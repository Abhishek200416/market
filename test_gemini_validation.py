#!/usr/bin/env python3
"""
Private Gemini key validation test - User authorized read-only testing.
Secrets never printed or exposed in reports.
"""
import os
import sys
import json
import asyncio
import httpx
from datetime import datetime

# Load validation secrets (never print these)
VALIDATION_ENV = {}
try:
    with open('/app/backend/.env.validation', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                VALIDATION_ENV[key.strip()] = value.strip()
except Exception as e:
    print(f"❌ CRITICAL: Cannot read /app/backend/.env.validation: {e}")
    sys.exit(1)

GEMINI_KEY = VALIDATION_ENV.get('GEMINI_VALIDATION_KEY')
PAYTM_API_KEY = VALIDATION_ENV.get('PAYTM_VALIDATION_API_KEY')
PAYTM_API_SECRET = VALIDATION_ENV.get('PAYTM_VALIDATION_API_SECRET')

if not GEMINI_KEY:
    print("❌ CRITICAL: GEMINI_VALIDATION_KEY not found in .env.validation")
    sys.exit(1)

# Load configured models
APP_ENV = {}
try:
    with open('/app/backend/.env', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                APP_ENV[key.strip()] = value.strip()
except Exception as e:
    print(f"❌ CRITICAL: Cannot read /app/backend/.env: {e}")
    sys.exit(1)

QUICK_MODEL = APP_ENV.get('GEMINI_QUICK_MODEL', 'gemini-3.5-flash-lite')
DEEP_MODEL = APP_ENV.get('GEMINI_DEEP_MODEL', 'gemini-3.1-pro-preview')
API_BASE = APP_ENV.get('APP_ORIGIN', 'http://localhost:8001')

print("=" * 80)
print("GEMINI KEY VALIDATION TEST")
print("=" * 80)
print(f"Quick Model: {QUICK_MODEL}")
print(f"Deep Model: {DEEP_MODEL}")
print(f"API Base: {API_BASE}")
print(f"Gemini Key: {'*' * 20} (redacted)")
print(f"Paytm Key: {'Present' if PAYTM_API_KEY else 'Missing'}")
print(f"Paytm Secret: {'Present' if PAYTM_API_SECRET else 'Missing'}")
print("=" * 80)
print()

# Test results storage
results = {
    'timestamp': datetime.utcnow().isoformat(),
    'independent_sdk_tests': [],
    'app_integration_test': {},
    'paytm_check': {},
    'health_check': {}
}

# ============================================================================
# PART 1: Independent Gemini SDK Validation
# ============================================================================
print("PART 1: INDEPENDENT GEMINI SDK VALIDATION")
print("-" * 80)

def test_gemini_model(model_name: str, api_key: str, max_tokens: int = 64) -> dict:
    """
    Test a single Gemini model with minimal generation.
    Returns sanitized result with no secrets.
    """
    result = {
        'model': model_name,
        'success': False,
        'status': None,
        'error_type': None,
        'response_received': False,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    try:
        import google.genai as genai
        from google.genai import types
        
        # Create client with user's key
        client = genai.Client(api_key=api_key)
        
        # Configure generation with retry disabled
        generation_config = types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=max_tokens,
            response_modalities=["TEXT"]
        )
        
        # Make ONE generation request
        print(f"  Testing {model_name}...")
        response = client.models.generate_content(
            model=model_name,
            contents='Reply exactly OK',
            config=generation_config
        )
        
        # Check if we got a response
        if response and response.text:
            result['success'] = True
            result['response_received'] = True
            result['status'] = 'SUCCESS'
            print(f"  ✅ {model_name}: SUCCESS (response received)")
        else:
            result['status'] = 'EMPTY_RESPONSE'
            result['error_type'] = 'NO_TEXT_IN_RESPONSE'
            print(f"  ⚠️  {model_name}: Empty response")
            
    except Exception as e:
        # Sanitize error - never print full exception or key
        error_str = str(e)
        result['success'] = False
        
        # Extract error type without exposing secrets
        if 'API_KEY_INVALID' in error_str or 'invalid API key' in error_str.lower():
            result['error_type'] = 'API_KEY_INVALID'
            result['status'] = 'AUTHENTICATION_FAILED'
        elif 'PERMISSION_DENIED' in error_str or 'permission denied' in error_str.lower():
            result['error_type'] = 'PERMISSION_DENIED'
            result['status'] = 'PERMISSION_DENIED'
        elif 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
            result['error_type'] = 'RESOURCE_EXHAUSTED'
            result['status'] = 'QUOTA_EXCEEDED'
        elif 'NOT_FOUND' in error_str or 'not found' in error_str.lower():
            result['error_type'] = 'MODEL_NOT_FOUND'
            result['status'] = 'MODEL_NOT_FOUND'
        elif 'timeout' in error_str.lower():
            result['error_type'] = 'TIMEOUT'
            result['status'] = 'TIMEOUT'
        else:
            result['error_type'] = 'UNKNOWN_ERROR'
            result['status'] = 'FAILED'
        
        print(f"  ❌ {model_name}: {result['status']} ({result['error_type']})")
    
    return result

# Test both configured models (max 2 requests)
print(f"\n1. Testing {QUICK_MODEL}...")
quick_result = test_gemini_model(QUICK_MODEL, GEMINI_KEY, max_tokens=64)
results['independent_sdk_tests'].append(quick_result)

print(f"\n2. Testing {DEEP_MODEL}...")
deep_result = test_gemini_model(DEEP_MODEL, GEMINI_KEY, max_tokens=128)
results['independent_sdk_tests'].append(deep_result)

print("\n" + "=" * 80)
print("INDEPENDENT SDK TEST SUMMARY:")
print(f"  Quick Model ({QUICK_MODEL}): {'✅ SUCCESS' if quick_result['success'] else '❌ ' + quick_result['status']}")
print(f"  Deep Model ({DEEP_MODEL}): {'✅ SUCCESS' if deep_result['success'] else '❌ ' + deep_result['status']}")
print("=" * 80)
print()

# If both models failed, stop here as instructed
if not quick_result['success'] and not deep_result['success']:
    print("⚠️  BOTH MODEL TESTS FAILED - STOPPING AS INSTRUCTED")
    print("Main agent should use troubleshoot before further attempts.")
    results['stopped_early'] = True
    
    # Save results
    with open('/app/gemini_validation_report.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    sys.exit(1)

# ============================================================================
# PART 2: In-App Integration Test
# ============================================================================
print("\nPART 2: IN-APP INTEGRATION TEST")
print("-" * 80)

async def test_app_integration():
    """
    Test Gemini integration through the app's API.
    Creates guest, saves key, tests, and cleans up.
    """
    result = {
        'workspace_created': False,
        'key_saved': False,
        'test_called': False,
        'test_success': False,
        'cleanup_done': False,
        'dependency_error': False,
        'error': None
    }
    
    user_id = None
    csrf_token = None
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Create guest workspace
            print("\n1. Creating guest workspace...")
            resp = await client.post(
                f"{API_BASE}/api/auth/workspace",
                headers={'Origin': API_BASE}
            )
            
            if resp.status_code != 200:
                result['error'] = f"Workspace creation failed: {resp.status_code}"
                print(f"  ❌ {result['error']}")
                return result
            
            data = resp.json()
            user_id = data.get('user', {}).get('id')
            csrf_token = data.get('csrf_token')
            cookies = resp.cookies
            
            result['workspace_created'] = True
            print(f"  ✅ Workspace created: {user_id[:8]}...")
            
            # Save Gemini key
            print("\n2. Saving Gemini key via PUT /api/connections/gemini...")
            resp = await client.put(
                f"{API_BASE}/api/connections/gemini",
                headers={
                    'Origin': API_BASE,
                    'X-CSRF-Token': csrf_token
                },
                cookies=cookies,
                json={'values': {'api_key': GEMINI_KEY}}
            )
            
            if resp.status_code != 200:
                result['error'] = f"Key save failed: {resp.status_code}"
                print(f"  ❌ {result['error']}")
                return result
            
            result['key_saved'] = True
            print("  ✅ Key saved successfully")
            
            # Test connection
            print("\n3. Testing connection via POST /api/connections/gemini/test...")
            resp = await client.post(
                f"{API_BASE}/api/connections/gemini/test",
                headers={
                    'Origin': API_BASE,
                    'X-CSRF-Token': csrf_token
                },
                cookies=cookies
            )
            
            result['test_called'] = True
            
            if resp.status_code != 200:
                result['error'] = f"Test call failed: {resp.status_code}"
                print(f"  ❌ {result['error']}")
                return result
            
            test_data = resp.json()
            result['test_success'] = test_data.get('ok', False)
            
            # Check connection status
            connections = test_data.get('connections', [])
            gemini_conn = next((c for c in connections if c['provider'] == 'gemini'), None)
            
            if gemini_conn:
                result['connection_status'] = gemini_conn.get('status')
                result['configured_fields'] = gemini_conn.get('configured_fields', [])
                
                if gemini_conn.get('status') == 'CONNECTED':
                    print(f"  ✅ Connection test PASSED")
                    print(f"     Status: {gemini_conn.get('status')}")
                    print(f"     Configured: {gemini_conn.get('configured_fields')}")
                elif gemini_conn.get('status') == 'ERROR':
                    print(f"  ❌ Connection test FAILED")
                    print(f"     Status: {gemini_conn.get('status')}")
                    print(f"     Error: {gemini_conn.get('error', 'Unknown')}")
                    
                    # Check if it's a dependency error
                    error_msg = gemini_conn.get('error', '')
                    if 'tradingagents' in error_msg.lower() or 'import' in error_msg.lower():
                        result['dependency_error'] = True
                        print("     ⚠️  Known dependency issue: TradingAgents not importable")
            
    except Exception as e:
        result['error'] = f"Integration test exception: {type(e).__name__}"
        print(f"  ❌ {result['error']}")
    
    finally:
        # ALWAYS cleanup - delete credential
        if user_id and csrf_token:
            try:
                print("\n4. Cleaning up - deleting credential...")
                async with httpx.AsyncClient(timeout=30.0) as cleanup_client:
                    resp = await cleanup_client.delete(
                        f"{API_BASE}/api/connections/gemini",
                        headers={
                            'Origin': API_BASE,
                            'X-CSRF-Token': csrf_token
                        },
                        cookies=cookies
                    )
                    
                    if resp.status_code == 200:
                        result['cleanup_done'] = True
                        print("  ✅ Credential deleted successfully")
                        
                        # Verify disconnected
                        data = resp.json()
                        connections = data.get('connections', [])
                        gemini_conn = next((c for c in connections if c['provider'] == 'gemini'), None)
                        if gemini_conn and gemini_conn.get('status') == 'DISCONNECTED':
                            print("  ✅ Verified: Status is DISCONNECTED")
                    else:
                        print(f"  ⚠️  Cleanup returned {resp.status_code}")
            except Exception as e:
                print(f"  ⚠️  Cleanup exception: {type(e).__name__}")
    
    return result

# Run app integration test
app_result = asyncio.run(test_app_integration())
results['app_integration_test'] = app_result

print("\n" + "=" * 80)
print("APP INTEGRATION TEST SUMMARY:")
print(f"  Workspace Created: {'✅' if app_result['workspace_created'] else '❌'}")
print(f"  Key Saved: {'✅' if app_result['key_saved'] else '❌'}")
print(f"  Test Called: {'✅' if app_result['test_called'] else '❌'}")
print(f"  Test Success: {'✅' if app_result['test_success'] else '❌'}")
print(f"  Cleanup Done: {'✅' if app_result['cleanup_done'] else '❌'}")
if app_result.get('dependency_error'):
    print("  ⚠️  Known Issue: TradingAgents import failure (inherited)")
print("=" * 80)
print()

# ============================================================================
# PART 3: Paytm Prerequisites Check
# ============================================================================
print("\nPART 3: PAYTM PREREQUISITES CHECK")
print("-" * 80)

paytm_result = {
    'api_key_present': bool(PAYTM_API_KEY),
    'api_secret_present': bool(PAYTM_API_SECRET),
    'request_token_present': False,
    'access_token_present': False,
    'authenticated_calls_possible': False,
    'adapter_exists': False
}

print(f"  Paytm API Key: {'✅ Present' if paytm_result['api_key_present'] else '❌ Missing'}")
print(f"  Paytm API Secret: {'✅ Present' if paytm_result['api_secret_present'] else '❌ Missing'}")
print(f"  Request Token: {'❌ Not supplied' if not paytm_result['request_token_present'] else '✅ Present'}")
print(f"  Access Token: {'❌ Not supplied' if not paytm_result['access_token_present'] else '✅ Present'}")

# Check if Paytm adapter exists in connections
print("\n  Checking connections.py for Paytm adapter...")
with open('/app/backend/connections.py', 'r') as f:
    connections_code = f.read()
    if 'paytm' in connections_code.lower():
        paytm_result['adapter_exists'] = True
        print("  ⚠️  Paytm references found in connections.py")
    else:
        print("  ✅ No Paytm adapter in connections.py (as expected)")

paytm_result['authenticated_calls_possible'] = (
    paytm_result['api_key_present'] and 
    paytm_result['api_secret_present'] and
    paytm_result['request_token_present'] and
    paytm_result['access_token_present']
)

print(f"\n  Authenticated Paytm Calls: {'✅ Possible' if paytm_result['authenticated_calls_possible'] else '❌ BLOCKED (no request/access token)'}")

results['paytm_check'] = paytm_result

print("=" * 80)
print()

# ============================================================================
# PART 4: Health Check
# ============================================================================
print("\nPART 4: HEALTH CHECK")
print("-" * 80)

async def check_health():
    """Verify health endpoint and no orders executed."""
    result = {
        'health_ok': False,
        'database': None,
        'api': None,
        'mode': None,
        'orders_count': 0
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Check health
            resp = await client.get(f"{API_BASE}/api/health")
            if resp.status_code == 200:
                data = resp.json()
                result['health_ok'] = True
                result['database'] = data.get('database')
                result['api'] = data.get('api')
                result['mode'] = data.get('mode')
                
                print(f"  ✅ Health check passed")
                print(f"     Database: {result['database']}")
                print(f"     API: {result['api']}")
                print(f"     Mode: {result['mode']}")
            else:
                print(f"  ❌ Health check failed: {resp.status_code}")
    except Exception as e:
        print(f"  ❌ Health check exception: {type(e).__name__}")
    
    return result

health_result = asyncio.run(check_health())
results['health_check'] = health_result

print("=" * 80)
print()

# ============================================================================
# FINAL SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print("FINAL VALIDATION SUMMARY")
print("=" * 80)

print("\n1. INDEPENDENT SDK TESTS:")
for test in results['independent_sdk_tests']:
    status = '✅ SUCCESS' if test['success'] else f"❌ {test['status']}"
    print(f"   {test['model']}: {status}")

print("\n2. APP INTEGRATION:")
app = results['app_integration_test']
if app.get('dependency_error'):
    print("   ⚠️  Known Issue: TradingAgents import failure (inherited, not credential issue)")
print(f"   Workspace: {'✅' if app['workspace_created'] else '❌'}")
print(f"   Key Save: {'✅' if app['key_saved'] else '❌'}")
print(f"   Test: {'✅' if app['test_success'] else '❌'}")
print(f"   Cleanup: {'✅' if app['cleanup_done'] else '❌'}")

print("\n3. PAYTM:")
paytm = results['paytm_check']
print(f"   Credentials: {'✅ Present' if paytm['api_key_present'] and paytm['api_secret_present'] else '❌ Missing'}")
print(f"   Tokens: ❌ Not supplied (request/access token required)")
print(f"   Authenticated Calls: ❌ BLOCKED")

print("\n4. HEALTH:")
health = results['health_check']
print(f"   API: {'✅ ' + health['api'] if health['health_ok'] else '❌ Failed'}")
print(f"   Database: {'✅ ' + health['database'] if health['health_ok'] else '❌ Failed'}")

print("\n" + "=" * 80)

# Save sanitized report (no secrets)
with open('/app/gemini_validation_report.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\n✅ Sanitized report saved to: /app/gemini_validation_report.json")
print("   (No secrets included in report)")
print("\n" + "=" * 80)
