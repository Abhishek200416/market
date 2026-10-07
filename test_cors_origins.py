"""
Comprehensive CORS origin policy tests for credentialed requests.

Tests both the canonical UUID origin and the named alias origin to ensure:
1. Both trusted origins can make credentialed requests
2. OPTIONS preflight returns exact origin (not wildcard) + credentials true + Vary Origin
3. POST /api/auth/workspace works from both origins
4. Authenticated requests with CSRF work
5. Missing/wrong CSRF rejected but CORS headers present
6. Missing Origin rejected
7. Foreign origins rejected (other preview tenant, malicious suffix, null, scheme mismatch)
8. No wildcard accepted
9. Sessions isolated between origins
"""
import os
import pytest
import httpx
from dotenv import load_dotenv
from pathlib import Path

# Load environment to get configured origins
backend_root = Path(__file__).parent / 'backend'
load_dotenv(backend_root / '.env')
load_dotenv(backend_root / '.env.origins')

# Get the backend URL from frontend .env
frontend_env = Path(__file__).parent / 'frontend' / '.env'
load_dotenv(frontend_env)
BACKEND_URL = os.environ['REACT_APP_BACKEND_URL']

# Get configured origins
CANONICAL_ORIGIN = os.environ['APP_ORIGIN']
ALIAS_ORIGIN = os.environ.get('APP_ALIAS_ORIGINS', '').split(',')[0].strip()

# Test origins
TRUSTED_ORIGINS = [CANONICAL_ORIGIN, ALIAS_ORIGIN]
FOREIGN_ORIGINS = [
    'https://credential-vault-84.preview.emergentagent.com',  # Different preview tenant
    'https://credential-vault-84.preview.emergentagent.com.evil.com',  # Malicious suffix
    'http://no-login-hub.preview.emergentagent.com',  # Wrong scheme
    'null',  # Null origin
    '*',  # Wildcard
]


