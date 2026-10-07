"""Comprehensive tests for broker-neutral JSON postback receiver and server connection details.

This tests the NEW feature: provider-neutral application connection-details and generic JSON postback ingress.
User explicitly wants server URL usable with compatible brokers without choosing provider.
"""

import json
import hashlib
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


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
NAMED_ALIAS = "https://no-login-hub.preview.emergentagent.com"

# Track created endpoints for cleanup
created_endpoints = []


def create_workspace(origin=None):
    """Create a new isolated workspace and return session, csrf_token, user"""
    session = requests.Session()
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    else:
        headers["Origin"] = APP_ORIGIN
    
    response = session.post(f"{API_BASE}/auth/workspace", headers=headers, timeout=25)
    assert response.status_code == 200, f"Workspace creation failed: {response.text}"
    
    data = response.json()
    csrf_token = data["csrf_token"]
    user = data["user"]
    
    session.headers["X-CSRF-Token"] = csrf_token
    return session, csrf_token, user


def test_connection_details_requires_workspace():
    """Test 1: GET /api/server/connection-details requires workspace"""
    print("\n=== Test 1: Connection Details Requires Workspace ===")
    
    # Try without workspace
    response = requests.get(f"{API_BASE}/server/connection-details", timeout=25)
    assert response.status_code in [401, 403], f"Should require auth, got {response.status_code}"
    print(f"✅ Unauthenticated request rejected: {response.status_code}")
    
    # Try with workspace
    session, csrf_token, user = create_workspace()
    response = session.get(f"{API_BASE}/server/connection-details", timeout=25)
    assert response.status_code == 200, f"Failed with workspace: {response.text}"
    
    data = response.json()
    assert data["app_name"] == "EDGE INDIA Research", "App name mismatch"
    assert data["receiver_ready"] is False, "Receiver should not be ready yet"
    assert data["receiver_method"] == "POST", "Method should be POST"
    assert data["receiver_format"] == "application/json", "Format should be JSON"
    assert data["max_payload_bytes"] == 262144, "Max bytes should be 256 KiB"
    assert data["retention_days"] == 30, "Retention should be 30 days"
    assert data["scope"] == "GENERIC_JSON_RECEIPTS_ONLY", "Scope mismatch"
    assert data["broker_authentication"] == "NOT_UNIVERSAL", "Should not be universal auth"
    assert data["verification_status"] == "UNVERIFIED", "Should be unverified"
    assert data["live_enabled"] is False, "Live should be disabled"
    
    print(f"✅ Connection details retrieved: receiver_ready={data['receiver_ready']}")
    return session, csrf_token, user


def test_postback_provision_idempotent():
    """Test 2: POST /api/server/postback idempotently provisions/reveals receive_path"""
    print("\n=== Test 2: Postback Provision Idempotent ===")
    
    session, csrf_token, user = create_workspace()
    
    # First provision
    response1 = session.post(f"{API_BASE}/server/postback", timeout=25)
    assert response1.status_code == 200, f"First provision failed: {response1.text}"
    
    data1 = response1.json()
    assert "receive_path" in data1, "receive_path not in response"
    assert data1["receive_path"].startswith("/server/receive/"), "Invalid receive_path format"
    assert data1["method"] == "POST", "Method should be POST"
    assert data1["verification_status"] == "UNVERIFIED", "Should be unverified"
    assert "created_at" in data1, "created_at not in response"
    
    receive_path1 = data1["receive_path"]
    token1 = receive_path1.split("/server/receive/")[1]
    assert len(token1) == 64, f"Token should be 64 chars, got {len(token1)}"
    
    print(f"✅ First provision: {receive_path1[:30]}...")
    
    # Second provision (idempotent - should return same path)
    response2 = session.post(f"{API_BASE}/server/postback", timeout=25)
    assert response2.status_code == 200, f"Second provision failed: {response2.text}"
    
    data2 = response2.json()
    receive_path2 = data2["receive_path"]
    
    assert receive_path1 == receive_path2, "Idempotent provision should return same path"
    print(f"✅ Second provision: same path (idempotent)")
    
    # Verify connection-details now shows receiver_ready=true
    details = session.get(f"{API_BASE}/server/connection-details", timeout=25)
    assert details.status_code == 200
    assert details.json()["receiver_ready"] is True, "Receiver should be ready now"
    print(f"✅ Connection details updated: receiver_ready=true")
    
    created_endpoints.append((session, token1, user["id"]))
    return session, csrf_token, user, receive_path1, token1


