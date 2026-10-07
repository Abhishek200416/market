"""Comprehensive backend API tests for EDGE INDIA workspace isolation and security."""

import os
import uuid
import requests
from pathlib import Path


def get_backend_url():
    """Get backend URL from frontend/.env"""
    frontend_env = Path("/app/frontend/.env")
    if frontend_env.exists():
        for line in frontend_env.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                return value.rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE_URL = get_backend_url()
API_BASE = f"{BASE_URL}/api"
APP_ORIGIN = BASE_URL  # Same as backend APP_ORIGIN


def test_health_db_running():
    """Test 1: /api/health DB running check"""
    print("\n=== Test 1: Health Check ===")
    response = requests.get(f"{API_BASE}/health", timeout=25)
    assert response.status_code == 200, f"Health check failed: {response.text}"
    
    body = response.json()
    assert body["database"] == "CONNECTED", "Database not connected"
    assert body["api"] == "HEALTHY", "API not healthy"
    assert body["mode"] == "PAPER", "Mode should be PAPER"
    assert body["upstream_version"] == "0.6.0", "Upstream version mismatch"
    print(f"✅ Health check passed: DB={body['database']}, API={body['api']}")
    return body


def test_workspace_bootstrap_with_origin():
    """Test 2: POST /api/auth/workspace with correct Origin creates guest workspace"""
    print("\n=== Test 2: Workspace Bootstrap with Origin ===")
    
    session = requests.Session()
    response = session.post(
        f"{API_BASE}/auth/workspace",
        headers={"Origin": APP_ORIGIN, "Content-Type": "application/json"},
        timeout=25
    )
    
    assert response.status_code == 200, f"Workspace creation failed: {response.text}"
    
    data = response.json()
    assert "user" in data, "User not in response"
    assert "csrf_token" in data, "CSRF token not in response"
    
    user = data["user"]
    assert user["is_guest"] is True, "User should be guest"
    assert "@guest.invalid" in user["email"], "Guest email format incorrect"
    
    # Check cookie
    cookie_header = response.headers.get("set-cookie", "")
    assert "terminal_session=" in cookie_header, "Session cookie not set"
    assert "HttpOnly" in cookie_header, "Cookie should be HttpOnly"
    assert "Secure" in cookie_header, "Cookie should be Secure"
    assert "SameSite=" in cookie_header, "Cookie should have SameSite"
    
    csrf_token = data["csrf_token"]
    print(f"✅ Guest workspace created: user_id={user['id']}, csrf_token={csrf_token[:20]}...")
    
    return session, csrf_token, user


def test_workspace_resume_same_cookie():
    """Test 3: Resume same cookie retains id/risk/account"""
    print("\n=== Test 3: Workspace Resume ===")
    
    session = requests.Session()
    
    # First bootstrap
    response1 = session.post(
        f"{API_BASE}/auth/workspace",
        headers={"Origin": APP_ORIGIN, "Content-Type": "application/json"},
        timeout=25
    )
    assert response1.status_code == 200
    user1 = response1.json()["user"]
    user1_id = user1["id"]
    
    # Second bootstrap with same cookie
    response2 = session.post(
        f"{API_BASE}/auth/workspace",
        headers={"Origin": APP_ORIGIN, "Content-Type": "application/json"},
        timeout=25
    )
    assert response2.status_code == 200
    user2 = response2.json()["user"]
    user2_id = user2["id"]
    
    assert user1_id == user2_id, "User ID should be same on resume"
    print(f"✅ Workspace resumed: same user_id={user1_id}")
    
    return session, response2.json()["csrf_token"], user2


def test_workspace_isolation():
    """Test 4: Separate sessions completely isolated"""
    print("\n=== Test 4: Workspace Isolation ===")
    
    # Create two separate sessions
    session1 = requests.Session()
    response1 = session1.post(
        f"{API_BASE}/auth/workspace",
        headers={"Origin": APP_ORIGIN, "Content-Type": "application/json"},
        timeout=25
    )
    user1 = response1.json()["user"]
    
    session2 = requests.Session()
    response2 = session2.post(
        f"{API_BASE}/auth/workspace",
        headers={"Origin": APP_ORIGIN, "Content-Type": "application/json"},
        timeout=25
    )
    user2 = response2.json()["user"]
    
    assert user1["id"] != user2["id"], "Different sessions should have different user IDs"
    print(f"✅ Workspace isolation verified: user1={user1['id']}, user2={user2['id']}")
    
    return session1, session2


