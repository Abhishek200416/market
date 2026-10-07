"""Broker-neutral inbound transport. Receipt NEVER means broker authentication.

The only public write is to an isolated encrypted inbox. Nothing in this module
may change accounts, provider keys, paper orders, research, balances or risk.
"""
import hashlib
import ipaddress
import json
import os
import re
import secrets
from datetime import timedelta, timezone
from pathlib import Path

import httpx
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pymongo.errors import DuplicateKeyError

from auth import digest, user_required
from core import Payload, audit, db, now, stamp, uid

load_dotenv(Path(__file__).parent / '.env.server')
vault = Fernet(os.environ['WEBHOOK_FERNET_KEY'].encode())
router = APIRouter(prefix='/api/server', tags=['Application connection details'])
public_router = APIRouter(prefix='/server', tags=['Public receiver'])
MAX_BYTES = 262144
RETENTION_DAYS = 30
TOKEN_PATTERN = re.compile(r'^[A-Za-z0-9_-]{64}$')


async def receiver_indexes():
    await db.webhook_endpoints.create_index('user_id', unique=True)
    await db.webhook_endpoints.create_index('token_hash', unique=True)
    await db.webhook_inbox.create_index([('user_id', 1), ('event_key', 1)], unique=True)
    await db.webhook_inbox.create_index([('user_id', 1), ('received_at', -1)])
    await db.webhook_inbox.create_index('expires_at', expireAfterSeconds=0)


def configured_ip(name):
    value = os.environ.get(name)
    if not value:
        return None
    try:
        parsed = ipaddress.ip_address(value)
        return str(parsed) if parsed.is_global else None
    except ValueError:
        return None


async def public_details(user_id):
    endpoint = await db.webhook_endpoints.find_one({'user_id': user_id}, {'_id': 0, 'created_at': 1})
    observation = await db.server_observations.find_one({'_id': 'outbound-ip'}, {'_id': 0})
    return {
        'app_name': 'EDGE INDIA Research', 'receiver_ready': bool(endpoint),
        'receiver_method': 'POST', 'receiver_format': 'application/json',
        'max_payload_bytes': MAX_BYTES, 'retention_days': RETENTION_DAYS,
        'primary_ip': configured_ip('SERVER_PRIMARY_EGRESS_IP'),
        'secondary_ip': configured_ip('SERVER_SECONDARY_EGRESS_IP'),
        'ip_configuration_status': 'OPERATOR_CONFIGURED_NOT_VERIFIED',
        'observation': observation,
        'scope': 'GENERIC_JSON_RECEIPTS_ONLY', 'broker_authentication': 'NOT_UNIVERSAL',
        'verification_status': 'UNVERIFIED', 'live_enabled': False,
        'description': 'Indian-market research and AI evaluation with paper trading. Generic JSON postbacks are stored as unverified receipts; real-money execution is disabled.',
    }


@router.get('/connection-details', response_model=Payload)
async def connection_details(user=Depends(user_required)):
    return await public_details(user['id'])


@router.post('/postback', response_model=Payload)
async def provision_postback(user=Depends(user_required)):
    """Idempotent authenticated provisioning/recovery, including CSRF validation."""
    token = secrets.token_urlsafe(48)
    try:
        await db.webhook_endpoints.update_one({'user_id': user['id']}, {'$setOnInsert': {
            '_id': uid(), 'user_id': user['id'], 'token_hash': digest(token),
            'token_ciphertext': vault.encrypt(token.encode()).decode(), 'created_at': stamp(),
        }}, upsert=True)
    except DuplicateKeyError:
        # Simultaneous first visits must recover the same already-created endpoint.
        pass
    row = await db.webhook_endpoints.find_one({'user_id': user['id']}, {'_id': 0})
    recovered = vault.decrypt(row['token_ciphertext'].encode()).decode()
    return {'receive_path': f'/server/receive/{recovered}', 'method': 'POST',
            'verification_status': 'UNVERIFIED', 'created_at': row['created_at']}


@router.post('/postback/rotate', response_model=Payload)
async def rotate_postback(user=Depends(user_required)):
    token = secrets.token_urlsafe(48)
    result = await db.webhook_endpoints.update_one({'user_id': user['id']}, {'$set': {
        'token_hash': digest(token), 'token_ciphertext': vault.encrypt(token.encode()).decode(),
        'rotated_at': stamp(),
    }})
    if not result.matched_count:
        raise HTTPException(409, 'Create the receiver before rotating it.')
    await audit(user['id'], 'postback_url_rotated', {'old_url': 'REVOKED'})
    return {'receive_path': f'/server/receive/{token}', 'method': 'POST', 'old_url_revoked': True}


