"""Read-only Upstox market data. No order or account/portfolio API calls.

Analytics-token quotes/history can be tested without sending credentials to
profile APIs which may have different static-IP requirements.
"""
import asyncio
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote as encode_path
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException
from core import now, stamp
from quality import normalize_candles, number, assess_quote

IST = ZoneInfo('Asia/Kolkata')
RESOLUTIONS = {'1': ('minutes', '1'), '5': ('minutes', '5'), '15': ('minutes', '15'),
               '30': ('minutes', '30'), '60': ('minutes', '60'), 'D': ('days', '1')}
_catalog = {}
_catalog_date = None
_catalog_lock = asyncio.Lock()

def parse_timestamp(value):
    if value is None or value == '':
        return None
    try:
        numeric = float(value)
        return datetime.fromtimestamp(numeric / 1000 if numeric > 1e12 else numeric, timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
        except (ValueError, TypeError):
            return None

def resolve_from_catalog(symbol, rows):
    clean = lambda value: ''.join(c for c in str(value).upper() if c.isalnum())
    indices = {'NSE:NIFTY50-INDEX': 'NIFTY50', 'NSE:NIFTYBANK-INDEX': 'NIFTYBANK'}
    if symbol in indices:
        matches = [r for r in rows if r.get('segment') == 'NSE_INDEX' and clean(r.get('name')) == indices[symbol]]
    elif symbol.startswith('NSE:') and symbol.endswith('-EQ'):
        ticker = symbol[4:-3]
        matches = [r for r in rows if r.get('segment') == 'NSE_EQ' and r.get('instrument_type') == 'EQ'
                   and r.get('trading_symbol') == ticker]
    else:
        matches = []
    if len(matches) != 1 or not matches[0].get('instrument_key'):
        raise HTTPException(409, 'Upstox instrument could not be uniquely resolved from its official catalogue.')
    row = matches[0]
    return {k: row.get(k) for k in ('instrument_key', 'trading_symbol', 'name', 'segment', 'instrument_type')}

async def resolve_instrument(symbol):
    global _catalog_date, _catalog
    today = now().astimezone(IST).date()
    async with _catalog_lock:
        if _catalog_date != today:
            try:
                async with httpx.AsyncClient(timeout=25) as client:
                    response = await client.get(os.environ['UPSTOX_INSTRUMENTS_URL'])
                response.raise_for_status()
                body = response.content
                rows = json.loads(gzip.decompress(body) if body[:2] == b'\x1f\x8b' else body)
                if not isinstance(rows, list):
                    raise ValueError('Invalid catalogue')
                _catalog = [r for r in rows if r.get('segment') in ('NSE_EQ', 'NSE_INDEX')]
                _catalog_date = today
            except (httpx.HTTPError, ValueError, OSError):
                raise HTTPException(503, 'Official Upstox instrument catalogue unavailable. No guessed instrument IDs used.')
        return resolve_from_catalog(symbol, _catalog)

def normalize_upstox_quote(symbol, row):
    source = parse_timestamp(row.get('timestamp'))
    received = now()
    depth = row.get('depth') or {}
    buys, sells = depth.get('buy') or [], depth.get('sell') or []
    buy, sell = (buys[0] if buys else {}), (sells[0] if sells else {})
    last_trade = parse_timestamp(row.get('last_trade_time'))
    ltp, change = number(row.get('last_price')), number(row.get('net_change'))
    prior_close = ltp - change if ltp is not None and change is not None else None
    result = {'symbol': symbol, 'instrument_key': row.get('instrument_token'), 'provider': 'UPSTOX',
        'timestamp': source.isoformat() if source else None, 'source_timestamp': source.isoformat() if source else None,
        'received_timestamp': received.isoformat(), 'last_trade_timestamp': last_trade.isoformat() if last_trade else None,
        'latency': round((received-source).total_seconds()*1000, 1) if source else None,
        'sequence': None, 'ltp': ltp, 'bid': number(buy.get('price')), 'ask': number(sell.get('price')),
        'bid_size': number(buy.get('quantity')), 'ask_size': number(sell.get('quantity')),
        'volume': number(row.get('volume')), 'change': change,
        'change_pct': round(change/prior_close*100, 3) if prior_close and change is not None else None}
    result['freshness'] = assess_quote(result)
    return result

def normalize_upstox_candles(symbol, rows, resolution, cutoff):
    converted = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise HTTPException(502, 'Incomplete Upstox candle rejected.')
        source = parse_timestamp(row[0])
        if not source:
            raise HTTPException(502, 'Invalid Upstox candle timestamp rejected.')
        converted.append([source.timestamp(), *row[1:6]])
    return [{**c, 'provider': 'UPSTOX'} for c in normalize_candles(symbol, converted, resolution, cutoff)]

class UpstoxMarketDataProvider:
    name = 'UPSTOX'

    def __init__(self, credentials):
        token = credentials.get('access_token')
        if not token:
            raise HTTPException(409, 'UPSTOX disconnected. Save an Analytics/access token or complete broker sign-in.')
        self.headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

    async def request(self, path, params=None):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(os.environ['UPSTOX_BASE_URL'] + path, headers=self.headers, params=params)
            if response.status_code in (401, 403):
                raise HTTPException(502, 'Upstox token rejected or permission missing. Renew the token and check API access.')
            if response.status_code == 429:
                raise HTTPException(429, 'Upstox rate limit reached. Wait before refreshing.')
            response.raise_for_status()
            data = response.json()
            if data.get('status') != 'success':
                raise HTTPException(502, 'Upstox rejected the read-only request. Check instrument and token permissions.')
            return data.get('data') or {}
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Upstox market data unavailable. No prices substituted.')

    async def quote(self, symbol):
        info = await resolve_instrument(symbol)
        payload = await self.request('/v2/market-quote/quotes', {'instrument_key': info['instrument_key']})
        matches = [row for row in payload.values() if isinstance(row, dict) and row.get('instrument_token') == info['instrument_key']]
        if len(matches) != 1:
            raise HTTPException(502, 'Upstox returned no unambiguous quote for the requested instrument.')
        return normalize_upstox_quote(symbol, matches[0])

    async def candles(self, symbol, resolution, start, end):
        if resolution not in RESOLUTIONS:
            raise HTTPException(422, 'Unsupported candle interval.')
        info = await resolve_instrument(symbol)
        key = encode_path(info['instrument_key'], safe='')
        unit, interval = RESOLUTIONS[resolution]
        today = now().astimezone(IST).date()
        start_date = datetime.fromtimestamp(start, IST).date()
        end_date = datetime.fromtimestamp(end, IST).date()
        historical_end = min(end_date, today-timedelta(days=1))
        rows = []
        if start_date <= historical_end:
            historical = await self.request(f'/v3/historical-candle/{key}/{unit}/{interval}/{historical_end.isoformat()}/{start_date.isoformat()}')
            rows.extend(historical.get('candles') or [])
        if resolution != 'D' and start_date <= today <= end_date:
            intraday = await self.request(f'/v3/historical-candle/intraday/{key}/{unit}/{interval}')
            rows.extend(intraday.get('candles') or [])
        # Fail on duplicate observations rather than quietly pick one.
        result = normalize_upstox_candles(symbol, rows, resolution, min(end, int(now().timestamp())))
        return [c for c in result if c['time'] >= start]