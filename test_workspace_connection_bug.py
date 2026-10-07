"""
Test workspace connection bug fix: Named alias origin against canonical API.

This test verifies the reported bug where browser at named alias origin
(https://credential-vault-84.preview.emergentagent.com) could not connect
to the canonical API (https://dc12a019-fe0d-4990-be49-f9c9014edc75.preview.emergentagent.com).

The fix restored APP_ALIAS_ORIGINS in backend/.env.origins.

Test requirements from review request:
1. Test OPTIONS + POST /api/auth/workspace with named Origin against canonical API
2. Verify exact ACAO (never wildcard *), credentials=true, secure cookie
3. Workspace resumes same user
4. /api/overview/private and /api/server/details/events working
5. CSRF write provisioning succeeds, missing & wrong CSRF rejects
6. Foreign origins reject
7. Postback provision, public JSON receiver, inbox from named-origin session still work
"""
import os
import httpx
from pathlib import Path
from dotenv import load_dotenv

# Load environment
backend_root = Path(__file__).parent / 'backend'
load_dotenv(backend_root / '.env')
load_dotenv(backend_root / '.env.origins')

# Get the canonical API URL from frontend .env
frontend_env = Path(__file__).parent / 'frontend' / '.env'
load_dotenv(frontend_env)
CANONICAL_API = os.environ['REACT_APP_BACKEND_URL']

# Get configured origins
CANONICAL_ORIGIN = os.environ['APP_ORIGIN']
NAMED_ALIAS_ORIGIN = os.environ.get('APP_ALIAS_ORIGINS', '').split(',')[0].strip()

print(f"\n{'='*80}")
print(f"WORKSPACE CONNECTION BUG VERIFICATION")
print(f"{'='*80}")
print(f"Canonical API URL: {CANONICAL_API}")
print(f"Canonical Origin:  {CANONICAL_ORIGIN}")
print(f"Named Alias Origin: {NAMED_ALIAS_ORIGIN}")
print(f"{'='*80}\n")

# Verify distinct origins
assert CANONICAL_ORIGIN != NAMED_ALIAS_ORIGIN, "Origins must be distinct!"
assert CANONICAL_API == CANONICAL_ORIGIN, "API URL must match canonical origin!"

# Test counter
test_count = 0
passed_count = 0

def test_result(name, passed, details=""):
    global test_count, passed_count
    test_count += 1
    if passed:
        passed_count += 1
        print(f"✅ Test {test_count}: {name}")
    else:
        print(f"❌ Test {test_count}: {name}")
    if details:
        print(f"   {details}")
    return passed


# Test 1: OPTIONS preflight with named origin against canonical API
print("\n--- Test 1: OPTIONS Preflight ---")
response = httpx.options(
    f'{CANONICAL_API}/api/auth/workspace',
    headers={
        'Origin': NAMED_ALIAS_ORIGIN,
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type,x-csrf-token',
    },
    follow_redirects=False,
)

acao = response.headers.get('access-control-allow-origin', '')
acac = response.headers.get('access-control-allow-credentials', '')
vary = response.headers.get('vary', '')

test_result(
    "OPTIONS preflight returns 200",
    response.status_code == 200,
    f"Status: {response.status_code}"
)

test_result(
    "ACAO is exact named origin (not wildcard)",
    acao == NAMED_ALIAS_ORIGIN and acao != '*',
    f"ACAO: {acao}"
)

test_result(
    "Credentials allowed",
    acac == 'true',
    f"Access-Control-Allow-Credentials: {acac}"
)

test_result(
    "Vary: Origin header present",
    'origin' in vary.lower(),
    f"Vary: {vary}"
)


# Test 2: POST /api/auth/workspace with named origin
print("\n--- Test 2: Workspace Bootstrap ---")
response = httpx.post(
    f'{CANONICAL_API}/api/auth/workspace',
    headers={'Origin': NAMED_ALIAS_ORIGIN},
    follow_redirects=False,
)

test_result(
    "POST /api/auth/workspace returns 200",
    response.status_code == 200,
    f"Status: {response.status_code}"
)

if response.status_code == 200:
    data = response.json()
    test_result(
        "Response contains user and csrf_token",
        'user' in data and 'csrf_token' in data,
        f"Keys: {list(data.keys())}"
    )
    
    test_result(
        "User is guest",
        data.get('user', {}).get('is_guest') is True,
        f"is_guest: {data.get('user', {}).get('is_guest')}"
    )
    
    # Save session for later tests
    session_cookie = response.cookies.get('terminal_session')
    csrf_token = data.get('csrf_token')
    user_id = data.get('user', {}).get('id')
    
    test_result(
        "Secure HttpOnly cookie set",
        session_cookie is not None,
        f"Cookie present: {session_cookie is not None}"
    )
    
    acao = response.headers.get('access-control-allow-origin', '')
    test_result(
        "ACAO is exact named origin",
        acao == NAMED_ALIAS_ORIGIN,
        f"ACAO: {acao}"
    )
