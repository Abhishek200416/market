"""Isolated unit tests for Upstox OAuth state handling and market-route strictness."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote as encode_path

import httpx
import pytest
from fastapi import HTTPException

import sys

sys.path.insert(0, "/app/backend")

import upstox  # noqa: E402
import upstox_oauth  # noqa: E402
from auth import digest  # noqa: E402


class _FakeRequest:
    def __init__(self, session_token: str):
        self.cookies = {"terminal_session": session_token}


class _FakeOAuthStates:
    def __init__(self, rows=None):
        self.rows = [copy.deepcopy(r) for r in (rows or [])]
        self.inserted = []

    async def insert_one(self, doc):
        self.inserted.append(copy.deepcopy(doc))
        self.rows.append(copy.deepcopy(doc))

    async def find_one_and_delete(self, query, projection=None):
        for idx, row in enumerate(self.rows):
            if row.get("state_hash") != query.get("state_hash"):
                continue
            if row.get("user_id") != query.get("user_id"):
                continue
            if row.get("session_hash") != query.get("session_hash"):
                continue
            expires_rule = query.get("expires_at", {})
            gt = expires_rule.get("$gt")
            if gt and not (row.get("expires_at") and row["expires_at"] > gt):
                continue
            found = self.rows.pop(idx)
            if projection and projection.get("_id") == 0:
                found.pop("_id", None)
            return copy.deepcopy(found)
        return None


class _FakeCredentialsCollection:
    def __init__(self):
        self.updated = []

    async def update_one(self, flt, update, upsert=False):
        self.updated.append({"filter": copy.deepcopy(flt), "update": copy.deepcopy(update), "upsert": upsert})


class _FakeDB:
    def __init__(self, oauth_rows=None):
        self.oauth_states = _FakeOAuthStates(oauth_rows)
        self.credentials = _FakeCredentialsCollection()


class _HTTPResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"status": "success", "data": {}}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("http error", request=None, response=None)

    def json(self):
        return self._payload


class _AsyncClientStub:
    def __init__(self, recorder, responses):
        self.recorder = recorder
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, data=None, headers=None):
        self.recorder.append({"method": "POST", "url": url, "data": copy.deepcopy(data), "headers": copy.deepcopy(headers)})
        return self.responses["post"]

    async def get(self, url, headers=None, params=None):
        self.recorder.append({"method": "GET", "url": url, "headers": copy.deepcopy(headers), "params": copy.deepcopy(params)})
        key = (url, tuple(sorted((params or {}).items())))
        return self.responses.get(key, self.responses.get(url, self.responses.get("default", _HTTPResponse(404))))


def _run(coro):
    return asyncio.run(coro)


# OAuth registration/start/callback state safety tests
def test_registration_configuration_returns_pending_for_malformed_or_local_origin(monkeypatch):
    monkeypatch.setenv("BROKER_PUBLIC_ORIGIN", "http://localhost:3000")
    pending = upstox_oauth.registration_configuration()
    assert pending["oauth_ready"] is False
    assert pending["oauth_status"] == "PENDING_HTTPS_HOSTNAME"
    assert pending["website_url"] is None
    assert pending["callback_url"] is None


def test_oauth_start_pending_gate_stops_before_credentials_or_state_insert(monkeypatch):
    called = {"credentials": 0, "insert": 0, "audit": 0}

    async def fake_credentials(_user_id, _provider):
        called["credentials"] += 1
        return {}

    async def fake_audit(*_args, **_kwargs):
        called["audit"] += 1

    fake_db = _FakeDB()
    original_insert = fake_db.oauth_states.insert_one

    async def tracked_insert(doc):
        called["insert"] += 1
        await original_insert(doc)

    monkeypatch.setattr(fake_db.oauth_states, "insert_one", tracked_insert)
    monkeypatch.setattr(upstox_oauth, "db", fake_db)
    monkeypatch.setattr(upstox_oauth, "credentials", fake_credentials)
    monkeypatch.setattr(upstox_oauth, "audit", fake_audit)
    monkeypatch.setattr(upstox_oauth, "registration_configuration", lambda: {"oauth_ready": False})

    with pytest.raises(HTTPException, match="pending"):
        _run(upstox_oauth.start(_FakeRequest("sess-1"), user={"id": "u1"}))

    assert called == {"credentials": 0, "insert": 0, "audit": 0}


def test_oauth_start_stores_hashed_state_user_session_expiry_and_redirect(monkeypatch):
    fake_db = _FakeDB()
    monkeypatch.setattr(upstox_oauth, "db", fake_db)
    monkeypatch.setattr(upstox_oauth, "audit", lambda *_args, **_kwargs: asyncio.sleep(0))

    async def fake_credentials(_user_id, _provider):
        return {"api_key": "k1", "api_secret": "s1"}

    monkeypatch.setattr(upstox_oauth, "credentials", fake_credentials)
    monkeypatch.setattr(upstox_oauth, "registration_configuration", lambda: {
        "oauth_ready": True,
        "callback_url": "https://unit.example.com/api/integrations/upstox/oauth/callback",
    })
    monkeypatch.setattr(upstox_oauth.secrets, "token_urlsafe", lambda _n: "raw-state-token")
    monkeypatch.setattr(upstox_oauth, "now", lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setenv("UPSTOX_BASE_URL", "https://api.upstox.test")

    result = _run(upstox_oauth.start(_FakeRequest("session-cookie"), user={"id": "u1"}))

    assert "raw-state-token" in result["authorize_url"]
    assert "/v2/login/authorization/dialog" in result["authorize_url"]
    saved = fake_db.oauth_states.inserted[0]
    assert saved["state_hash"] == digest("raw-state-token")
    assert saved["state_hash"] != "raw-state-token"
    assert saved["user_id"] == "u1"
    assert saved["session_hash"] == digest("session-cookie")
    assert saved["expires_at"] == datetime(2026, 2, 10, 10, 10, tzinfo=timezone.utc)
    assert saved["redirect_uri"] == "https://unit.example.com/api/integrations/upstox/oauth/callback"


@pytest.mark.parametrize("state_rows", [
    [],
    [{"state_hash": digest("s1"), "user_id": "another-user", "session_hash": digest("sess"), "expires_at": datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc)}],
    [{"state_hash": digest("s1"), "user_id": "u1", "session_hash": digest("other-session"), "expires_at": datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc)}],
    [{"state_hash": digest("s1"), "user_id": "u1", "session_hash": digest("sess"), "expires_at": datetime(2026, 2, 10, 9, 59, tzinfo=timezone.utc)}],
])
def test_oauth_callback_wrong_user_session_expired_or_replay_returns_400_without_exchange(monkeypatch, state_rows):
    calls = []
    fake_db = _FakeDB(state_rows)
    monkeypatch.setattr(upstox_oauth, "db", fake_db)
    monkeypatch.setattr(upstox_oauth, "registration_configuration", lambda: {
        "oauth_ready": True,
        "callback_url": "https://unit.example.com/api/integrations/upstox/oauth/callback",
        "website_url": "https://unit.example.com",
    })
    monkeypatch.setattr(upstox_oauth, "now", lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(upstox_oauth.httpx, "AsyncClient", lambda timeout=20: _AsyncClientStub(calls, {"post": _HTTPResponse()}))

    with pytest.raises(HTTPException, match="Invalid, expired or already-used"):
        _run(upstox_oauth.callback(_FakeRequest("sess"), code="c1", state="s1", user={"id": "u1"}))

    assert calls == []


def test_oauth_callback_blocks_credential_fingerprint_change_without_exchange(monkeypatch):
    state_row = {
        "state_hash": digest("s1"),
        "user_id": "u1",
        "session_hash": digest("sess"),
        "expires_at": datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc),
        "credential_fingerprint": "old-fingerprint",
        "redirect_uri": "https://unit.example.com/api/integrations/upstox/oauth/callback",
    }
    calls = []
    fake_db = _FakeDB([state_row])
    monkeypatch.setattr(upstox_oauth, "db", fake_db)
    monkeypatch.setattr(upstox_oauth, "now", lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(upstox_oauth, "registration_configuration", lambda: {
        "oauth_ready": True,
        "callback_url": "https://unit.example.com/api/integrations/upstox/oauth/callback",
        "website_url": "https://unit.example.com",
    })

    async def fake_credentials(_uid, _provider):
        return {"api_key": "new-key", "api_secret": "new-secret"}

    monkeypatch.setattr(upstox_oauth, "credentials", fake_credentials)
    monkeypatch.setattr(upstox_oauth.httpx, "AsyncClient", lambda timeout=20: _AsyncClientStub(calls, {"post": _HTTPResponse()}))

    with pytest.raises(HTTPException, match="configuration changed"):
        _run(upstox_oauth.callback(_FakeRequest("sess"), code="c1", state="s1", user={"id": "u1"}))

    assert calls == []


def test_oauth_callback_blocks_changed_redirect_without_exchange(monkeypatch):
    state_row = {
        "state_hash": digest("s1"),
        "user_id": "u1",
        "session_hash": digest("sess"),
        "expires_at": datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc),
        "credential_fingerprint": "same-fingerprint",
        "redirect_uri": "https://old.example.com/api/integrations/upstox/oauth/callback",
    }
    fake_db = _FakeDB([state_row])
    calls = []

    monkeypatch.setattr(upstox_oauth, "db", fake_db)
    monkeypatch.setattr(upstox_oauth, "now", lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(upstox_oauth, "registration_configuration", lambda: {
        "oauth_ready": True,
        "callback_url": "https://new.example.com/api/integrations/upstox/oauth/callback",
        "website_url": "https://new.example.com",
    })

    creds = {"api_key": "k1", "api_secret": "s1"}
    expected_fp = upstox_oauth.hashlib.sha256(json.dumps(creds, sort_keys=True).encode()).hexdigest()
    fake_db.oauth_states.rows[0]["credential_fingerprint"] = expected_fp

    async def fake_credentials(_uid, _provider):
        return creds

    monkeypatch.setattr(upstox_oauth, "credentials", fake_credentials)
    monkeypatch.setattr(upstox_oauth.httpx, "AsyncClient", lambda timeout=20: _AsyncClientStub(calls, {"post": _HTTPResponse()}))

    with pytest.raises(HTTPException, match="configuration changed"):
        _run(upstox_oauth.callback(_FakeRequest("sess"), code="c1", state="s1", user={"id": "u1"}))

    assert calls == []


def test_oauth_callback_success_posts_form_encrypts_token_and_redirects_clean(monkeypatch):
    creds = {"api_key": "k1", "api_secret": "s1"}
    callback_url = "https://unit.example.com/api/integrations/upstox/oauth/callback"
    fingerprint = upstox_oauth.hashlib.sha256(json.dumps(creds, sort_keys=True).encode()).hexdigest()
    state_row = {
        "state_hash": digest("s1"),
        "user_id": "u1",
        "session_hash": digest("sess"),
        "expires_at": datetime(2026, 2, 10, 11, 0, tzinfo=timezone.utc),
        "credential_fingerprint": fingerprint,
        "redirect_uri": callback_url,
    }
    fake_db = _FakeDB([state_row])
    calls = []
    audits = []
    encrypted_payloads = []

    class _Vault:
        def encrypt(self, value: bytes):
            encrypted_payloads.append(value.decode())
            return b"ciphertext"

    async def fake_credentials(_uid, _provider):
        return copy.deepcopy(creds)

    async def fake_audit(user_id, event, detail=None):
        audits.append((user_id, event, detail))

    monkeypatch.setattr(upstox_oauth, "db", fake_db)
    monkeypatch.setattr(upstox_oauth, "vault", _Vault())
    monkeypatch.setattr(upstox_oauth, "credentials", fake_credentials)
    monkeypatch.setattr(upstox_oauth, "audit", fake_audit)
    monkeypatch.setattr(upstox_oauth, "now", lambda: datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(upstox_oauth, "stamp", lambda: "2026-02-10T10:00:00+00:00")
    monkeypatch.setattr(upstox_oauth, "registration_configuration", lambda: {
        "oauth_ready": True,
        "callback_url": callback_url,
        "website_url": "https://unit.example.com",
    })
    monkeypatch.setenv("UPSTOX_BASE_URL", "https://api.upstox.test")
    monkeypatch.setattr(
        upstox_oauth.httpx,
        "AsyncClient",
        lambda timeout=20: _AsyncClientStub(calls, {"post": _HTTPResponse(payload={"access_token": "token-abc"})}),
    )

    response = _run(upstox_oauth.callback(_FakeRequest("sess"), code="code-1", state="s1", user={"id": "u1"}))

    assert response.status_code == 303
    location = response.headers.get("location", "")
    assert location == "https://unit.example.com/connections?broker=upstox&authorization=complete"
    assert "code-1" not in location and "token-abc" not in location and "state=" not in location

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://api.upstox.test/v2/login/authorization/token"
    assert calls[0]["headers"] == {"Accept": "application/json"}
    assert calls[0]["data"] == {
        "code": "code-1",
        "client_id": "k1",
        "client_secret": "s1",
        "redirect_uri": callback_url,
        "grant_type": "authorization_code",
    }

    saved = fake_db.credentials.updated[0]
    assert saved["filter"] == {"user_id": "u1", "provider": "upstox"}
    assert saved["update"]["$set"]["encrypted"] == "ciphertext"
    assert "token-abc" in encrypted_payloads[0]
    assert any(event == "upstox_oauth_completed" for _uid, event, _detail in audits)


# Upstox market quote/candle route correctness tests
def test_upstox_quote_uses_exact_get_bearer_and_matching_instrument_only(monkeypatch):
    calls = []
    monkeypatch.setenv("UPSTOX_BASE_URL", "https://api.upstox.test")

    async def fake_resolve(_symbol):
        return {"instrument_key": "NSE_EQ|INE002A01018"}

    monkeypatch.setattr(upstox, "resolve_instrument", fake_resolve)
    quote_payload = {
        "status": "success",
        "data": {
            "a": {"instrument_token": "NSE_EQ|WRONG", "last_price": "100", "net_change": "1", "timestamp": None, "depth": {}},
            "b": {"instrument_token": "NSE_EQ|INE002A01018", "last_price": "101", "net_change": "1", "timestamp": None, "depth": {}},
        },
    }
    monkeypatch.setattr(
        upstox.httpx,
        "AsyncClient",
        lambda timeout=20: _AsyncClientStub(calls, {"default": _HTTPResponse(payload=quote_payload)}),
    )

    provider = upstox.UpstoxMarketDataProvider({"access_token": "token-123"})
    result = _run(provider.quote("NSE:RELIANCE-EQ"))

    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://api.upstox.test/v2/market-quote/quotes"
    assert calls[0]["params"] == {"instrument_key": "NSE_EQ|INE002A01018"}
    assert calls[0]["headers"]["Authorization"] == "Bearer token-123"
    assert result["instrument_key"] == "NSE_EQ|INE002A01018"
    assert result["freshness"] == "UNKNOWN"
    assert "order" not in calls[0]["url"].lower() and "profile" not in calls[0]["url"].lower()


def test_upstox_candles_use_v3_history_then_intraday_with_encoded_instrument(monkeypatch):
    calls = []
    monkeypatch.setenv("UPSTOX_BASE_URL", "https://api.upstox.test")

    async def fake_resolve(_symbol):
        return {"instrument_key": "NSE_EQ|INE002A01018"}

    monkeypatch.setattr(upstox, "resolve_instrument", fake_resolve)
    monkeypatch.setattr(upstox, "now", lambda: datetime(2026, 2, 10, 6, 0, tzinfo=timezone.utc))

    encoded_key = encode_path("NSE_EQ|INE002A01018", safe="")
    history_url = f"https://api.upstox.test/v3/historical-candle/{encoded_key}/minutes/5/2026-02-09/2026-02-08"
    intraday_url = f"https://api.upstox.test/v3/historical-candle/intraday/{encoded_key}/minutes/5"
    responses = {
        history_url: _HTTPResponse(payload={"status": "success", "data": {"candles": [["2026-02-09T09:20:00+05:30", 100, 101, 99, 100.5, 1000]]}}),
        intraday_url: _HTTPResponse(payload={"status": "success", "data": {"candles": [["2026-02-10T09:20:00+05:30", 101, 102, 100, 101.5, 1200]]}}),
    }
    monkeypatch.setattr(upstox.httpx, "AsyncClient", lambda timeout=20: _AsyncClientStub(calls, responses))

    provider = upstox.UpstoxMarketDataProvider({"access_token": "token-123"})
    ist = timezone(timedelta(hours=5, minutes=30))
    start = int(datetime(2026, 2, 8, 0, 0, tzinfo=ist).timestamp())
    end = int(datetime(2026, 2, 10, 15, 0, tzinfo=ist).timestamp())
    candles = _run(provider.candles("NSE:RELIANCE-EQ", "5", start, end))

    called_urls = [c["url"] for c in calls]
    assert history_url in called_urls
    assert intraday_url in called_urls
    assert all("/v3/historical-candle" in url for url in called_urls)
    assert all("/order" not in url and "/profile" not in url for url in called_urls)
    assert all(c["headers"]["Authorization"] == "Bearer token-123" for c in calls)
    assert len(candles) == 2
    assert all(c["provider"] == "UPSTOX" for c in candles)