@router.get('/events', response_model=Payload)
async def recent_events(user=Depends(user_required)):
    rows = await db.webhook_inbox.find({'user_id': user['id'], 'expires_at': {'$gt': now()}}, {
        '_id': 0, 'id': 1, 'received_at': 1, 'size_bytes': 1,
        'payload_type': 1, 'verification_status': 1, 'kind': 1,
    }).sort('received_at', -1).to_list(12)
    return {'events': rows, 'retention_days': RETENTION_DAYS}


@public_router.get('/receive/{token}', response_model=Payload)
async def receiver_health(token: str):
    # This is not an OAuth callback or a token-validity oracle. No data/query storage.
    return {'status': 'RECEIVER_ONLINE', 'method': 'POST', 'content_type': 'application/json',
            'message': 'Health check only. This endpoint does not complete broker authorization.'}


def reject_constant(_):
    raise ValueError('Non-finite JSON number')


@public_router.post('/receive/{token}', status_code=202, response_model=Payload)
async def receive_json(token: str, request: Request, response: Response):
    if not TOKEN_PATTERN.fullmatch(token):
        raise HTTPException(404, 'Receiver not found.')
    endpoint = await db.webhook_endpoints.find_one({'token_hash': digest(token)}, {'_id': 0, 'user_id': 1})
    if not endpoint:
        raise HTTPException(404, 'Receiver not found.')
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'Send application/json: an object or an array.')
    declared = request.headers.get('content-length')
    if declared is not None:
        try:
            size = int(declared)
        except ValueError:
            raise HTTPException(400, 'Invalid content length.') from None
        if size < 0:
            raise HTTPException(400, 'Invalid content length.')
        if size > MAX_BYTES:
            raise HTTPException(413, 'Postback exceeds the 256 KiB limit.')
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, 'Postback exceeds the 256 KiB limit.')
        raw.extend(chunk)
    try:
        payload = json.loads(raw, parse_constant=reject_constant)
        if not isinstance(payload, (dict, list)):
            raise ValueError('Object or array required')
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, RecursionError):
        raise HTTPException(400, 'Valid JSON object or array required.') from None
    event_key = hashlib.sha256(canonical).hexdigest()
    event_id = uid()
    record = {
        '_id': event_id, 'id': event_id, 'user_id': endpoint['user_id'], 'event_key': event_key,
        'received_at': stamp(), 'expires_at': now() + timedelta(days=RETENTION_DAYS),
        'verification_status': 'UNVERIFIED', 'size_bytes': len(raw),
        'payload_type': 'object' if isinstance(payload, dict) else 'array',
        'kind': 'SELF_LABELLED_TEST' if isinstance(payload, dict) and payload.get('type') == 'application_self_test' else 'INBOUND_RECEIPT',
        'payload_ciphertext': vault.encrypt(bytes(raw)).decode(),
    }
    try:
        await db.webhook_inbox.insert_one(record)
    except DuplicateKeyError:
        response.status_code = 200
        return {'accepted': True, 'duplicate': True, 'verification_status': 'UNVERIFIED'}
    return {'accepted': True, 'duplicate': False, 'receipt_id': event_id,
            'verification_status': 'UNVERIFIED'}


@router.post('/observe-egress', response_model=Payload)
async def observe_egress(user=Depends(user_required)):
    """On-demand observation, never IP reservation or broker verification."""
    cached = await db.server_observations.find_one({'_id': 'outbound-ip'}, {'_id': 0})
    if cached and cached['observed_at'].replace(tzinfo=timezone.utc) > now() - timedelta(seconds=60):
        return {'observation': cached, 'cached': True}
    url = os.environ.get('IPIFY_URL') or os.environ.get('AWS_CHECKIP_URL')
    if not url or not url.startswith('https://'):
        raise HTTPException(503, 'Outbound IP observation is not configured.')
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            result = await client.get(url)
            result.raise_for_status()
            if len(result.content) > 1024:
                raise ValueError('Unexpected observation response')
            if result.headers.get('content-type', '').startswith('application/json'):
                observed = result.json().get('ip', '')
            else:
                observed = result.text.strip()
            parsed = ipaddress.ip_address(observed)
            if not parsed.is_global:
                raise ValueError('Not a public IP')
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(502, 'Could not observe outbound IP. No static address has been inferred; try again.') from None
    record = {'ip': str(parsed), 'observed_at': now(), 'status': 'OBSERVED_NOT_RESERVED',
              'source': 'configured_observation_endpoint'}
    await db.server_observations.update_one({'_id': 'outbound-ip'}, {'$set': record}, upsert=True)
    return {'observation': record, 'cached': False}
