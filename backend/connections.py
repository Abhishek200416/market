import json
import os
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from auth import user_required
from core import db, stamp, audit, Payload
from providers import FyersBrokerProvider
from upstox import UpstoxMarketDataProvider

router = APIRouter(prefix='/api/connections')
vault = Fernet(os.environ['ENCRYPTION_KEY'].encode())
FIELDS = {'upstox': ['api_key', 'api_secret', 'access_token'], 'gemini': ['api_key'], 'fyers': ['client_id', 'access_token', 'secret']}

class ConnectionInput(BaseModel):
    values: dict[str, str] = Field(max_length=5)

async def credentials(user_id, provider):
    row = await db.credentials.find_one({'user_id': user_id, 'provider': provider}, {'_id': 0})
    if not row:
        raise HTTPException(409, f'{provider.upper()} disconnected. Add credentials in API Connections.')
    return json.loads(vault.decrypt(row['encrypted'].encode()))

async def statuses(user_id):
    rows = await db.credentials.find({'user_id': user_id}, {'_id': 0, 'encrypted': 0, 'user_id': 0}).to_list(10) if user_id else []
    return [{**{'provider': p, 'status': 'DISCONNECTED', 'configured_fields': [], 'last_success': None,
                'error': None, 'last_test': None}, **next((r for r in rows if r['provider'] == p), {})} for p in FIELDS]

@router.get('', response_model=Payload)
async def list_connections(user=Depends(user_required)):
    return {'connections': await statuses(user['id'])}

@router.put('/{provider}', response_model=Payload)
async def save(provider: str, data: ConnectionInput, user=Depends(user_required)):
    if provider not in FIELDS or set(data.values) - set(FIELDS[provider]):
        raise HTTPException(422, 'Unsupported provider or credential field.')
    values = {k: v.strip() for k, v in data.values.items() if v.strip()}
    if any(len(v) > 8192 for v in values.values()):
        raise HTTPException(422, 'Credential value too long.')
    existing = await db.credentials.find_one({'user_id': user['id'], 'provider': provider}, {'_id': 0})
    merged = json.loads(vault.decrypt(existing['encrypted'].encode())) if existing else {}
    merged.update(values)
    required = (['access_token'] if merged.get('access_token') else ['api_key', 'api_secret']) if provider == 'upstox' else (['client_id', 'access_token'] if provider == 'fyers' else ['api_key'])
    if any(not merged.get(k) for k in required):
        raise HTTPException(422, 'Complete the required credential fields.')
    await db.credentials.update_one({'user_id': user['id'], 'provider': provider}, {'$set': {
        'encrypted': vault.encrypt(json.dumps(merged).encode()).decode(), 'configured_fields': list(merged),
        'status': 'UNTESTED', 'updated_at': stamp(), 'last_success': None, 'last_test': None, 'error': None}}, upsert=True)
    await audit(user['id'], 'credentials_saved', {'provider': provider})
    if provider in ('upstox', 'fyers'):
        await db.quotes.delete_many({'user_id': user['id'], 'provider': provider.upper()})
    return {'connections': await statuses(user['id'])}

@router.post('/{provider}/test', response_model=Payload)
async def test(provider: str, user=Depends(user_required)):
    if provider not in FIELDS:
        raise HTTPException(404, 'Unknown provider.')
    values = await credentials(user['id'], provider)
    error = None
    try:
        if provider == 'upstox':
            quote = await UpstoxMarketDataProvider(values).quote('NSE:NIFTY50-INDEX')
            if quote.get('ltp') is None or quote['ltp'] <= 0:
                raise ValueError('No quote')
        elif provider == 'fyers':
            await FyersBrokerProvider(values).get_account()
        else:
            from tradingagents.llm_clients.google_client import GoogleClient
            llm = GoogleClient(os.environ['GEMINI_QUICK_MODEL'], api_key=values['api_key'], timeout=15, max_retries=0, max_output_tokens=32).get_llm()
            response = await llm.ainvoke('Reply only OK. This is a connection test, not market analysis.')
            await db.llm_usage.insert_one({'user_id': user['id'], 'timestamp': stamp(), 'purpose': 'connection_test',
                'model': os.environ['GEMINI_QUICK_MODEL'], 'tokens': (response.usage_metadata or {}).get('total_tokens'), 'estimated_cost': None})
    except Exception:
        error = f'{provider.upper()} test failed. Check credentials, quota, model access and network connectivity.'
    fields = {'status': 'ERROR' if error else 'CONNECTED', 'error': error, 'last_test': stamp()}
    if not error:
        fields['last_success'] = stamp()
    await db.credentials.update_one({'user_id': user['id'], 'provider': provider}, {'$set': fields})
    await audit(user['id'], 'connection_test', {'provider': provider, 'success': not error})
    return {'ok': not error, 'connections': await statuses(user['id'])}

@router.delete('/{provider}', response_model=Payload)
async def disconnect(provider: str, user=Depends(user_required)):
    await db.credentials.delete_one({'user_id': user['id'], 'provider': provider})
    if provider in ('upstox', 'fyers'):
        await db.quotes.delete_many({'user_id': user['id'], 'provider': provider.upper()})
    if provider == 'upstox':
        await db.oauth_states.delete_many({'user_id': user['id']})
    await audit(user['id'], 'provider_disconnected', {'provider': provider})
    return {'connections': await statuses(user['id'])}