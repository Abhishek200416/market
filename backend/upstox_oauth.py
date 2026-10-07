"""Explicitly gated OAuth. No secrets in callbacks, redirects, logs or frontend JSON."""
import hashlib
import json
import os
import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlparse
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from auth import user_required, digest
from connections import credentials, vault
from core import db, now, stamp, audit, Payload

router = APIRouter(prefix='/api/integrations/upstox')
CALLBACK_PATH = '/api/integrations/upstox/oauth/callback'

def registration_configuration():
    origin = os.environ.get('BROKER_PUBLIC_ORIGIN')
    valid = False
    if origin:
        try:
            parsed = urlparse(origin)
            valid = (parsed.scheme == 'https' and bool(parsed.hostname) and parsed.path in ('', '/')
                and not parsed.query and not parsed.fragment and not parsed.username and not parsed.port
                and '.preview.' not in parsed.hostname and parsed.hostname not in ('localhost', '127.0.0.1'))
        except ValueError:
            valid = False
    origin = origin.rstrip('/') if valid else None
    return {'app_name': 'EDGE INDIA Research', 'website_url': origin,
        'callback_path': CALLBACK_PATH, 'callback_url': origin + CALLBACK_PATH if origin else None,
        'callback_method': 'GET', 'postback_url': None, 'postback_status': 'NOT_REQUIRED_FOR_MARKET_DATA',
        'primary_ip': None, 'secondary_ip': None, 'ip_status': 'NO_VERIFIED_RESERVED_IP',
        'oauth_ready': bool(origin), 'oauth_status': 'CONFIGURED_NOT_BROKER_VERIFIED' if origin else 'PENDING_HTTPS_HOSTNAME',
        'description': 'Private Indian-market research and AI-model evaluation with simulated paper trading. Real-money execution disabled.',
        'analytics_token_note': 'Upstox documents no static-IP requirement for market quotes and historical data with its read-only Analytics Token. Account/portfolio APIs may require an IP; this adapter does not call them.',
        'paytm_status': 'DEFERRED_NOT_CONFIGURED', 'live_enabled': False}

@router.get('/registration', response_model=Payload)
async def registration():
    return registration_configuration()

@router.post('/oauth/start', response_model=Payload)
async def start(request: Request, user=Depends(user_required)):
    config = registration_configuration()
    if not config['oauth_ready']:
        raise HTTPException(409, 'Broker sign-in is pending a verified permanent HTTPS hostname. Use a read-only Analytics Token in the meantime.')
    values = await credentials(user['id'], 'upstox')
    if not values.get('api_key') or not values.get('api_secret'):
        raise HTTPException(409, 'Save your Upstox API key and secret before starting broker sign-in.')
    state = secrets.token_urlsafe(40)
    await db.oauth_states.insert_one({'state_hash': digest(state), 'user_id': user['id'],
        'session_hash': digest(request.cookies['terminal_session']), 'expires_at': now()+timedelta(minutes=10),
        'credential_fingerprint': hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest(),
        'redirect_uri': config['callback_url']})
    url = os.environ['UPSTOX_BASE_URL'] + '/v2/login/authorization/dialog?' + urlencode({
        'response_type': 'code', 'client_id': values['api_key'], 'redirect_uri': config['callback_url'], 'state': state})
    await audit(user['id'], 'upstox_oauth_started')
    return {'authorize_url': url}

@router.get('/oauth/callback')
async def callback(request: Request, code: str = '', state: str = '', error: str = '', user=Depends(user_required)):
    config = registration_configuration()
    if not config['oauth_ready']:
        raise HTTPException(409, 'Broker callback registration is not configured.')
    if error or not code or not state or len(code) > 4096 or len(state) > 256:
        raise HTTPException(400, 'Broker authorization was not completed.')
    # Atomic consumption, same account and same browser session. A mismatched caller
    # cannot consume another user's state. Codes are never reused after a failed exchange.
    record = await db.oauth_states.find_one_and_delete({'state_hash': digest(state), 'user_id': user['id'],
        'session_hash': digest(request.cookies['terminal_session']), 'expires_at': {'$gt': now()}}, projection={'_id': 0})
    if not record or not secrets.compare_digest(record['state_hash'], digest(state)):
        raise HTTPException(400, 'Invalid, expired or already-used authorization state.')
    values = await credentials(user['id'], 'upstox')
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    if not secrets.compare_digest(fingerprint, record['credential_fingerprint']) or record['redirect_uri'] != config['callback_url']:
        raise HTTPException(409, 'Connection configuration changed. Restart broker sign-in.')
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(os.environ['UPSTOX_BASE_URL']+'/v2/login/authorization/token',
                data={'code': code, 'client_id': values['api_key'], 'client_secret': values['api_secret'],
                      'redirect_uri': config['callback_url'], 'grant_type': 'authorization_code'},
                headers={'Accept': 'application/json'})
        response.raise_for_status()
        token = response.json().get('access_token')
        if not token or not isinstance(token, str):
            raise ValueError('No token')
    except (httpx.HTTPError, ValueError):
        await audit(user['id'], 'upstox_oauth_failed')
        raise HTTPException(502, 'Upstox authorization exchange failed. Start a new sign-in; no credentials were returned to the browser.')
    values['access_token'] = token
    await db.credentials.update_one({'user_id': user['id'], 'provider': 'upstox'}, {'$set': {
        'encrypted': vault.encrypt(json.dumps(values).encode()).decode(), 'configured_fields': list(values),
        'status': 'UNTESTED', 'updated_at': stamp(), 'error': None, 'last_test': None, 'last_success': None}})
    await audit(user['id'], 'upstox_oauth_completed')
    # No provider tokens or authorization code in redirect query parameters.
    return RedirectResponse(config['website_url']+'/connections?broker=upstox&authorization=complete', status_code=303)