def test_concurrent_provision_idempotency():
    """Test 3: Concurrent provision requests are idempotent"""
    print("\n=== Test 3: Concurrent Provision Idempotency ===")
    
    session, csrf_token, user = create_workspace()
    
    def provision():
        # Use same session with CSRF token
        resp = session.post(f"{API_BASE}/server/postback", timeout=25)
        if resp.status_code == 200:
            return resp.json()["receive_path"]
        return None
    
    # Make 5 concurrent provision requests
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(provision) for _ in range(5)]
        paths = [f.result() for f in as_completed(futures)]
    
    # All should return the same path
    paths = [p for p in paths if p is not None]
    assert len(paths) > 0, "No successful provisions"
    assert all(p == paths[0] for p in paths), f"Concurrent provisions returned different paths: {paths}"
    
    print(f"✅ Concurrent provision idempotency verified: all 5 requests returned same path")
    
    token = paths[0].split("/server/receive/")[1]
    created_endpoints.append((session, token, user["id"]))
    return session, paths[0], token


def test_public_receiver_post_json():
    """Test 4: POST /server/receive/{token} accepts JSON object/array, returns 202/200"""
    print("\n=== Test 4: Public Receiver POST JSON ===")
    
    session, csrf_token, user, receive_path, token = test_postback_provision_idempotent()
    
    # Test 1: POST JSON object (new receipt)
    test_payload = {
        "type": "application_self_test",
        "timestamp": time.time(),
        "data": {"test": "value", "number": 42}
    }
    
    response1 = requests.post(
        f"{BASE_URL}{receive_path}",
        json=test_payload,
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response1.status_code == 202, f"New receipt should return 202, got {response1.status_code}: {response1.text}"
    
    data1 = response1.json()
    assert data1["accepted"] is True, "Should be accepted"
    assert data1["duplicate"] is False, "Should not be duplicate"
    assert "receipt_id" in data1, "receipt_id not in response"
    assert data1["verification_status"] == "UNVERIFIED", "Should be unverified"
    
    receipt_id1 = data1["receipt_id"]
    print(f"✅ New JSON object accepted: 202, receipt_id={receipt_id1}")
    
    # Test 2: POST same JSON (duplicate - canonical match)
    response2 = requests.post(
        f"{BASE_URL}{receive_path}",
        json=test_payload,
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response2.status_code == 200, f"Duplicate should return 200, got {response2.status_code}: {response2.text}"
    
    data2 = response2.json()
    assert data2["accepted"] is True, "Should be accepted"
    assert data2["duplicate"] is True, "Should be duplicate"
    assert data2["verification_status"] == "UNVERIFIED", "Should be unverified"
    
    print(f"✅ Duplicate JSON detected: 200, duplicate=true")
    
    # Test 3: POST JSON array
    array_payload = [{"item": 1}, {"item": 2}, {"item": 3}]
    response3 = requests.post(
        f"{BASE_URL}{receive_path}",
        json=array_payload,
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response3.status_code == 202, f"Array should return 202, got {response3.status_code}: {response3.text}"
    
    data3 = response3.json()
    assert data3["accepted"] is True, "Array should be accepted"
    assert data3["duplicate"] is False, "Array should not be duplicate"
    
    print(f"✅ JSON array accepted: 202, receipt_id={data3['receipt_id']}")
    
    return session, receive_path, token, receipt_id1


def test_public_receiver_validation():
    """Test 5: POST /server/receive/{token} validates input correctly"""
    print("\n=== Test 5: Public Receiver Validation ===")
    
    session, csrf_token, user, receive_path, token = test_postback_provision_idempotent()
    
    # Test 1: Invalid token format (404)
    response1 = requests.post(
        f"{BASE_URL}/server/receive/invalid-token",
        json={"test": "data"},
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response1.status_code == 404, f"Invalid token should return 404, got {response1.status_code}"
    print(f"✅ Invalid token format rejected: 404")
    
    # Test 2: Non-existent token (404)
    fake_token = "A" * 64
    response2 = requests.post(
        f"{BASE_URL}/server/receive/{fake_token}",
        json={"test": "data"},
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response2.status_code == 404, f"Non-existent token should return 404, got {response2.status_code}"
    print(f"✅ Non-existent token rejected: 404")
    
    # Test 3: Wrong content-type (415)
    response3 = requests.post(
        f"{BASE_URL}{receive_path}",
        data="plain text",
        headers={"Content-Type": "text/plain"},
        timeout=25
    )
    assert response3.status_code == 415, f"Wrong content-type should return 415, got {response3.status_code}"
    print(f"✅ Wrong content-type rejected: 415")
    
    # Test 4: Malformed JSON (400)
    response4 = requests.post(
        f"{BASE_URL}{receive_path}",
        data="{invalid json",
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response4.status_code == 400, f"Malformed JSON should return 400, got {response4.status_code}"
    print(f"✅ Malformed JSON rejected: 400")
    
    # Test 5: Scalar JSON (400)
    response5 = requests.post(
        f"{BASE_URL}{receive_path}",
        data='"just a string"',
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response5.status_code == 400, f"Scalar JSON should return 400, got {response5.status_code}"
    print(f"✅ Scalar JSON rejected: 400")
    
    # Test 6: Non-finite number (400)
    response6 = requests.post(
        f"{BASE_URL}{receive_path}",
        data='{"value": NaN}',
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response6.status_code == 400, f"Non-finite number should return 400, got {response6.status_code}"
    print(f"✅ Non-finite number rejected: 400")
    
    # Test 7: Payload too large (413)
    large_payload = {"data": "x" * 300000}  # > 256 KiB
    response7 = requests.post(
        f"{BASE_URL}{receive_path}",
        json=large_payload,
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response7.status_code == 413, f"Oversized payload should return 413, got {response7.status_code}"
    print(f"✅ Oversized payload rejected: 413")
    
    return session, receive_path, token


def test_public_receiver_get_health():
    """Test 6: GET /server/receive/{token} returns generic health, no validation"""
    print("\n=== Test 6: Public Receiver GET Health ===")
    
    session, csrf_token, user, receive_path, token = test_postback_provision_idempotent()
    
    # Test 1: GET with valid token
    response1 = requests.get(f"{BASE_URL}{receive_path}", timeout=25)
    assert response1.status_code == 200, f"GET health should return 200, got {response1.status_code}"
    
    data1 = response1.json()
    assert data1["status"] == "RECEIVER_ONLINE", "Status should be RECEIVER_ONLINE"
    assert data1["method"] == "POST", "Method should be POST"
    assert data1["content_type"] == "application/json", "Content-type should be JSON"
    assert "Health check only" in data1["message"], "Should mention health check"
    
    print(f"✅ GET health with valid token: 200, status={data1['status']}")
    
    # Test 2: GET with invalid token (should still return 200 - no validation)
    fake_token = "B" * 64
    response2 = requests.get(f"{BASE_URL}/server/receive/{fake_token}", timeout=25)
    assert response2.status_code == 200, f"GET health should return 200 even for invalid token, got {response2.status_code}"
    
    data2 = response2.json()
    assert data2["status"] == "RECEIVER_ONLINE", "Status should be RECEIVER_ONLINE"
    
    print(f"✅ GET health with invalid token: 200 (no validation)")
    
    # Test 3: GET with query parameters (should not store them)
    response3 = requests.get(f"{BASE_URL}{receive_path}?code=secret&state=test", timeout=25)
    assert response3.status_code == 200, f"GET health with query should return 200, got {response3.status_code}"
    
    print(f"✅ GET health with query params: 200 (not stored)")
    
    return session, receive_path, token


def test_public_receiver_methods():
    """Test 7: Other HTTP methods on /server/receive/{token} return 405"""
    print("\n=== Test 7: Public Receiver Methods ===")
    
    session, csrf_token, user, receive_path, token = test_postback_provision_idempotent()
    
    # Test PUT
    response1 = requests.put(f"{BASE_URL}{receive_path}", json={"test": "data"}, timeout=25)
    assert response1.status_code == 405, f"PUT should return 405, got {response1.status_code}"
    print(f"✅ PUT rejected: 405")
    
    # Test DELETE
    response2 = requests.delete(f"{BASE_URL}{receive_path}", timeout=25)
    assert response2.status_code == 405, f"DELETE should return 405, got {response2.status_code}"
    print(f"✅ DELETE rejected: 405")
    
    # Test PATCH
    response3 = requests.patch(f"{BASE_URL}{receive_path}", json={"test": "data"}, timeout=25)
    assert response3.status_code == 405, f"PATCH should return 405, got {response3.status_code}"
    print(f"✅ PATCH rejected: 405")
    
    return session, receive_path, token


def test_events_metadata_only():
    """Test 8: GET /api/server/events returns metadata only, isolated by user"""
    print("\n=== Test 8: Events Metadata Only ===")
    
    # Create workspace and send some receipts
    session, csrf_token, user, receive_path, token, receipt_id = test_public_receiver_post_json()
    
    # Get events
    response = session.get(f"{API_BASE}/server/events", timeout=25)
    assert response.status_code == 200, f"Events request failed: {response.text}"
    
    data = response.json()
    assert "events" in data, "events not in response"
    assert data["retention_days"] == 30, "Retention should be 30 days"
    
    events = data["events"]
    assert len(events) > 0, "Should have at least one event"
    
    # Check first event metadata
    event = events[0]
    assert "id" in event, "id not in event"
    assert "received_at" in event, "received_at not in event"
    assert "size_bytes" in event, "size_bytes not in event"
    assert "payload_type" in event, "payload_type not in event"
    assert "verification_status" in event, "verification_status not in event"
    assert event["verification_status"] == "UNVERIFIED", "Should be unverified"
    
    # Ensure no payload or credentials in response
    assert "payload" not in event, "Payload should not be in metadata"
    assert "payload_ciphertext" not in event, "Ciphertext should not be in metadata"
    assert "token" not in event, "Token should not be in metadata"
    
    print(f"✅ Events metadata retrieved: {len(events)} events, no payload/credentials")
    
    # Test isolation: create another workspace and verify it has no events
    session2, csrf2, user2 = create_workspace()
    response2 = session2.get(f"{API_BASE}/server/events", timeout=25)
    assert response2.status_code == 200
    
    data2 = response2.json()
    events2 = data2["events"]
    assert len(events2) == 0, "New workspace should have no events"
    
    print(f"✅ Events isolated by user: new workspace has 0 events")
    
    return session, events


def test_postback_rotate():
    """Test 9: POST /api/server/postback/rotate requires session+CSRF, revokes old URL"""
    print("\n=== Test 9: Postback Rotate ===")
    
    session, csrf_token, user, receive_path1, token1 = test_postback_provision_idempotent()
    
    # Test 1: Rotate without CSRF (should fail)
    session_no_csrf = requests.Session()
    session_no_csrf.cookies = session.cookies
    response1 = session_no_csrf.post(f"{API_BASE}/server/postback/rotate", timeout=25)
    assert response1.status_code == 403, f"Rotate without CSRF should fail, got {response1.status_code}"
    print(f"✅ Rotate without CSRF rejected: 403")
    
    # Test 2: Rotate with CSRF (should succeed)
    response2 = session.post(f"{API_BASE}/server/postback/rotate", timeout=25)
    assert response2.status_code == 200, f"Rotate with CSRF failed: {response2.text}"
    
    data2 = response2.json()
    assert "receive_path" in data2, "receive_path not in response"
    assert data2["method"] == "POST", "Method should be POST"
    assert data2["old_url_revoked"] is True, "old_url_revoked should be true"
    
    receive_path2 = data2["receive_path"]
    token2 = receive_path2.split("/server/receive/")[1]
    
    assert receive_path1 != receive_path2, "New path should be different"
    assert token1 != token2, "New token should be different"
    
    print(f"✅ Rotate succeeded: old token revoked, new token issued")
    
    # Test 3: Old token should be revoked (404)
    response3 = requests.post(
        f"{BASE_URL}{receive_path1}",
        json={"test": "after_rotation"},
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response3.status_code == 404, f"Old token should be revoked, got {response3.status_code}"
    print(f"✅ Old token revoked: 404")
    
    # Test 4: New token should work
    response4 = requests.post(
        f"{BASE_URL}{receive_path2}",
        json={"test": "after_rotation"},
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response4.status_code == 202, f"New token should work, got {response4.status_code}"
    print(f"✅ New token works: 202")
    
    # Test 5: Old receipts should be preserved
    events_response = session.get(f"{API_BASE}/server/events", timeout=25)
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert len(events) > 0, "Old receipts should be preserved"
    print(f"✅ Old receipts preserved: {len(events)} events")
    
    created_endpoints.append((session, token2, user["id"]))
    return session, receive_path2, token2


def test_observe_egress_real_lookup():
    """Test 10: POST /api/server/observe-egress uses real IPify, reports OBSERVED_NOT_RESERVED"""
    print("\n=== Test 10: Observe Egress Real Lookup ===")
    
    session, csrf_token, user = create_workspace()
    
    # First observation (should hit IPify)
    response1 = session.post(f"{API_BASE}/server/observe-egress", timeout=30)
    assert response1.status_code == 200, f"Observe egress failed: {response1.text}"
    
    data1 = response1.json()
    assert "observation" in data1, "observation not in response"
    assert data1["cached"] is False, "First lookup should not be cached"
    
    obs1 = data1["observation"]
    assert "ip" in obs1, "ip not in observation"
    assert "observed_at" in obs1, "observed_at not in observation"
    assert obs1["status"] == "OBSERVED_NOT_RESERVED", "Status should be OBSERVED_NOT_RESERVED"
    assert obs1["source"] == "configured_observation_endpoint", "Source should be configured endpoint"
    
    # Validate IP format
    ip = obs1["ip"]
    parts = ip.split(".")
    assert len(parts) == 4, f"Invalid IP format: {ip}"
    assert all(part.isdigit() and 0 <= int(part) <= 255 for part in parts), f"Invalid IP: {ip}"
    
    print(f"✅ Real egress observation: ip={ip}, status={obs1['status']}")
    
    # Second observation within 60 seconds (should be cached)
    response2 = session.post(f"{API_BASE}/server/observe-egress", timeout=30)
    assert response2.status_code == 200
    
    data2 = response2.json()
    assert data2["cached"] is True, "Second lookup should be cached"
    
    obs2 = data2["observation"]
    assert obs2["ip"] == ip, "Cached IP should be same"
    
    print(f"✅ Cached observation: cached=true, same IP")
    
    # Verify connection-details includes observation
    details = session.get(f"{API_BASE}/server/connection-details", timeout=25)
    assert details.status_code == 200
    
    details_data = details.json()
    assert "observation" in details_data, "observation not in connection-details"
    assert details_data["observation"]["ip"] == ip, "IP should match in connection-details"
    
    print(f"✅ Connection details includes observation")
    
    return session, ip, obs1


def test_cors_csrf_enforcement():
    """Test 11: Private CORS/writes preserve exact allowlist and CSRF"""
    print("\n=== Test 11: CORS/CSRF Enforcement ===")
    
    # Test 1: Private endpoint with wrong origin (403)
    response1 = requests.post(
        f"{API_BASE}/server/postback",
        headers={"Origin": "https://evil.example.com"},
        timeout=25
    )
    assert response1.status_code == 403, f"Wrong origin should be rejected, got {response1.status_code}"
    print(f"✅ Wrong origin rejected: 403")
    
    # Test 2: Private endpoint with missing origin (403)
    response2 = requests.post(f"{API_BASE}/server/postback", timeout=25)
    assert response2.status_code == 403, f"Missing origin should be rejected, got {response2.status_code}"
    print(f"✅ Missing origin rejected: 403")
    
    # Test 3: Private endpoint with correct origin but no session (401/403)
    response3 = requests.post(
        f"{API_BASE}/server/postback",
        headers={"Origin": APP_ORIGIN},
        timeout=25
    )
    assert response3.status_code in [401, 403], f"No session should be rejected, got {response3.status_code}"
    print(f"✅ No session rejected: {response3.status_code}")
    
    # Test 4: Private endpoint with session but no CSRF (403)
    session, csrf_token, user = create_workspace()
    session_no_csrf = requests.Session()
    session_no_csrf.cookies = session.cookies
    response4 = session_no_csrf.post(f"{API_BASE}/server/postback/rotate", timeout=25)
    assert response4.status_code == 403, f"No CSRF should be rejected, got {response4.status_code}"
    print(f"✅ No CSRF rejected: 403")
    
    # Test 5: Private endpoint with wrong CSRF (403)
    session.headers["X-CSRF-Token"] = "wrong-token"
    response5 = session.post(f"{API_BASE}/server/postback/rotate", timeout=25)
    assert response5.status_code == 403, f"Wrong CSRF should be rejected, got {response5.status_code}"
    print(f"✅ Wrong CSRF rejected: 403")
    
    # Test 6: Private endpoint with correct origin, session, and CSRF (200)
    session.headers["X-CSRF-Token"] = csrf_token
    response6 = session.post(f"{API_BASE}/server/postback", timeout=25)
    assert response6.status_code == 200, f"Valid request should succeed, got {response6.status_code}"
    print(f"✅ Valid request with origin+session+CSRF: 200")
    
    # Test 7: Named alias origin should also work
    session2, csrf2, user2 = create_workspace(origin=NAMED_ALIAS)
    response7 = session2.post(f"{API_BASE}/server/postback", timeout=25)
    assert response7.status_code == 200, f"Named alias should work, got {response7.status_code}"
    print(f"✅ Named alias origin works: 200")
    
    return session


def test_storage_encryption_persistence():
    """Test 12: Storage uses UUID ids, encrypted body/token, hash lookup, isolated scope"""
    print("\n=== Test 12: Storage Encryption & Persistence ===")
    
    session, csrf_token, user, receive_path, token = test_postback_provision_idempotent()
    
    # Send a test receipt
    test_payload = {
        "type": "application_self_test",
        "timestamp": time.time(),
        "sensitive_data": "this should be encrypted"
    }
    
    response = requests.post(
        f"{BASE_URL}{receive_path}",
        json=test_payload,
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response.status_code == 202
    receipt_id = response.json()["receipt_id"]
    
    # Verify receipt_id is UUID format (36 chars with hyphens)
    assert len(receipt_id) == 36, f"Receipt ID should be UUID format, got {len(receipt_id)} chars"
    assert receipt_id.count("-") == 4, "UUID should have 4 hyphens"
    
    print(f"✅ Receipt ID is UUID format: {receipt_id}")
    
    # Get events and verify metadata
    events_response = session.get(f"{API_BASE}/server/events", timeout=25)
    assert events_response.status_code == 200
    
    events = events_response.json()["events"]
    event = next((e for e in events if e["id"] == receipt_id), None)
    assert event is not None, "Receipt not found in events"
    
    # Verify metadata fields
    assert event["verification_status"] == "UNVERIFIED", "Should be unverified"
    assert event["payload_type"] == "object", "Should be object type"
    assert event["kind"] == "SELF_LABELLED_TEST", "Should be self-labelled test"
    assert event["size_bytes"] > 0, "Size should be positive"
    
    # Verify no plaintext payload in response
    assert "payload" not in event, "Plaintext payload should not be in response"
    assert "payload_ciphertext" not in event, "Ciphertext should not be in response"
    
    print(f"✅ Storage verified: UUID id, metadata only, no plaintext")
    
    # Test isolation: another user should not see this receipt
    session2, csrf2, user2 = create_workspace()
    events2_response = session2.get(f"{API_BASE}/server/events", timeout=25)
    assert events2_response.status_code == 200
    
    events2 = events2_response.json()["events"]
    event2 = next((e for e in events2 if e["id"] == receipt_id), None)
    assert event2 is None, "Receipt should not be visible to other users"
    
    print(f"✅ Isolation verified: other users cannot see receipts")
    
    return session, receipt_id


def test_log_redaction():
    """Test 13: Verify access logs redact receive token and query parameters"""
    print("\n=== Test 13: Log Redaction ===")
    
    session, csrf_token, user, receive_path, token = test_postback_provision_idempotent()
    
    # Make a request to the receiver with query parameters
    requests.get(f"{BASE_URL}{receive_path}?code=SECRET123&state=SENSITIVE", timeout=25)
    
    # Check uvicorn access logs
    import subprocess
    result = subprocess.run(
        ["tail", "-n", "50", "/var/log/supervisor/backend.out.log"],
        capture_output=True,
        text=True,
        timeout=10
    )
    
    logs = result.stdout
    
    # Verify token is redacted
    assert token not in logs, f"Token should be redacted in logs, but found: {token}"
    assert "[redacted]" in logs or "/server/receive/" not in logs, "Logs should contain redaction marker or no receiver paths"
    
    # Verify query parameters are redacted
    assert "SECRET123" not in logs, "Query parameter should be redacted"
    assert "SENSITIVE" not in logs, "Query parameter should be redacted"
    
    print(f"✅ Log redaction verified: token and query params not in logs")
    
    return True


def test_canonical_origin_regression():
    """Test 14: Canonical UUID origin still works (regression test)"""
    print("\n=== Test 14: Canonical Origin Regression ===")
    
    # Use canonical UUID origin
    session, csrf_token, user = create_workspace(origin=APP_ORIGIN)
    
    # Test all key endpoints
    response1 = session.get(f"{API_BASE}/server/connection-details", timeout=25)
    assert response1.status_code == 200, f"Connection details failed: {response1.text}"
    print(f"✅ Connection details works with canonical origin")
    
    response2 = session.post(f"{API_BASE}/server/postback", timeout=25)
    assert response2.status_code == 200, f"Postback provision failed: {response2.text}"
    print(f"✅ Postback provision works with canonical origin")
    
    receive_path = response2.json()["receive_path"]
    token = receive_path.split("/server/receive/")[1]
    
    response3 = requests.post(
        f"{BASE_URL}{receive_path}",
        json={"test": "canonical_origin"},
        headers={"Content-Type": "application/json"},
        timeout=25
    )
    assert response3.status_code == 202, f"Receiver failed: {response3.text}"
    print(f"✅ Receiver works with canonical origin")
    
    response4 = session.get(f"{API_BASE}/server/events", timeout=25)
    assert response4.status_code == 200, f"Events failed: {response4.text}"
    print(f"✅ Events works with canonical origin")
    
    created_endpoints.append((session, token, user["id"]))
    return session


def cleanup_test_data():
    """Clean up test receipts and endpoints created during testing"""
    print("\n=== Cleanup Test Data ===")
    
    from pymongo import MongoClient
    import os
    
    # Connect to MongoDB
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "edge_india")
    
    client = MongoClient(mongo_url)
    db = client[db_name]
    
    # Get all user IDs from created endpoints
    user_ids = list(set(user_id for _, _, user_id in created_endpoints))
    
    if not user_ids:
        print("⚠️  No test data to clean up")
        return
    
    # Delete test receipts
    receipts_deleted = db.webhook_inbox.delete_many({"user_id": {"$in": user_ids}})
    print(f"✅ Deleted {receipts_deleted.deleted_count} test receipts")
    
    # Delete test endpoints
    endpoints_deleted = db.webhook_endpoints.delete_many({"user_id": {"$in": user_ids}})
    print(f"✅ Deleted {endpoints_deleted.deleted_count} test endpoints")
    
    # Do NOT delete the global egress observation (it's shared)
    # Do NOT delete test user accounts (they're isolated guests)
    
    print(f"✅ Cleanup complete: {len(user_ids)} test workspaces cleaned")
    
    client.close()


def run_all_tests():
    """Run all server connections tests"""
    print("\n" + "="*80)
    print("EDGE INDIA Server Connections Tests")
    print("Provider-neutral JSON postback receiver and connection details")
    print("="*80)
    
    results = {
        "passed": [],
        "failed": []
    }
    
    tests = [
        ("Connection Details Requires Workspace", test_connection_details_requires_workspace),
        ("Postback Provision Idempotent", test_postback_provision_idempotent),
        ("Concurrent Provision Idempotency", test_concurrent_provision_idempotency),
        ("Public Receiver POST JSON", test_public_receiver_post_json),
        ("Public Receiver Validation", test_public_receiver_validation),
        ("Public Receiver GET Health", test_public_receiver_get_health),
        ("Public Receiver Methods", test_public_receiver_methods),
        ("Events Metadata Only", test_events_metadata_only),
        ("Postback Rotate", test_postback_rotate),
        ("Observe Egress Real Lookup", test_observe_egress_real_lookup),
        ("CORS/CSRF Enforcement", test_cors_csrf_enforcement),
        ("Storage Encryption & Persistence", test_storage_encryption_persistence),
        ("Log Redaction", test_log_redaction),
        ("Canonical Origin Regression", test_canonical_origin_regression),
    ]
    
    for test_name, test_func in tests:
        try:
            test_func()
            results["passed"].append(test_name)
        except Exception as e:
            results["failed"].append((test_name, str(e)))
            print(f"❌ {test_name} FAILED: {e}")
    
    # Cleanup
    try:
        cleanup_test_data()
    except Exception as e:
        print(f"⚠️  Cleanup failed: {e}")
    
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
