"""Integration tests for auth, connections, dashboard, risk and fail-closed execution flows."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests


def _public_base_url() -> str:
    env_value = os.environ.get("REACT_APP_BACKEND_URL")
    if env_value:
        return env_value.rstrip("/")

    frontend_env = Path("/app/frontend/.env")
    if frontend_env.exists():
        for line in frontend_env.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value.rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL is required for public endpoint tests")


BASE_URL = _public_base_url()
API_BASE = f"{BASE_URL}/api"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _register(session: requests.Session, prefix: str = "qa") -> tuple[dict, str]:
    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    password = "TerminalTest#2026"
    payload = {"email": email, "password": password, "name": "QA User"}
    response = session.post(f"{API_BASE}/auth/register", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["user"]["email"] == email
    assert "password" not in str(data).lower()
    assert data.get("csrf_token")
    return payload, data["csrf_token"]


def test_health_and_overview_anonymous_disconnected_state():
    response = requests.get(f"{API_BASE}/health", timeout=25)
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "PAPER"
    assert body["live_enabled"] is False

    overview = requests.get(f"{API_BASE}/overview", timeout=25)
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["user"] is None
    assert payload["account"] is None
    assert payload["decision"] == "NO TRADE"


def test_auth_cookie_csrf_and_logout_flow():
    session = _session()
    registration, csrf_token = _register(session, "auth")

    set_cookie = session.post(f"{API_BASE}/auth/login", json=registration)
    assert set_cookie.status_code == 200
    csrf_token = set_cookie.json()["csrf_token"]
    cookie_header = set_cookie.headers.get("set-cookie", "")
    assert "terminal_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "SameSite=" in cookie_header

    me = session.get(f"{API_BASE}/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == registration["email"]

    blocked = session.put(
        f"{API_BASE}/connections/gemini",
        json={"values": {"api_key": "dummy"}},
    )
    assert blocked.status_code == 403

    session.headers["X-CSRF-Token"] = csrf_token
    logout = session.post(f"{API_BASE}/auth/logout")
    assert logout.status_code == 200
    assert logout.json()["ok"] is True

    after_logout = session.get(f"{API_BASE}/auth/me")
    assert after_logout.status_code == 200
    assert after_logout.json()["user"] is None


def test_auth_validation_and_unsafe_origin_blocked():
    unsafe = requests.post(
        f"{API_BASE}/auth/register",
        json={"email": f"unsafe-{uuid.uuid4().hex[:8]}@example.com", "password": "TerminalTest#2026", "name": "Unsafe"},
        headers={"Origin": "https://evil.example.com", "Content-Type": "application/json"},
        timeout=25,
    )
    assert unsafe.status_code == 403

    invalid = requests.post(
        f"{API_BASE}/auth/register",
        json={"email": "invalid-email", "password": "short", "name": "x"},
        timeout=25,
    )
    assert invalid.status_code == 422


def test_connections_masking_isolation_and_graceful_invalid_test():
    a = _session()
    _, csrf_a = _register(a, "conn-a")
    a.headers["X-CSRF-Token"] = csrf_a

    save = a.put(f"{API_BASE}/connections/gemini", json={"values": {"api_key": "not-a-real-key"}})
    assert save.status_code == 200
    rows = save.json()["connections"]
    gemini = next(x for x in rows if x["provider"] == "gemini")
    assert gemini["status"] == "UNTESTED"
    assert "encrypted" not in gemini
    assert "api_key" in gemini["configured_fields"]

    tested = a.post(f"{API_BASE}/connections/gemini/test")
    assert tested.status_code == 200
    tested_body = tested.json()
    assert tested_body["ok"] is False
    tested_gemini = next(x for x in tested_body["connections"] if x["provider"] == "gemini")
    assert tested_gemini["status"] == "ERROR"
    assert "failed" in (tested_gemini.get("error") or "").lower()

    b = _session()
    _, csrf_b = _register(b, "conn-b")
    b.headers["X-CSRF-Token"] = csrf_b
    b_rows = b.get(f"{API_BASE}/connections")
    assert b_rows.status_code == 200
    b_gemini = next(x for x in b_rows.json()["connections"] if x["provider"] == "gemini")
    assert b_gemini["status"] == "DISCONNECTED"
    assert b_gemini["configured_fields"] == []

    anon = requests.get(f"{API_BASE}/connections", timeout=25)
    assert anon.status_code == 401


def test_risk_save_validation_and_persistence_and_default_capital():
    session = _session()
    _, csrf = _register(session, "risk")
    session.headers["X-CSRF-Token"] = csrf

    paper_before = session.get(f"{API_BASE}/paper")
    assert paper_before.status_code == 200
    account = paper_before.json()["account"]
    assert account["starting_capital"] == 1000000.0
    assert account["cash"] == 1000000.0

    invalid = session.put(
        f"{API_BASE}/paper/risk",
        json={
            "risk_per_trade": 2.5,
            "daily_loss_limit": 2,
            "max_consecutive_losses": 3,
            "max_trades_day": 10,
            "cooldown_seconds": 60,
            "max_exposure": 30,
            "max_position": 10,
            "min_risk_reward": 2,
            "min_volume": 1000,
            "max_spread_bps": 25,
        },
    )
    assert invalid.status_code == 422

    payload = {
        "risk_per_trade": 1.2,
        "daily_loss_limit": 3.5,
        "max_consecutive_losses": 3,
        "max_trades_day": 8,
        "cooldown_seconds": 90,
        "max_exposure": 35,
        "max_position": 12,
        "min_risk_reward": 2,
        "min_volume": 1000,
        "max_spread_bps": 20,
    }
    saved = session.put(f"{API_BASE}/paper/risk", json=payload)
    assert saved.status_code == 200
    assert saved.json()["risk"]["risk_per_trade"] == 1.2

    after = session.get(f"{API_BASE}/paper")
    assert after.status_code == 200
    assert after.json()["account"]["risk"]["daily_loss_limit"] == 3.5
    assert after.json()["account"]["risk"]["cooldown_seconds"] == 90


def test_fail_closed_without_providers_and_no_live_route():
    session = _session()
    _, csrf = _register(session, "closed")
    session.headers["X-CSRF-Token"] = csrf

    order = session.post(
        f"{API_BASE}/paper/orders",
        json={
            "symbol": "NSE:RELIANCE-EQ",
            "quantity": 1,
            "stop": 2000,
            "target": 3000,
            "idempotency_key": uuid.uuid4().hex,
        },
    )
    assert order.status_code == 409
    assert "disconnected" in order.json()["detail"].lower()

    research = session.post(f"{API_BASE}/research/run", json={"symbol": "NSE:NIFTY50-INDEX"}, timeout=40)
    assert research.status_code == 409
    assert "disconnected" in research.json()["detail"].lower()

    unknown_live = session.post(f"{API_BASE}/live/orders", json={})
    assert unknown_live.status_code == 404


def test_existing_cookie_session_can_recover_csrf_then_mutate_and_still_block_foreign_origin():
    session = _session()
    registration, _csrf = _register(session, "csrf-recover")

    relogin = session.post(f"{API_BASE}/auth/login", json=registration)
    assert relogin.status_code == 200

    # Simulate new tab with cleared sessionStorage: cookie exists, CSRF header missing.
    blocked = session.put(
        f"{API_BASE}/paper/risk",
        json={
            "risk_per_trade": 1,
            "daily_loss_limit": 2,
            "max_consecutive_losses": 3,
            "max_trades_day": 10,
            "cooldown_seconds": 60,
            "max_exposure": 30,
            "max_position": 10,
            "min_risk_reward": 2,
            "min_volume": 1000,
            "max_spread_bps": 25,
        },
    )
    assert blocked.status_code == 403

    csrf_fetch = session.get(f"{API_BASE}/auth/csrf")
    assert csrf_fetch.status_code == 200
    csrf_token = csrf_fetch.json()["csrf_token"]
    session.headers["X-CSRF-Token"] = csrf_token

    allowed = session.put(
        f"{API_BASE}/paper/risk",
        json={
            "risk_per_trade": 1.1,
            "daily_loss_limit": 2,
            "max_consecutive_losses": 3,
            "max_trades_day": 10,
            "cooldown_seconds": 60,
            "max_exposure": 30,
            "max_position": 10,
            "min_risk_reward": 2,
            "min_volume": 1000,
            "max_spread_bps": 25,
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["risk"]["risk_per_trade"] == 1.1

    foreign = session.put(
        f"{API_BASE}/paper/risk",
        json={
            "risk_per_trade": 1,
            "daily_loss_limit": 2,
            "max_consecutive_losses": 3,
            "max_trades_day": 10,
            "cooldown_seconds": 60,
            "max_exposure": 30,
            "max_position": 10,
            "min_risk_reward": 2,
            "min_volume": 1000,
            "max_spread_bps": 25,
        },
        headers={"Origin": "https://evil.example.com", "X-CSRF-Token": csrf_token, "Content-Type": "application/json"},
    )
    assert foreign.status_code == 403