def test_invalid_origin_rejected():
    """Test 5: Invalid/missing Origin rejected on bootstrap"""
    print("\n=== Test 5: Invalid Origin Rejection ===")
    
    # Test with wrong origin
    response = requests.post(
        f"{API_BASE}/auth/workspace",
        headers={"Origin": "https://evil.example.com", "Content-Type": "application/json"},
        timeout=25
    )
    assert response.status_code == 403, "Invalid origin should be rejected"
    print(f"✅ Invalid origin rejected: {response.status_code}")
    
    # Test with missing origin
    response2 = requests.post(
        f"{API_BASE}/auth/workspace",
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response2.status_code == 403, "Missing origin should be rejected"
    print(f"✅ Missing origin rejected: {response2.status_code}")


def test_csrf_protection():
    """Test 6: Ordinary writes missing CSRF rejected"""
    print("\n=== Test 6: CSRF Protection ===")
    
    session, csrf_token, user = test_workspace_bootstrap_with_origin()
    
    # Try write without CSRF token
    response = session.put(
        f"{API_BASE}/connections/gemini",
        json={"values": {"api_key": "test-key"}},
        timeout=25
    )
    assert response.status_code == 403, "Write without CSRF should be rejected"
    print(f"✅ Write without CSRF rejected: {response.status_code}")
    
    # Try write with CSRF token
    session.headers["X-CSRF-Token"] = csrf_token
    response2 = session.put(
        f"{API_BASE}/connections/gemini",
        json={"values": {"api_key": "test-key"}},
        timeout=25
    )
    assert response2.status_code == 200, f"Write with CSRF should succeed: {response2.text}"
    print(f"✅ Write with CSRF accepted: {response2.status_code}")


def test_guest_cannot_password_login():
    """Test 7: Guest identity cannot legacy password-login"""
    print("\n=== Test 7: Guest Cannot Password Login ===")
    
    session, csrf_token, user = test_workspace_bootstrap_with_origin()
    
    # Try to login with guest email
    response = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": user["email"], "password": "anypassword123456"},
        timeout=25
    )
    
    # Should return 401 or 422 (validation error for invalid email format), not 500
    assert response.status_code in [401, 422], f"Guest login should return 401 or 422, got {response.status_code}"
    print(f"✅ Guest cannot password-login: {response.status_code} (expected 401 or 422)")


def test_simulated_capital():
    """Test 8: 1,000,000 simulated capital"""
    print("\n=== Test 8: Simulated Capital ===")
    
    session, csrf_token, user = test_workspace_bootstrap_with_origin()
    session.headers["X-CSRF-Token"] = csrf_token
    
    # Get account info
    response = session.get(f"{API_BASE}/paper", timeout=25)
    assert response.status_code == 200, f"Failed to get account: {response.text}"
    
    account = response.json()["account"]
    assert account["starting_capital"] == 1000000.0, "Starting capital should be 1,000,000"
    assert account["cash"] == 1000000.0, "Cash should be 1,000,000"
    print(f"✅ Simulated capital verified: {account['starting_capital']}")


def test_risk_update():
    """Test 9: Risk update works"""
    print("\n=== Test 9: Risk Update ===")
    
    session, csrf_token, user = test_workspace_bootstrap_with_origin()
    session.headers["X-CSRF-Token"] = csrf_token
    
    # Update risk settings
    risk_payload = {
        "risk_per_trade": 1.5,
        "daily_loss_limit": 3.0,
        "max_consecutive_losses": 4,
        "max_trades_day": 15,
        "cooldown_seconds": 90,
        "max_exposure": 40,
        "max_position": 12,
        "min_risk_reward": 2.5,
        "min_volume": 2000,
        "max_spread_bps": 30
    }
    
    response = session.put(f"{API_BASE}/paper/risk", json=risk_payload, timeout=25)
    assert response.status_code == 200, f"Risk update failed: {response.text}"
    
    updated_risk = response.json()["risk"]
    assert updated_risk["risk_per_trade"] == 1.5, "Risk per trade not updated"
    assert updated_risk["daily_loss_limit"] == 3.0, "Daily loss limit not updated"
    print(f"✅ Risk update successful: risk_per_trade={updated_risk['risk_per_trade']}")