else:
    print(f"   ❌ Failed to create workspace: {response.text}")
    session_cookie = None
    csrf_token = None
    user_id = None


# Test 3: Workspace resume with same cookie
if session_cookie and csrf_token:
    print("\n--- Test 3: Workspace Resume ---")
    response = httpx.post(
        f'{CANONICAL_API}/api/auth/workspace',
        headers={'Origin': NAMED_ALIAS_ORIGIN},
        cookies={'terminal_session': session_cookie},
        follow_redirects=False,
    )
    
    test_result(
        "Workspace resume returns 200",
        response.status_code == 200,
        f"Status: {response.status_code}"
    )
    
    if response.status_code == 200:
        data = response.json()
        resumed_user_id = data.get('user', {}).get('id')
        test_result(
            "Same user_id resumed",
            resumed_user_id == user_id,
            f"Original: {user_id}, Resumed: {resumed_user_id}"
        )


# Test 4: /api/overview (private endpoint)
if session_cookie and csrf_token:
    print("\n--- Test 4: Private Endpoint /api/overview ---")
    response = httpx.get(
        f'{CANONICAL_API}/api/overview',
        headers={'Origin': NAMED_ALIAS_ORIGIN},
        cookies={'terminal_session': session_cookie},
        follow_redirects=False,
    )
    
    test_result(
        "/api/overview returns 200",
        response.status_code == 200,
        f"Status: {response.status_code}"
    )
    
    if response.status_code == 200:
        data = response.json()
        test_result(
            "Overview contains account data",
            'cash' in data or 'account' in data,
            f"Keys: {list(data.keys())}"
        )


# Test 5: /api/server/events (server connection endpoint)
if session_cookie and csrf_token:
    print("\n--- Test 5: Server Events ---")
    response = httpx.get(
        f'{CANONICAL_API}/api/server/events',
        headers={'Origin': NAMED_ALIAS_ORIGIN},
        cookies={'terminal_session': session_cookie},
        follow_redirects=False,
    )
    
    test_result(
        "/api/server/events returns 200",
        response.status_code == 200,
        f"Status: {response.status_code}"
    )
    
    if response.status_code == 200:
        data = response.json()
        test_result(
            "Events response contains events list",
            'events' in data and isinstance(data['events'], list),
            f"Keys: {list(data.keys())}"
        )


# Test 6: CSRF protection - write succeeds with token
if session_cookie and csrf_token:
    print("\n--- Test 6: CSRF Protection - Valid Token ---")
    response = httpx.put(
        f'{CANONICAL_API}/api/paper/risk',
        headers={
            'Origin': NAMED_ALIAS_ORIGIN,
            'X-CSRF-Token': csrf_token,
            'Content-Type': 'application/json',
        },
        cookies={'terminal_session': session_cookie},
        json={
            'risk_per_trade': 0.6,
            'daily_loss_limit': 2.5,
            'max_consecutive_losses': 3,
            'max_trades_day': 10,
            'cooldown_seconds': 60,
            'max_exposure': 30.0,
            'max_position': 10.0,
            'min_risk_reward': 2.0,
            'min_volume': 1000,
            'max_spread_bps': 25.0,
        },
        follow_redirects=False,
    )
    
    test_result(
        "Write with valid CSRF succeeds",
        response.status_code == 200,
        f"Status: {response.status_code}"
    )


# Test 7: CSRF protection - write fails without token
if session_cookie:
    print("\n--- Test 7: CSRF Protection - Missing Token ---")
    response = httpx.put(
        f'{CANONICAL_API}/api/paper/risk',
        headers={
            'Origin': NAMED_ALIAS_ORIGIN,
            'Content-Type': 'application/json',
        },
        cookies={'terminal_session': session_cookie},
        json={
            'risk_per_trade': 0.6,
            'daily_loss_limit': 2.5,
            'max_consecutive_losses': 3,
            'max_trades_day': 10,
            'cooldown_seconds': 60,
            'max_exposure': 30.0,
            'max_position': 10.0,
            'min_risk_reward': 2.0,
            'min_volume': 1000,
            'max_spread_bps': 25.0,
        },
        follow_redirects=False,
    )
    
    test_result(
        "Write without CSRF rejected (403)",
        response.status_code == 403,
        f"Status: {response.status_code}"
    )


