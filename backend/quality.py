import math
from datetime import datetime, timezone
from fastapi import HTTPException
from core import stamp, now

def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None

def source_time(value):
    try:
        if not value:
            return None
        numeric = float(value)
        return datetime.fromtimestamp(numeric / 1000 if numeric > 1e12 else numeric, timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None

def normalize_quote(symbol, raw):
    source = source_time(raw.get('tt') or raw.get('last_traded_time'))
    received = now()
    age = (received - source).total_seconds() if source else None
    freshness = 'UNKNOWN' if age is None else ('ANOMALY' if age < -2 else ('FRESH' if age <= 15 else 'STALE'))
    return {'symbol': symbol, 'timestamp': source.isoformat() if source else None,
        'provider': 'FYERS', 'source_timestamp': source.isoformat() if source else None,
        'received_timestamp': received.isoformat(), 'latency': round(age * 1000, 1) if age is not None else None,
        'freshness': freshness, 'sequence': raw.get('sequence'), 'ltp': number(raw.get('lp', raw.get('ltp'))),
        'bid': number(raw.get('bid')), 'ask': number(raw.get('ask')),
        'bid_size': number(raw.get('bid_size')), 'ask_size': number(raw.get('ask_size')),
        'volume': number(raw.get('volume', raw.get('vol_traded_today'))),
        'change': number(raw.get('ch')), 'change_pct': number(raw.get('chp'))}

def assess_quote(quote, previous=None):
    if not quote or not quote.get('source_timestamp'):
        return 'UNKNOWN'
    try:
        source = datetime.fromisoformat(quote['source_timestamp'])
        if source.tzinfo is None:
            return 'ANOMALY'
    except (TypeError, ValueError):
        return 'ANOMALY'
    age = (now() - source).total_seconds()
    if age < -2 or not quote.get('ltp') or quote['ltp'] <= 0:
        return 'ANOMALY'
    if previous and previous.get('source_timestamp'):
        if source < datetime.fromisoformat(previous['source_timestamp']):
            return 'OUT_OF_ORDER'
        if quote.get('sequence') is not None and quote['sequence'] == previous.get('sequence'):
            return 'DUPLICATE'
    return 'FRESH' if age <= 15 else 'STALE'

def require_fresh(quote):
    status = assess_quote(quote)
    if status != 'FRESH' or quote.get('freshness') in ('OUT_OF_ORDER', 'ANOMALY', 'DUPLICATE'):
        raise HTTPException(409, f'DATA {status if status != "FRESH" else quote["freshness"]} — trading and signal generation blocked.')

def normalize_candles(symbol, rows, resolution, cutoff):
    duration = 86400 if resolution == 'D' else int(resolution) * 60
    result, seen = [], set()
    for row in rows:
        if len(row) < 6:
            raise HTTPException(502, 'Incomplete OHLCV candle.')
        ts, o, h, l, c, v = [number(x) for x in row[:6]]
        if None in (ts, o, h, l, c, v) or min(o, h, l, c) <= 0 or v < 0 or h < max(o, c, l) or l > min(o, c, h):
            raise HTTPException(502, 'Invalid OHLCV candle. Data rejected.')
        if ts in seen:
            raise HTTPException(502, 'Duplicate candle timestamp. Data rejected.')
        seen.add(ts)
        if ts + duration > cutoff:
            continue
        try:
            iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            raise HTTPException(502, 'Invalid candle timestamp.')
        result.append({'symbol': symbol, 'timestamp': iso, 'time': int(ts), 'open': o, 'high': h,
            'low': l, 'close': c, 'volume': v, 'provider': 'FYERS', 'source_timestamp': iso,
            'received_timestamp': stamp(), 'latency': None, 'freshness': 'HISTORICAL', 'sequence': None})
    return sorted(result, key=lambda c: c['time'])