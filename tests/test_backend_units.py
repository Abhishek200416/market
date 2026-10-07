"""Unit tests for quote quality, candles, quant determinism, risk controls, and paper accounting math."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import sys

sys.path.insert(0, "/app/backend")

import quality  # noqa: E402
import quant  # noqa: E402
import risk  # noqa: E402
import paper  # noqa: E402
import research  # noqa: E402
from core import now, stamp  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402


def _fresh_quote(symbol: str = "NSE:RELIANCE-EQ") -> dict:
    source = now().isoformat()
    return {
        "symbol": symbol,
        "source_timestamp": source,
        "timestamp": source,
        "freshness": "FRESH",
        "sequence": 1,
        "ltp": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "volume": 2000000,
    }


def _base_account() -> dict:
    return {
        "user_id": "u1",
        "starting_capital": 1000000.0,
        "cash": 1000000.0,
        "realized_pnl": 0.0,
        "fees_paid": 0.0,
        "peak_equity": 1000000.0,
        "positions": [],
        "orders": [],
        "trades": [],
        "risk": risk.RiskSettings().model_dump(),
        "kill_switch": False,
        "version": 0,
        "created_at": stamp(),
    }


def test_normalize_quote_handles_missing_and_future_source_time():
    missing = quality.normalize_quote("NSE:NIFTY50-INDEX", {"lp": "25000"})
    assert missing["freshness"] == "UNKNOWN"
    assert missing["source_timestamp"] is None
    assert missing["ltp"] == 25000.0

    future_ts = (now() + timedelta(seconds=10)).timestamp()
    future = quality.normalize_quote("NSE:NIFTY50-INDEX", {"lp": "25000", "tt": future_ts})
    assert future["freshness"] == "ANOMALY"


def test_assess_quote_detects_stale_out_of_order_and_duplicate():
    stale_quote = {
        "source_timestamp": (now() - timedelta(seconds=20)).isoformat(),
        "ltp": 100,
        "sequence": 2,
    }
    assert quality.assess_quote(stale_quote) == "STALE"

    newer = {
        "source_timestamp": now().isoformat(),
        "ltp": 100,
        "sequence": 5,
    }
    older = {
        "source_timestamp": (now() + timedelta(seconds=1)).isoformat(),
        "ltp": 100,
        "sequence": 4,
    }
    assert quality.assess_quote(newer, older) == "OUT_OF_ORDER"

    same_ts = now().isoformat()
    duplicate = {
        "source_timestamp": same_ts,
        "ltp": 100,
        "sequence": 7,
    }
    assert quality.assess_quote(duplicate, {"source_timestamp": same_ts, "sequence": 7}) == "DUPLICATE"


def test_normalize_candles_valid_duplicate_incomplete_and_future_cutoff():
    cutoff = int(now().timestamp())
    rows = [
        [cutoff - 1200, 100, 101, 99, 100.5, 10_000],
        [cutoff + 60, 100, 101, 99, 100.5, 10_000],
    ]
    candles = quality.normalize_candles("NSE:RELIANCE-EQ", rows, "5", cutoff)
    assert len(candles) == 1
    assert candles[0]["open"] == 100.0
    assert candles[0]["provider"] == "FYERS"

    with pytest.raises(HTTPException, match="Duplicate candle timestamp"):
        quality.normalize_candles("NSE:RELIANCE-EQ", [[1, 1, 2, 1, 1.5, 1], [1, 1, 2, 1, 1.6, 1]], "1", cutoff)

    with pytest.raises(HTTPException, match="Incomplete OHLCV"):
        quality.normalize_candles("NSE:RELIANCE-EQ", [[1, 2, 3]], "1", cutoff)


def test_indicator_calculation_is_deterministic():
    start = int(now().timestamp()) - 300 * 260
    candles = []
    for i in range(260):
        px = 100 + i * 0.2
        candles.append({
            "open": px,
            "high": px + 1,
            "low": px - 1,
            "close": px + 0.2,
            "volume": 100000 + i,
            "time": start + i * 300,
            "timestamp": now().isoformat(),
        })

    first = quant.indicators(candles)
    second = quant.indicators(candles)
    assert first == second
    assert first["close_200_sma"] is not None
    assert first["vwap_window"] is not None


def test_validate_order_accepts_valid_case_and_rejects_risk_breaches():
    account = _base_account()
    quote = _fresh_quote()
    accepted = risk.validate_order(account, quote, quantity=10, stop=98, target=106, fill=100.1, fees=2.5)
    assert accepted["risk_amount"] > 0
    assert accepted["risk_reward"] >= 2

    daily_lock = _base_account()
    daily_lock["trades"] = [{"timestamp": stamp(), "pnl": -25000}]
    with pytest.raises(HTTPException, match="Daily loss lock active"):
        risk.validate_order(daily_lock, quote, quantity=10, stop=98, target=106, fill=100.1, fees=2.5)

    duplicate_position = _base_account()
    duplicate_position["positions"] = [{"symbol": quote["symbol"], "quantity": 1, "entry": 100}]
    with pytest.raises(HTTPException, match="Duplicate position blocked"):
        risk.validate_order(duplicate_position, quote, quantity=10, stop=98, target=106, fill=100.1, fees=2.5)


def test_close_position_updates_cash_fees_and_realized_pnl(monkeypatch):
    account = _base_account()
    account["positions"] = [{
        "id": "pos-1",
        "symbol": "NSE:RELIANCE-EQ",
        "quantity": 10,
        "entry": 100.0,
        "entry_fees": 2.0,
        "stop": 95,
        "target": 110,
        "opened_at": stamp(),
    }]
    account["cash"] = 900000.0
    captured = {}

    async def fake_account_for(_):
        return account

    async def fake_persist(current, _):
        captured["account"] = current.copy()

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(paper, "account_for", fake_account_for)
    monkeypatch.setattr(paper, "persist", fake_persist)
    monkeypatch.setattr(paper, "audit", fake_audit)

    quote = _fresh_quote("NSE:RELIANCE-EQ")
    quote["bid"] = 110
    quote["ask"] = 110.2
    quote["ltp"] = 110.1

    result = asyncio.run(paper.close_position("u1", "pos-1", quote=quote, reason="TARGET"))
    assert result["order"]["side"] == "SELL"
    assert result["trade"]["reason"] == "TARGET"
    assert result["trade"]["pnl"] > 0
    assert captured["account"]["realized_pnl"] > 0
    assert captured["account"]["positions"] == []


def test_buy_sell_round_trip_conserves_cash_fees_and_realized_pnl_with_idempotency(monkeypatch):
    account = _base_account()
    account["cash"] = 1_000_000.0
    call_count = {"uid": 0}

    async def fake_account_for(_):
        return account

    async def fake_persist(_current, _old_version):
        return None

    async def fake_audit(*_args, **_kwargs):
        return None

    async def fake_get_quote(_user_id, _symbol):
        return {
            "symbol": "NSE:RELIANCE-EQ",
            "source_timestamp": now().isoformat(),
            "freshness": "FRESH",
            "ltp": 100.0,
            "bid": 99.8,
            "ask": 100.2,
            "volume": 2_000_000,
        }

    def fake_uid():
        call_count["uid"] += 1
        return f"id-{call_count['uid']}"

    monkeypatch.setattr(paper, "account_for", fake_account_for)
    monkeypatch.setattr(paper, "persist", fake_persist)
    monkeypatch.setattr(paper, "audit", fake_audit)
    monkeypatch.setattr(paper, "get_quote", fake_get_quote)
    monkeypatch.setattr(paper, "instrument", lambda _s: {"type": "EQUITY"})
    monkeypatch.setattr(paper, "uid", fake_uid)
    monkeypatch.setattr(paper, "validate_order", lambda *_args, **_kwargs: {"risk_amount": 25.0, "risk_reward": 2.4})

    buy_in = paper.OrderInput(symbol="NSE:RELIANCE-EQ", quantity=10, stop=98, target=105, idempotency_key="idem-buy-001")
    first = asyncio.run(paper.buy(buy_in, user={"id": "u1"}))
    assert first["order"]["side"] == "BUY"
    assert len(account["orders"]) == 1
    assert len(account["positions"]) == 1

    second = asyncio.run(paper.buy(buy_in, user={"id": "u1"}))
    assert second["idempotent"] is True
    assert len(account["orders"]) == 1
    assert len(account["positions"]) == 1

    position_id = account["positions"][0]["id"]
    close_quote = {
        "symbol": "NSE:RELIANCE-EQ",
        "source_timestamp": now().isoformat(),
        "freshness": "FRESH",
        "ltp": 100.0,
        "bid": 100.6,
        "ask": 100.8,
        "volume": 2_000_000,
    }
    closed = asyncio.run(paper.close_position("u1", position_id, quote=close_quote, reason="MANUAL"))
    assert closed["order"]["side"] == "SELL"
    assert closed["trade"]["entry_fees"] > 0
    assert closed["trade"]["exit_fees"] > 0

    entry_cost = first["order"]["fill"] * 10 + first["order"]["fees"]
    exit_credit = closed["order"]["fill"] * 10 - closed["order"]["fees"]
    expected_cash = round(1_000_000.0 - entry_cost + exit_credit, 2)
    assert account["cash"] == expected_cash
    assert account["realized_pnl"] == closed["trade"]["pnl"]
    assert round(account["cash"] - 1_000_000.0, 2) == account["realized_pnl"]
    assert account["fees_paid"] == round(first["order"]["fees"] + closed["order"]["fees"], 2)


def test_close_position_rejects_wrong_symbol_quote(monkeypatch):
    account = _base_account()
    account["positions"] = [{
        "id": "pos-1",
        "symbol": "NSE:RELIANCE-EQ",
        "quantity": 1,
        "entry": 100,
        "entry_fees": 1,
        "stop": 95,
        "target": 105,
        "opened_at": stamp(),
    }]

    async def fake_account_for(_):
        return account

    monkeypatch.setattr(paper, "account_for", fake_account_for)

    with pytest.raises(HTTPException, match="does not match position"):
        asyncio.run(
            paper.close_position(
                "u1",
                "pos-1",
                quote={
                    "symbol": "NSE:HDFCBANK-EQ",
                    "source_timestamp": now().isoformat(),
                    "freshness": "FRESH",
                    "ltp": 100,
                    "bid": 99.9,
                    "ask": 100.1,
                    "volume": 2_000_000,
                },
            )
        )


def test_refresh_closes_on_stop_at_bid_with_slippage(monkeypatch):
    account = _base_account()
    account["positions"] = [{
        "id": "pos-stop",
        "symbol": "NSE:RELIANCE-EQ",
        "quantity": 10,
        "entry": 100,
        "entry_fees": 2,
        "stop": 98,
        "target": 110,
        "opened_at": stamp(),
    }]

    async def fake_account_for(_):
        return account

    async def fake_persist(_current, _old_version):
        return None

    async def fake_audit(*_args, **_kwargs):
        return None

    async def fake_get_quote(_user_id, _symbol):
        return {
            "symbol": "NSE:RELIANCE-EQ",
            "source_timestamp": now().isoformat(),
            "freshness": "FRESH",
            "ltp": 97.8,
            "bid": 97.6,
            "ask": 97.9,
            "volume": 2_000_000,
        }

    monkeypatch.setattr(paper, "account_for", fake_account_for)
    monkeypatch.setattr(paper, "persist", fake_persist)
    monkeypatch.setattr(paper, "audit", fake_audit)
    monkeypatch.setattr(paper, "get_quote", fake_get_quote)

    result = asyncio.run(paper.refresh(user={"id": "u1"}))
    assert result["account"]["positions"] == []
    trade = account["trades"][0]
    assert trade["reason"] == "STOP"
    assert trade["exit"] == round(97.6 * 0.9995, 2)


def test_refresh_closes_on_target_and_stale_quote_blocks_closing(monkeypatch):
    account = _base_account()
    account["positions"] = [{
        "id": "pos-target",
        "symbol": "NSE:RELIANCE-EQ",
        "quantity": 10,
        "entry": 100,
        "entry_fees": 2,
        "stop": 95,
        "target": 101,
        "opened_at": stamp(),
    }]

    async def fake_account_for(_):
        return account

    async def fake_persist(_current, _old_version):
        return None

    async def fake_audit(*_args, **_kwargs):
        return None

    state = {"mode": "target"}

    async def fake_get_quote(_user_id, _symbol):
        if state["mode"] == "target":
            return {
                "symbol": "NSE:RELIANCE-EQ",
                "source_timestamp": now().isoformat(),
                "freshness": "FRESH",
                "ltp": 101.2,
                "bid": 101.0,
                "ask": 101.3,
                "volume": 2_000_000,
            }
        return {
            "symbol": "NSE:RELIANCE-EQ",
            "source_timestamp": (now() - timedelta(seconds=25)).isoformat(),
            "freshness": "STALE",
            "ltp": 94.0,
            "bid": 93.9,
            "ask": 94.1,
            "volume": 2_000_000,
        }

    monkeypatch.setattr(paper, "account_for", fake_account_for)
    monkeypatch.setattr(paper, "persist", fake_persist)
    monkeypatch.setattr(paper, "audit", fake_audit)
    monkeypatch.setattr(paper, "get_quote", fake_get_quote)

    result = asyncio.run(paper.refresh(user={"id": "u1"}))
    assert result["account"]["positions"] == []
    assert account["trades"][0]["reason"] == "TARGET"

    account["positions"] = [{
        "id": "pos-stale",
        "symbol": "NSE:RELIANCE-EQ",
        "quantity": 1,
        "entry": 100,
        "entry_fees": 1,
        "stop": 99,
        "target": 101,
        "opened_at": stamp(),
    }]
    account["trades"] = []
    state["mode"] = "stale"
    with pytest.raises(HTTPException, match="DATA STALE"):
        asyncio.run(paper.refresh(user={"id": "u1"}))
    assert account["positions"], "stale quote must not close the position"
    assert account["trades"] == []


def test_risk_lock_thresholds_cannot_be_relaxed_after_daily_or_streak_breach(monkeypatch):
    account = _base_account()
    account["risk"]["daily_loss_limit"] = 2
    account["risk"]["max_consecutive_losses"] = 3
    account["trades"] = [
        {"timestamp": stamp(), "pnl": -9000},
        {"timestamp": stamp(), "pnl": -8000},
        {"timestamp": stamp(), "pnl": -6000},
    ]

    async def fake_account_for(_):
        return account

    async def fake_persist(_current, _old_version):
        return None

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(paper, "account_for", fake_account_for)
    monkeypatch.setattr(paper, "persist", fake_persist)
    monkeypatch.setattr(paper, "audit", fake_audit)

    with pytest.raises(HTTPException, match="Daily loss lock active"):
        asyncio.run(
            paper.risk(
                risk.RiskSettings(daily_loss_limit=3, max_consecutive_losses=3),
                user={"id": "u1"},
            )
        )

    with pytest.raises(HTTPException, match="Loss-streak lock active"):
        asyncio.run(
            paper.risk(
                risk.RiskSettings(daily_loss_limit=2, max_consecutive_losses=4),
                user={"id": "u1"},
            )
        )


def test_open_position_losses_are_counted_toward_daily_loss_lock_on_new_buy():
    account = _base_account()
    account["trades"] = [{"timestamp": stamp(), "pnl": -15_000}]
    account["open_pnl_for_risk"] = -6_000
    quote = _fresh_quote("NSE:RELIANCE-EQ")

    with pytest.raises(HTTPException, match="Daily loss lock active"):
        risk.validate_order(account, quote, quantity=1, stop=95, target=111, fill=100.1, fees=1.0)


def test_buy_rechecks_quote_freshness_before_commit(monkeypatch):
    account = _base_account()
    persisted = {"called": False}
    checks = {"count": 0}

    async def fake_account_for(_):
        return account

    async def fake_persist(_current, _old_version):
        persisted["called"] = True

    async def fake_audit(*_args, **_kwargs):
        return None

    async def fake_get_quote(_user_id, _symbol):
        return {
            "symbol": "NSE:RELIANCE-EQ",
            "source_timestamp": now().isoformat(),
            "freshness": "FRESH",
            "ltp": 100,
            "bid": 99.9,
            "ask": 100.1,
            "volume": 2_000_000,
        }

    def fake_require_fresh(_quote):
        checks["count"] += 1
        if checks["count"] == 2:
            raise HTTPException(409, "DATA STALE — trading and signal generation blocked.")

    monkeypatch.setattr(paper, "account_for", fake_account_for)
    monkeypatch.setattr(paper, "persist", fake_persist)
    monkeypatch.setattr(paper, "audit", fake_audit)
    monkeypatch.setattr(paper, "get_quote", fake_get_quote)
    monkeypatch.setattr(paper, "instrument", lambda _s: {"type": "EQUITY"})
    monkeypatch.setattr(paper, "validate_order", lambda *_args, **_kwargs: {"risk_amount": 10.0, "risk_reward": 2.0})
    monkeypatch.setattr(paper, "require_fresh", fake_require_fresh)

    with pytest.raises(HTTPException, match="DATA STALE"):
        asyncio.run(
            paper.buy(
                paper.OrderInput(symbol="NSE:RELIANCE-EQ", quantity=1, stop=98, target=104, idempotency_key="recheck-001"),
                user={"id": "u1"},
            )
        )
    assert checks["count"] == 2
    assert persisted["called"] is False


def test_buy_with_kill_switch_blocks_without_provider_calls(monkeypatch):
    account = _base_account()
    account["kill_switch"] = True
    called = {"provider": 0}

    async def fake_account_for(_):
        return account

    async def fake_get_quote(_user_id, _symbol):
        called["provider"] += 1
        return _fresh_quote(_symbol)

    monkeypatch.setattr(paper, "account_for", fake_account_for)
    monkeypatch.setattr(paper, "get_quote", fake_get_quote)

    with pytest.raises(HTTPException, match="Kill switch engaged"):
        asyncio.run(
            paper.buy(
                paper.OrderInput(symbol="NSE:RELIANCE-EQ", quantity=1, stop=98, target=104, idempotency_key="kill-001"),
                user={"id": "u1"},
            )
        )
    assert called["provider"] == 0


class _FakeCursor:
    def __init__(self, items):
        self._items = items

    async def to_list(self, _limit):
        return [copy.deepcopy(i) for i in self._items]


class _FakeCollection:
    def __init__(self, items=None, key=None):
        self.items = list(items or [])
        self.key = key

    def find(self, query, _projection=None):
        results = []
        for item in self.items:
            if all(
                (
                    item.get(k) <= v["$lte"] if isinstance(v, dict) and "$lte" in v else item.get(k) == v
                )
                for k, v in query.items()
            ):
                results.append(item)
        return _FakeCursor(results)

    async def find_one(self, query, _projection=None):
        for item in self.items:
            if all(item.get(k) == v for k, v in query.items()):
                return copy.deepcopy(item)
        return None

    async def insert_one(self, doc):
        if self.key and any(existing.get(self.key) == doc.get(self.key) for existing in self.items):
            raise DuplicateKeyError("duplicate")
        self.items.append(copy.deepcopy(doc))


def test_ledger_settlement_exact_horizon_pending_and_idempotent(monkeypatch):
    now_iso = stamp()
    target1 = 1767261660
    target2 = 1767261720
    target3 = 1767261780
    predictions = [
        {
            "prediction_id": "p1",
            "user_id": "u1",
            "asset": "NSE:RELIANCE-EQ",
            "provider": "UPSTOX",
            "entry": 100.0,
            "direction": "UP",
            "horizon_end": datetime.fromtimestamp(target1, timezone.utc).isoformat(),
        },
        {
            "prediction_id": "p2",
            "user_id": "u1",
            "asset": "NSE:HDFCBANK-EQ",
            "provider": "FYERS",
            "entry": 200.0,
            "direction": "DOWN",
            "horizon_end": datetime.fromtimestamp(target2, timezone.utc).isoformat(),
        },
        {
            "prediction_id": "p3",
            "user_id": "u1",
            "asset": "NSE:INFY-EQ",
            "provider": "UPSTOX",
            "entry": 150.0,
            "direction": "UP",
            "horizon_end": datetime.fromtimestamp(target3, timezone.utc).isoformat(),
        },
    ]
    outcomes = [{"prediction_id": "p3", "user_id": "u1", "actual_return": 0.001, "actual_direction": "UP"}]
    before_predictions = copy.deepcopy(predictions)

    class _FakeDB:
        pass

    _FakeDB.predictions = _FakeCollection(predictions)
    _FakeDB.outcomes = _FakeCollection(outcomes, key="prediction_id")

    provider_calls = []

    class _Provider:
        def __init__(self, provider_name):
            self.name = provider_name.upper()

        async def candles(self, symbol, _resolution, _start, _end):
            if symbol == "NSE:RELIANCE-EQ":
                # exact horizon bar => row where time + 60 == target
                return [
                    {"time": target1 - 60, "close": 101.0, "timestamp": datetime.fromtimestamp(target1, timezone.utc).isoformat()},
                    {"time": target1, "close": 101.2, "timestamp": datetime.fromtimestamp(target1 + 60, timezone.utc).isoformat()},
                ]
            if symbol == "NSE:HDFCBANK-EQ":
                # no exact match for target
                return [{"time": target2 - 55, "close": 199.0, "timestamp": datetime.fromtimestamp(target2 - 55, timezone.utc).isoformat()}]
            return []

    async def fake_market_provider(_user_id, provider_name=None):
        provider_calls.append(provider_name)
        return _Provider(provider_name or "fyers")

    monkeypatch.setattr(research, "db", _FakeDB)
    monkeypatch.setattr(research, "market_provider", fake_market_provider)
    monkeypatch.setattr(research, "stamp", lambda: now_iso)

    first = asyncio.run(research.settle(user={"id": "u1"}))
    assert first["settled"] == 1
    assert len(_FakeDB.outcomes.items) == 2
    assert any(x["prediction_id"] == "p1" for x in _FakeDB.outcomes.items)
    assert not any(x["prediction_id"] == "p2" for x in _FakeDB.outcomes.items)
    assert _FakeDB.predictions.items == before_predictions
    assert provider_calls[:2] == ["upstox", "fyers"]

    second = asyncio.run(research.settle(user={"id": "u1"}))
    assert second["settled"] == 0
    assert len(_FakeDB.outcomes.items) == 2
