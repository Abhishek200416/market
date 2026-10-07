"""Regression tests for Upstox adapter strictness, OAuth gate metadata, and provider selection API."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from fastapi import HTTPException

import sys

sys.path.insert(0, "/app/backend")

import upstox  # noqa: E402


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
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


def _register_and_auth() -> tuple[requests.Session, str, str]:
    session = _session()
    email = f"upstox-reg-{uuid.uuid4().hex[:10]}@example.com"
    password = "TerminalTest#2026"
    payload = {"email": email, "password": password, "name": "Upstox QA"}
    response = session.post(f"{API_BASE}/auth/register", json=payload, timeout=30)
    assert response.status_code == 200, response.text
    csrf = response.json().get("csrf_token")
    assert isinstance(csrf, str) and csrf
    session.headers["X-CSRF-Token"] = csrf
    return session, email, password


# Upstox instrument-mapping strictness
def test_resolve_from_catalog_maps_nifty_50_exact_official_key():
    rows = [
        {
            "segment": "NSE_INDEX",
            "name": "Nifty 50",
            "trading_symbol": "NIFTY",
            "instrument_type": "INDEX",
            "instrument_key": "NSE_INDEX|Nifty 50",
        }
    ]
    resolved = upstox.resolve_from_catalog("NSE:NIFTY50-INDEX", rows)
    assert resolved["instrument_key"] == "NSE_INDEX|Nifty 50"


def test_resolve_from_catalog_rejects_ambiguous_or_missing_mapping():
    duplicate = [
        {"segment": "NSE_INDEX", "name": "Nifty 50", "instrument_key": "NSE_INDEX|Nifty 50"},
        {"segment": "NSE_INDEX", "name": "Nifty50", "instrument_key": "NSE_INDEX|Nifty50"},
    ]
    with pytest.raises(HTTPException, match="could not be uniquely resolved"):
        upstox.resolve_from_catalog("NSE:NIFTY50-INDEX", duplicate)

    with pytest.raises(HTTPException, match="could not be uniquely resolved"):
        upstox.resolve_from_catalog("NSE:NIFTYBANK-INDEX", [])


def test_resolve_from_catalog_enforces_exact_nse_eq_symbol_and_type():
    rows = [
        {
            "segment": "NSE_EQ",
            "instrument_type": "EQ",
            "trading_symbol": "RELIANCE",
            "name": "Reliance Industries",
            "instrument_key": "NSE_EQ|INE002A01018",
        }
    ]
    resolved = upstox.resolve_from_catalog("NSE:RELIANCE-EQ", rows)
    assert resolved["trading_symbol"] == "RELIANCE"

    wrong_type = [{**rows[0], "instrument_type": "FUT"}]
    with pytest.raises(HTTPException, match="could not be uniquely resolved"):
        upstox.resolve_from_catalog("NSE:RELIANCE-EQ", wrong_type)


# Upstox quote normalization quality guarantees
def test_normalize_upstox_quote_missing_source_timestamp_stays_unknown_and_bid_ask_nullable():
    quote = upstox.normalize_upstox_quote(
        "NSE:NIFTY50-INDEX",
        {
            "instrument_token": "NSE_INDEX|Nifty 50",
            "last_price": "25000",
            "net_change": "10",
            "last_trade_time": "2026-01-01T10:00:00Z",
            "depth": {},
            "volume": "1000",
            "timestamp": None,
        },
    )
    assert quote["source_timestamp"] is None
    assert quote["freshness"] == "UNKNOWN"
    assert quote["bid"] is None and quote["ask"] is None


# API regression tests against public preview endpoint
def test_upstox_registration_endpoint_shows_pending_origin_without_fabricated_values():
    response = requests.get(f"{API_BASE}/integrations/upstox/registration", timeout=30)
    assert response.status_code == 200
    data = response.json()
    assert data["callback_path"] == "/api/integrations/upstox/oauth/callback"
    assert data["callback_method"] == "GET"
    assert data["callback_url"] is None
    assert data["website_url"] is None
    assert data["postback_url"] is None
    assert data["primary_ip"] is None


def test_oauth_start_requires_auth_and_returns_409_when_origin_unconfigured():
    anonymous = requests.post(f"{API_BASE}/integrations/upstox/oauth/start", timeout=30)
    assert anonymous.status_code == 401

    session, _, _ = _register_and_auth()
    gated = session.post(f"{API_BASE}/integrations/upstox/oauth/start", timeout=30)
    assert gated.status_code == 409
    assert "pending" in gated.json()["detail"].lower() or "hostname" in gated.json()["detail"].lower()


def test_connections_upstox_save_masks_secrets_and_logout_blocks_access():
    session, _, _ = _register_and_auth()

    bad = session.put(f"{API_BASE}/connections/upstox", json={"values": {"access_token": "   "}}, timeout=30)
    assert bad.status_code == 422

    saved = session.put(f"{API_BASE}/connections/upstox", json={"values": {"access_token": "dummy_token_qa"}}, timeout=30)
    assert saved.status_code == 200
    upstox_row = next(item for item in saved.json()["connections"] if item["provider"] == "upstox")
    assert "access_token" in upstox_row["configured_fields"]
    assert "encrypted" not in upstox_row

    logout = session.post(f"{API_BASE}/auth/logout", timeout=30)
    assert logout.status_code == 200
    after = session.get(f"{API_BASE}/connections", timeout=30)
    assert after.status_code == 401


def test_market_provider_default_upstox_and_explicit_switch_to_fyers_without_fallback():
    session, _, _ = _register_and_auth()
    overview = session.get(f"{API_BASE}/overview", timeout=30)
    assert overview.status_code == 200
    assert overview.json()["market_provider"] == "upstox"

    switched = session.put(f"{API_BASE}/market-provider", json={"provider": "fyers"}, timeout=30)
    assert switched.status_code == 200
    body = switched.json()
    assert body["market_provider"] == "fyers"
    assert body["automatic_fallback"] is False

    verify = session.get(f"{API_BASE}/overview", timeout=30)
    assert verify.status_code == 200
    assert verify.json()["market_provider"] == "fyers"


def test_invalid_provider_credentials_fail_safely_without_secret_echo():
    session, _, _ = _register_and_auth()

    upstox_save = session.put(
        f"{API_BASE}/connections/upstox",
        json={"values": {"access_token": "invalid_upstox_token_for_qa"}},
        timeout=30,
    )
    assert upstox_save.status_code == 200
    upstox_test = session.post(f"{API_BASE}/connections/upstox/test", timeout=40)
    assert upstox_test.status_code == 200
    upstox_body = upstox_test.json()
    upstox_row = next(item for item in upstox_body["connections"] if item["provider"] == "upstox")
    assert upstox_body["ok"] is False
    assert upstox_row["status"] == "ERROR"
    assert "invalid_upstox_token_for_qa" not in (upstox_row.get("error") or "")

    fyers_save = session.put(
        f"{API_BASE}/connections/fyers",
        json={"values": {"client_id": "dummy-client", "access_token": "dummy-token", "secret": "dummy-secret"}},
        timeout=30,
    )
    assert fyers_save.status_code == 200
    fyers_test = session.post(f"{API_BASE}/connections/fyers/test", timeout=40)
    assert fyers_test.status_code == 200
    fyers_body = fyers_test.json()
    fyers_row = next(item for item in fyers_body["connections"] if item["provider"] == "fyers")
    assert fyers_body["ok"] is False
    assert fyers_row["status"] == "ERROR"

    gemini_save = session.put(
        f"{API_BASE}/connections/gemini",
        json={"values": {"api_key": "dummy-gemini-key"}},
        timeout=30,
    )
    assert gemini_save.status_code == 200
    gemini_test = session.post(f"{API_BASE}/connections/gemini/test", timeout=40)
    assert gemini_test.status_code == 200
    gemini_body = gemini_test.json()
    gemini_row = next(item for item in gemini_body["connections"] if item["provider"] == "gemini")
    assert gemini_body["ok"] is False
    assert gemini_row["status"] == "ERROR"