class TestCORSOriginPolicy:
    """Test CORS origin policy for credentialed requests."""

    @pytest.mark.parametrize("origin", TRUSTED_ORIGINS)
    def test_options_preflight_trusted_origin(self, origin):
        """OPTIONS preflight from trusted origin returns exact origin + credentials true + Vary Origin."""
        response = httpx.options(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={
                'Origin': origin,
                'Access-Control-Request-Method': 'POST',
                'Access-Control-Request-Headers': 'content-type,x-csrf-token',
            },
            follow_redirects=False,
        )
        
        assert response.status_code == 200, f"Preflight failed for {origin}: {response.status_code}"
        
        # Check CORS headers
        acao = response.headers.get('access-control-allow-origin')
        assert acao == origin, f"Expected exact origin {origin}, got {acao}"
        assert acao != '*', "Wildcard ACAO not allowed with credentials"
        
        acac = response.headers.get('access-control-allow-credentials')
        assert acac == 'true', f"Expected credentials true, got {acac}"
        
        vary = response.headers.get('vary')
        assert vary and 'origin' in vary.lower(), f"Expected Vary: Origin, got {vary}"
        
        print(f"✅ OPTIONS preflight for {origin}: ACAO={acao}, credentials={acac}, Vary={vary}")

    @pytest.mark.parametrize("origin", TRUSTED_ORIGINS)
    def test_workspace_bootstrap_trusted_origin(self, origin):
        """POST /api/auth/workspace from trusted origin creates workspace with secure cookie."""
        response = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={'Origin': origin},
            follow_redirects=False,
        )
        
        assert response.status_code == 200, f"Workspace bootstrap failed for {origin}: {response.status_code} {response.text}"
        
        data = response.json()
        assert 'user' in data, "Missing user in response"
        assert 'csrf_token' in data, "Missing csrf_token in response"
        assert data['user']['is_guest'] is True, "Expected guest user"
        
        # Check secure HttpOnly cookie
        cookies = response.cookies
        assert 'terminal_session' in cookies, "Missing terminal_session cookie"
        
        # Check CORS headers
        acao = response.headers.get('access-control-allow-origin')
        assert acao == origin, f"Expected exact origin {origin}, got {acao}"
        
        acac = response.headers.get('access-control-allow-credentials')
        assert acac == 'true', f"Expected credentials true, got {acac}"
        
        print(f"✅ Workspace bootstrap for {origin}: user_id={data['user']['id']}, ACAO={acao}")

    @pytest.mark.parametrize("origin", TRUSTED_ORIGINS)
    def test_authenticated_request_with_csrf(self, origin):
        """Authenticated request with CSRF token succeeds."""
        # First, create workspace
        bootstrap_response = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={'Origin': origin},
            follow_redirects=False,
        )
        assert bootstrap_response.status_code == 200
        
        data = bootstrap_response.json()
        csrf_token = data['csrf_token']
        cookies = bootstrap_response.cookies
        
        # Now make authenticated write request with CSRF
        response = httpx.put(
            f'{BACKEND_URL}/api/paper/risk',
            headers={
                'Origin': origin,
                'X-CSRF-Token': csrf_token,
                'Content-Type': 'application/json',
            },
            cookies=cookies,
            json={'risk_per_trade': 0.5, 'daily_loss_limit': 2.0},
            follow_redirects=False,
        )
        
        assert response.status_code == 200, f"Authenticated request failed: {response.status_code} {response.text}"
        
        # Check CORS headers
        acao = response.headers.get('access-control-allow-origin')
        assert acao == origin, f"Expected exact origin {origin}, got {acao}"
        
        print(f"✅ Authenticated request with CSRF for {origin}: status={response.status_code}")

    @pytest.mark.parametrize("origin", TRUSTED_ORIGINS)
    def test_authenticated_request_without_csrf_rejected(self, origin):
        """Authenticated request without CSRF token is rejected but CORS headers present."""
        # First, create workspace
        bootstrap_response = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={'Origin': origin},
            follow_redirects=False,
        )
        assert bootstrap_response.status_code == 200
        
        cookies = bootstrap_response.cookies
        
        # Now make authenticated write request WITHOUT CSRF
        response = httpx.put(
            f'{BACKEND_URL}/api/paper/risk',
            headers={
                'Origin': origin,
                'Content-Type': 'application/json',
            },
            cookies=cookies,
            json={'risk_per_trade': 0.5, 'daily_loss_limit': 2.0},
            follow_redirects=False,
        )
        
        assert response.status_code == 403, f"Expected 403 without CSRF, got {response.status_code}"
        
        # Check CORS headers are still present for trusted origin
        acao = response.headers.get('access-control-allow-origin')
        assert acao == origin, f"Expected CORS headers even on 403, got {acao}"
        
        print(f"✅ Request without CSRF rejected for {origin}: status=403, ACAO={acao}")

    @pytest.mark.parametrize("origin", TRUSTED_ORIGINS)
    def test_authenticated_request_wrong_csrf_rejected(self, origin):
        """Authenticated request with wrong CSRF token is rejected but CORS headers present."""
        # First, create workspace
        bootstrap_response = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={'Origin': origin},
            follow_redirects=False,
        )
        assert bootstrap_response.status_code == 200
        
        cookies = bootstrap_response.cookies
        
        # Now make authenticated write request with WRONG CSRF
        response = httpx.put(
            f'{BACKEND_URL}/api/paper/risk',
            headers={
                'Origin': origin,
                'X-CSRF-Token': 'wrong_token_12345',
                'Content-Type': 'application/json',
            },
            cookies=cookies,
            json={'risk_per_trade': 0.5, 'daily_loss_limit': 2.0},
            follow_redirects=False,
        )
        
        assert response.status_code == 403, f"Expected 403 with wrong CSRF, got {response.status_code}"
        
        # Check CORS headers are still present for trusted origin
        acao = response.headers.get('access-control-allow-origin')
        assert acao == origin, f"Expected CORS headers even on 403, got {acao}"
        
        print(f"✅ Request with wrong CSRF rejected for {origin}: status=403, ACAO={acao}")

    def test_workspace_bootstrap_missing_origin_rejected(self):
        """POST /api/auth/workspace without Origin header is rejected."""
        response = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            follow_redirects=False,
        )
        
        assert response.status_code == 403, f"Expected 403 without Origin, got {response.status_code}"
        print(f"✅ Request without Origin rejected: status=403")

    @pytest.mark.parametrize("origin", FOREIGN_ORIGINS)
    def test_workspace_bootstrap_foreign_origin_rejected(self, origin):
        """POST /api/auth/workspace from foreign origin is rejected."""
        response = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={'Origin': origin},
            follow_redirects=False,
        )
        
        assert response.status_code == 403, f"Expected 403 for foreign origin {origin}, got {response.status_code}"
        
        # Check that no wildcard ACAO is granted
        acao = response.headers.get('access-control-allow-origin')
        assert acao != '*', f"Wildcard ACAO should not be granted for foreign origin {origin}"
        
        print(f"✅ Foreign origin {origin} rejected: status=403, ACAO={acao}")

    def test_session_isolation_between_origins(self):
        """Sessions created from different origins are isolated."""
        sessions = {}
        
        for origin in TRUSTED_ORIGINS:
            response = httpx.post(
                f'{BACKEND_URL}/api/auth/workspace',
                headers={'Origin': origin},
                follow_redirects=False,
            )
            assert response.status_code == 200
            
            data = response.json()
            sessions[origin] = {
                'user_id': data['user']['id'],
                'csrf_token': data['csrf_token'],
                'cookies': response.cookies,
            }
        
        # Verify different user IDs
        user_ids = [s['user_id'] for s in sessions.values()]
        assert len(set(user_ids)) == len(user_ids), "Sessions should have different user IDs"
        
        print(f"✅ Session isolation verified: {len(sessions)} separate sessions created")

    @pytest.mark.parametrize("origin", TRUSTED_ORIGINS)
    def test_workspace_resume_same_origin(self, origin):
        """Same cookie can resume workspace from same origin."""
        # First request
        response1 = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={'Origin': origin},
            follow_redirects=False,
        )
        assert response1.status_code == 200
        
        data1 = response1.json()
        user_id1 = data1['user']['id']
        cookies = response1.cookies
        
        # Second request with same cookie
        response2 = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={'Origin': origin},
            cookies=cookies,
            follow_redirects=False,
        )
        assert response2.status_code == 200
        
        data2 = response2.json()
        user_id2 = data2['user']['id']
        
        assert user_id1 == user_id2, "Same cookie should resume same workspace"
        print(f"✅ Workspace resume for {origin}: same user_id={user_id1}")

    @pytest.mark.parametrize("origin", TRUSTED_ORIGINS)
    def test_risk_persistence_with_csrf(self, origin):
        """Risk settings persist across requests with CSRF."""
        # Create workspace
        bootstrap_response = httpx.post(
            f'{BACKEND_URL}/api/auth/workspace',
            headers={'Origin': origin},
            follow_redirects=False,
        )
        assert bootstrap_response.status_code == 200
        
        data = bootstrap_response.json()
        csrf_token = data['csrf_token']
        cookies = bootstrap_response.cookies
        
        # Update risk settings
        risk_data = {'risk_per_trade': 0.7, 'daily_loss_limit': 3.5}
        update_response = httpx.put(
            f'{BACKEND_URL}/api/paper/risk',
            headers={
                'Origin': origin,
                'X-CSRF-Token': csrf_token,
                'Content-Type': 'application/json',
            },
            cookies=cookies,
            json=risk_data,
            follow_redirects=False,
        )
        assert update_response.status_code == 200
        
        # Verify persistence by fetching overview
        overview_response = httpx.get(
            f'{BACKEND_URL}/api/overview',
            headers={'Origin': origin},
            cookies=cookies,
            follow_redirects=False,
        )
        assert overview_response.status_code == 200
        
        overview_data = overview_response.json()
        account = overview_data['account']
        assert account['risk']['risk_per_trade'] == 0.7
        assert account['risk']['daily_loss_limit'] == 3.5
        
        print(f"✅ Risk persistence for {origin}: risk_per_trade=0.7, daily_loss_limit=3.5")

    def test_no_wildcard_in_allowed_origins(self):
        """Verify that ALLOWED_ORIGINS does not contain wildcards."""
        from backend.origin_policy import ALLOWED_ORIGINS
        
        for origin in ALLOWED_ORIGINS:
            assert '*' not in origin, f"Wildcard found in ALLOWED_ORIGINS: {origin}"
            assert origin.startswith('https://'), f"Non-HTTPS origin in ALLOWED_ORIGINS: {origin}"
        
        print(f"✅ ALLOWED_ORIGINS validated: {ALLOWED_ORIGINS}")

    def test_both_origins_in_allowed_list(self):
        """Verify both canonical and alias origins are in ALLOWED_ORIGINS."""
        from backend.origin_policy import ALLOWED_ORIGINS
        
        assert CANONICAL_ORIGIN in ALLOWED_ORIGINS, f"Canonical origin {CANONICAL_ORIGIN} not in ALLOWED_ORIGINS"
        assert ALIAS_ORIGIN in ALLOWED_ORIGINS, f"Alias origin {ALIAS_ORIGIN} not in ALLOWED_ORIGINS"
        
        print(f"✅ Both origins in ALLOWED_ORIGINS: {ALLOWED_ORIGINS}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
