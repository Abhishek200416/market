from fastapi import APIRouter, Depends, HTTPException, Query
from auth import user_required
from connections import credentials
from providers import FyersMarketDataProvider
from core import db, now, audit, Payload
from quality import assess_quote
from market_routing import market_provider, selected_provider

router = APIRouter(prefix='/api/markets')
INSTRUMENTS = [
    {'symbol': 'NSE:NIFTY50-INDEX', 'name': 'NIFTY 50', 'type': 'INDEX', 'sector': 'Broad market'},
    {'symbol': 'NSE:NIFTYBANK-INDEX', 'name': 'BANK NIFTY', 'type': 'INDEX', 'sector': 'Banking'},
    {'symbol': 'NSE:RELIANCE-EQ', 'name': 'RELIANCE', 'type': 'EQUITY', 'sector': 'Energy'},
    {'symbol': 'NSE:HDFCBANK-EQ', 'name': 'HDFC BANK', 'type': 'EQUITY', 'sector': 'Banking'},
    {'symbol': 'NSE:ICICIBANK-EQ', 'name': 'ICICI BANK', 'type': 'EQUITY', 'sector': 'Banking'},
    {'symbol': 'NSE:INFY-EQ', 'name': 'INFOSYS', 'type': 'EQUITY', 'sector': 'Technology'},
    {'symbol': 'NSE:TCS-EQ', 'name': 'TCS', 'type': 'EQUITY', 'sector': 'Technology'},
    {'symbol': 'NSE:SBIN-EQ', 'name': 'SBI', 'type': 'EQUITY', 'sector': 'Banking'},
]
def instrument(symbol):
    found = next((x for x in INSTRUMENTS if x['symbol'] == symbol), None)
    if not found:
        raise HTTPException(422, 'Select a supported instrument.')
    return found

async def get_quote(user_id, symbol):
    instrument(symbol)
    name = await selected_provider(user_id)
    provider = await market_provider(user_id, name)
    quote = await provider.quote(symbol)
    if name != await selected_provider(user_id):
        raise HTTPException(409, 'Market provider changed during the request. Refresh again.')
    previous = await db.quotes.find_one({'user_id': user_id, 'symbol': symbol}, {'_id': 0})
    quote['freshness'] = assess_quote(quote, previous if previous and previous.get('provider') == quote['provider'] else None)
    if quote['freshness'] in ('ANOMALY', 'OUT_OF_ORDER', 'DUPLICATE'):
        await audit(user_id, 'data_quality_block', {'symbol': symbol, 'status': quote['freshness']})
    await db.quotes.update_one({'user_id': user_id, 'symbol': symbol}, {'$set': quote}, upsert=True)
    return quote

@router.get('/instruments', response_model=Payload)
async def instruments():
    return {'instruments': INSTRUMENTS}

@router.get('/quote', response_model=Payload)
async def quote(symbol: str, user=Depends(user_required)):
    return {'quote': await get_quote(user['id'], symbol)}

@router.get('/candles', response_model=Payload)
async def candles(symbol: str, resolution: str = Query(default='5', pattern='^(1|5|15|30|60|D)$'), user=Depends(user_required)):
    instrument(symbol)
    provider = await market_provider(user['id'])
    end = int(now().timestamp())
    lookback = 365 if resolution == 'D' else 5
    rows = await provider.candles(symbol, resolution, end - lookback * 86400, end)
    return {'candles': rows, 'symbol': symbol, 'resolution': resolution, 'provider': provider.name, 'transport': 'REST polling'}