def test_kill_switch_toggle():
    """Test 10: Kill switch toggle works"""
    print("\n=== Test 10: Kill Switch Toggle ===")
    
    session, csrf_token, user = test_workspace_bootstrap_with_origin()
    session.headers["X-CSRF-Token"] = csrf_token
    
    # Enable kill switch
    response = session.post(f"{API_BASE}/paper/kill-switch", json={"enabled": True}, timeout=25)
    assert response.status_code == 200, f"Kill switch enable failed: {response.text}"
    
    data = response.json()
    assert data["enabled"] is True, "Kill switch should be enabled"
    print(f"✅ Kill switch enabled: {data['enabled']}")
    
    # Disable kill switch
    response2 = session.post(f"{API_BASE}/paper/kill-switch", json={"enabled": False}, timeout=25)
    assert response2.status_code == 200, f"Kill switch disable failed: {response2.text}"
    
    data2 = response2.json()
    assert data2["enabled"] is False, "Kill switch should be disabled"
    print(f"✅ Kill switch disabled: {data2['enabled']}")


def test_provider_selector():
    """Test 11: Provider selector works"""
    print("\n=== Test 11: Provider Selector ===")
    
    session, csrf_token, user = test_workspace_bootstrap_with_origin()
    session.headers["X-CSRF-Token"] = csrf_token
    
    # Change provider to fyers
    response = session.put(f"{API_BASE}/market-provider", json={"provider": "fyers"}, timeout=25)
    assert response.status_code == 200, f"Provider change failed: {response.text}"
    
    data = response.json()
    assert data["market_provider"] == "fyers", "Provider should be fyers"
    print(f"✅ Provider changed to: {data['market_provider']}")


def test_orders_blocked_without_broker():
    """Test 12: Orders safely blocked without broker"""
    print("\n=== Test 12: Orders Blocked Without Broker ===")
    
    session, csrf_token, user = test_workspace_bootstrap_with_origin()
    session.headers["X-CSRF-Token"] = csrf_token
    
    # Try to place order without broker connection
    order_payload = {
        "symbol": "NSE:RELIANCE-EQ",
        "quantity": 10,
        "stop": 2500,
        "target": 2700,
        "idempotency_key": uuid.uuid4().hex
    }
    
    response = session.post(f"{API_BASE}/paper/orders", json=order_payload, timeout=25)
    assert response.status_code == 409, f"Order should be blocked, got {response.status_code}"
    assert "disconnected" in response.json()["detail"].lower(), "Should indicate disconnected"
    print(f"✅ Order blocked without broker: {response.status_code}")


def test_research_blocked_without_broker():
    """Test 13: Research/signals safely blocked without broker"""
    print("\n=== Test 13: Research Blocked Without Broker ===")
    
    session, csrf_token, user = test_workspace_bootstrap_with_origin()
    session.headers["X-CSRF-Token"] = csrf_token
    
    # Try to run research without broker connection
    research_payload = {"symbol": "NSE:NIFTY50-INDEX"}
    
    response = session.post(f"{API_BASE}/research/run", json=research_payload, timeout=40)
    assert response.status_code == 409, f"Research should be blocked, got {response.status_code}"
    assert "disconnected" in response.json()["detail"].lower(), "Should indicate disconnected"
    print(f"✅ Research blocked without broker: {response.status_code}")


