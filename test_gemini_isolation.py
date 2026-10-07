#!/usr/bin/env python3
"""
Test that Gemini credentials are isolated per workspace and no global seeding occurs.
"""
import asyncio
import httpx
import sys

API_BASE = "https://dc12a019-fe0d-4990-be49-f9c9014edc75.preview.emergentagent.com"

async def test_isolation():
    """Test that second guest has no Gemini credentials."""
    
    print("=" * 80)
    print("GEMINI CREDENTIAL ISOLATION TEST")
    print("=" * 80)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Create second guest workspace
            print("\n1. Creating second guest workspace...")
            resp = await client.post(
                f"{API_BASE}/api/auth/workspace",
                headers={'Origin': API_BASE}
            )
            
            if resp.status_code != 200:
                print(f"  ❌ Workspace creation failed: {resp.status_code}")
                return False
            
            data = resp.json()
            user_id = data.get('user', {}).get('id')
            print(f"  ✅ Second workspace created: {user_id[:8]}...")
            
            # Check connections status
            print("\n2. Checking Gemini connection status...")
            resp = await client.get(
                f"{API_BASE}/api/connections",
                headers={'Origin': API_BASE},
                cookies=resp.cookies
            )
            
            if resp.status_code != 200:
                print(f"  ❌ Connections check failed: {resp.status_code}")
                return False
            
            data = resp.json()
            connections = data.get('connections', [])
            gemini_conn = next((c for c in connections if c['provider'] == 'gemini'), None)
            
            if not gemini_conn:
                print("  ❌ Gemini connection not found in list")
                return False
            
            status = gemini_conn.get('status')
            configured_fields = gemini_conn.get('configured_fields', [])
            
            print(f"  Status: {status}")
            print(f"  Configured Fields: {configured_fields}")
            
            if status == 'DISCONNECTED' and len(configured_fields) == 0:
                print("  ✅ Second guest is DISCONNECTED with no credentials (correct)")
                return True
            else:
                print(f"  ❌ Second guest has unexpected status or credentials")
                print(f"     Expected: DISCONNECTED with no fields")
                print(f"     Got: {status} with fields {configured_fields}")
                return False
                
    except Exception as e:
        print(f"  ❌ Exception: {type(e).__name__}: {e}")
        return False

# Run test
result = asyncio.run(test_isolation())

print("\n" + "=" * 80)
if result:
    print("✅ ISOLATION TEST PASSED")
    print("   No global Gemini credentials seeded to new guests")
else:
    print("❌ ISOLATION TEST FAILED")
    sys.exit(1)
print("=" * 80)