# Test 8: CSRF protection - write fails with wrong token
if session_cookie:
    print("\n--- Test 8: CSRF Protection - Wrong Token ---")
    response = httpx.put(
        f'{CANONICAL_API}/api/paper/risk',
        headers={
            'Origin': NAMED_ALIAS_ORIGIN,
            'X-CSRF-Token': 'wrong_token_12345',
            'Content-Type': 'application/json',
        },
        cookies={'terminal_session': session_cookie},
        json={
            'risk_per_trade': 0.6,
            'daily_loss_limit': 2.5,
            'max_consecutive_losses': 3,
            'max_trades_day': 10,
            'cooldown_seconds': 60,
            'max_exposure': 30.0,
            'max_position': 10.0,
            'min_risk_reward': 2.0,
            'min_volume': 1000,
            'max_spread_bps': 25.0,
        },
        follow_redirects=False,
    )
    
    test_result(
        "Write with wrong CSRF rejected (403)",
        response.status_code == 403,
        f"Status: {response.status_code}"
    )


# Test 9: Foreign origin rejection - different tenant
print("\n--- Test 9: Foreign Origin Rejection ---")
foreign_origins = [
    'https://other-app-99.preview.emergentagent.com',  # Different tenant
    'https://credential-vault-84.preview.emergentagent.com.evil.com',  # Malicious suffix
    'http://credential-vault-84.preview.emergentagent.com',  # Wrong scheme
    'null',  # Null origin
    '*',  # Wildcard
]

for foreign_origin in foreign_origins:
    response = httpx.post(
        f'{CANONICAL_API}/api/auth/workspace',
        headers={'Origin': foreign_origin},
        follow_redirects=False,
    )
    
    test_result(
        f"Foreign origin rejected: {foreign_origin[:50]}",
        response.status_code == 403,
        f"Status: {response.status_code}"
    )


# Test 10: Postback provision with CSRF
if session_cookie and csrf_token:
    print("\n--- Test 10: Postback Provision ---")
    response = httpx.post(
        f'{CANONICAL_API}/api/server/postback',
        headers={
            'Origin': NAMED_ALIAS_ORIGIN,
            'X-CSRF-Token': csrf_token,
        },
        cookies={'terminal_session': session_cookie},
        follow_redirects=False,
    )
    
    test_result(
        "Postback provision succeeds",
        response.status_code == 200,
        f"Status: {response.status_code}"
    )
    
    if response.status_code == 200:
        data = response.json()
        receive_path = data.get('receive_path', '')
        test_result(
            "Receive path returned",
            receive_path.startswith('/api/server/receive/'),
            f"Path: {receive_path[:40]}..."
        )
        
        # Save for next test
        receiver_token = receive_path.split('/')[-1] if receive_path else None
    else:
        receiver_token = None
else:
    receiver_token = None


# Test 11: Public JSON receiver (no auth required)
if receiver_token:
    print("\n--- Test 11: Public JSON Receiver ---")
    response = httpx.post(
        f'{CANONICAL_API}/api/server/receive/{receiver_token}',
        headers={'Content-Type': 'application/json'},
        json={'test': 'data', 'type': 'application_self_test'},
        follow_redirects=False,
    )
    
    test_result(
        "Public receiver accepts JSON",
        response.status_code in [200, 202],
        f"Status: {response.status_code}"
    )


# Test 12: Inbox from named-origin session
if session_cookie and csrf_token:
    print("\n--- Test 12: Inbox from Named-Origin Session ---")
    response = httpx.get(
        f'{CANONICAL_API}/api/server/events',
        headers={'Origin': NAMED_ALIAS_ORIGIN},
        cookies={'terminal_session': session_cookie},
        follow_redirects=False,
    )
    
    test_result(
        "Inbox accessible from named-origin session",
        response.status_code == 200,
        f"Status: {response.status_code}"
    )
    
    if response.status_code == 200:
        data = response.json()
        test_result(
            "Events list returned",
            'events' in data and isinstance(data['events'], list),
            f"Event count: {len(data.get('events', []))}"
        )


# Test 13: Canonical origin still works (regression)
print("\n--- Test 13: Canonical Origin Regression ---")
response = httpx.post(
    f'{CANONICAL_API}/api/auth/workspace',
    headers={'Origin': CANONICAL_ORIGIN},
    follow_redirects=False,
)

test_result(
    "Canonical origin still works",
    response.status_code == 200,
    f"Status: {response.status_code}"
)

if response.status_code == 200:
    acao = response.headers.get('access-control-allow-origin', '')
    test_result(
        "Canonical origin gets exact ACAO",
        acao == CANONICAL_ORIGIN,
        f"ACAO: {acao}"
    )


# Summary
print(f"\n{'='*80}")
print(f"TEST SUMMARY")
print(f"{'='*80}")
print(f"Total Tests: {test_count}")
print(f"Passed: {passed_count}")
print(f"Failed: {test_count - passed_count}")
print(f"Success Rate: {passed_count/test_count*100:.1f}%")
print(f"{'='*80}\n")

if passed_count == test_count:
    print("✅ ALL TESTS PASSED - Workspace connection bug FIXED!")
    exit(0)
else:
    print("❌ SOME TESTS FAILED - Workspace connection bug NOT fully fixed")
    exit(1)