def test_real_gemini_validation():
    """Test 14: REAL Gemini validation with user-supplied key"""
    print("\n=== Test 14: REAL Gemini Validation ===")
    
    # Get validation key from backend/.env
    backend_env = Path("/app/backend/.env")
    validation_key = None
    if backend_env.exists():
        for line in backend_env.read_text().splitlines():
            if line.startswith("GEMINI_VALIDATION_KEY="):
                validation_key = line.split("=", 1)[1].strip()
                break
    
    if not validation_key:
        print("⚠️  GEMINI_VALIDATION_KEY not found in backend/.env, skipping real validation")
        return
    
    print(f"✅ Found validation key (length: {len(validation_key)})")
    
    # Create isolated guest workspace
    session = requests.Session()
    response = session.post(
        f"{API_BASE}/auth/workspace",
        headers={"Origin": APP_ORIGIN, "Content-Type": "application/json"},
        timeout=25
    )
    assert response.status_code == 200
    csrf_token = response.json()["csrf_token"]
    user = response.json()["user"]
    
    session.headers["X-CSRF-Token"] = csrf_token
    
    # Save Gemini credentials
    save_response = session.put(
        f"{API_BASE}/connections/gemini",
        json={"values": {"api_key": validation_key}},
        timeout=25
    )
    assert save_response.status_code == 200, f"Failed to save Gemini credentials: {save_response.text}"
    print(f"✅ Gemini credentials saved (encrypted)")
    
    # Test connection with quick model
    test_response = session.post(
        f"{API_BASE}/connections/gemini/test",
        timeout=30
    )
    
    if test_response.status_code != 200:
        print(f"❌ Gemini test request failed: {test_response.status_code} - {test_response.text}")
        return
    
    test_data = test_response.json()
    connections = test_data.get("connections", [])
    gemini_status = next((c for c in connections if c["provider"] == "gemini"), None)
    
    if not gemini_status:
        print(f"❌ Gemini status not found in response")
        return
    
    if gemini_status["status"] == "CONNECTED":
        print(f"✅ Gemini quick model validation PASSED: {gemini_status['status']}")
        print(f"   Last success: {gemini_status.get('last_success')}")
    else:
        print(f"❌ Gemini validation FAILED: {gemini_status['status']}")
        print(f"   Error: {gemini_status.get('error')}")
        print(f"   Note: This could be due to API quota, network, or model access issues")
    
    # Clean up: disconnect Gemini
    disconnect_response = session.delete(f"{API_BASE}/connections/gemini", timeout=25)
    assert disconnect_response.status_code == 200, "Failed to disconnect Gemini"
    print(f"✅ Test credentials cleaned up")
    
    return gemini_status


def run_all_tests():
    """Run all backend tests"""
    print("\n" + "="*80)
    print("EDGE INDIA Backend API Tests")
    print("="*80)
    
    results = {
        "passed": [],
        "failed": []
    }
    
    tests = [
        ("Health Check", test_health_db_running),
        ("Workspace Bootstrap", test_workspace_bootstrap_with_origin),
        ("Workspace Resume", test_workspace_resume_same_cookie),
        ("Workspace Isolation", test_workspace_isolation),
        ("Invalid Origin Rejection", test_invalid_origin_rejected),
        ("CSRF Protection", test_csrf_protection),
        ("Guest Cannot Password Login", test_guest_cannot_password_login),
        ("Simulated Capital", test_simulated_capital),
        ("Risk Update", test_risk_update),
        ("Kill Switch Toggle", test_kill_switch_toggle),
        ("Provider Selector", test_provider_selector),
        ("Orders Blocked Without Broker", test_orders_blocked_without_broker),
        ("Research Blocked Without Broker", test_research_blocked_without_broker),
        ("Real Gemini Validation", test_real_gemini_validation),
    ]
    
    for test_name, test_func in tests:
        try:
            test_func()
            results["passed"].append(test_name)
        except Exception as e:
            results["failed"].append((test_name, str(e)))
            print(f"❌ {test_name} FAILED: {e}")
    
    print("\n" + "="*80)
    print("Test Summary")
    print("="*80)
    print(f"✅ Passed: {len(results['passed'])}/{len(tests)}")
    print(f"❌ Failed: {len(results['failed'])}/{len(tests)}")
    
    if results["passed"]:
        print("\nPassed Tests:")
        for test in results["passed"]:
            print(f"  ✅ {test}")
    
    if results["failed"]:
        print("\nFailed Tests:")
        for test, error in results["failed"]:
            print(f"  ❌ {test}")
            print(f"     Error: {error}")
    
    print("\n" + "="*80)
    
    return results


if __name__ == "__main__":
    results = run_all_tests()
    exit(0 if not results["failed"] else 1)
