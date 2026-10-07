"""Explicit per-account provider selection. Never silently mix vendor sources."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import user_required
from core import db, audit, Payload
from connections import credentials
from providers import FyersMarketDataProvider
from upstox import UpstoxMarketDataProvider

router = APIRouter(prefix='/api/market-provider')
PROVIDERS = {'upstox': UpstoxMarketDataProvider, 'fyers': FyersMarketDataProvider}

class Selection(BaseModel):
    provider: Literal['upstox', 'fyers']

async def selected_provider(user_id):
    account = await db.accounts.find_one({'user_id': user_id}, {'_id': 0, 'market_provider': 1})
    if account is None:
        raise HTTPException(503, 'Paper account unavailable. Data routing disabled.')
    return account.get('market_provider', 'upstox')

async def market_provider(user_id, provider_name=None):
    name = provider_name or await selected_provider(user_id)
    if name not in PROVIDERS:
        raise HTTPException(409, 'Select an available market-data provider.')
    return PROVIDERS[name](await credentials(user_id, name))

@router.put('', response_model=Payload)
async def select_provider(data: Selection, user=Depends(user_required)):
    from paper import account_for, persist
    account = await account_for(user['id'])
    if account['positions']:
        raise HTTPException(409, 'Close existing paper positions before changing the market-data provider.')
    account['market_provider'] = data.provider
    await persist(account, account['version'])
    await db.quotes.delete_many({'user_id': user['id']})
    await audit(user['id'], 'market_provider_selected', {'provider': data.provider})
    return {'market_provider': data.provider, 'automatic_fallback': False}