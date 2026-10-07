"""Deterministic CPU-only features from validated completed candles."""
import math
import pandas as pd
from stockstats import wrap

INDICATORS = {'close_10_ema': 10, 'close_50_sma': 50, 'close_200_sma': 200,
    'rsi': 15, 'macd': 26, 'macds': 35, 'macdh': 35, 'atr': 15,
    'boll': 20, 'boll_ub': 20, 'boll_lb': 20, 'vwma': 20}

def indicators(candles):
    if not candles:
        return {}
    frame = wrap(pd.DataFrame(candles)[['open', 'high', 'low', 'close', 'volume']].copy())
    result = {}
    for name, required in INDICATORS.items():
        if len(frame) < required:
            result[name] = None
            continue
        try:
            value = float(frame[name].iloc[-1])
            result[name] = round(value, 5) if math.isfinite(value) else None
        except (KeyError, ValueError, ZeroDivisionError):
            result[name] = None
    volume = frame['volume'].sum()
    result['vwap_window'] = round(float((((frame['high'] + frame['low'] + frame['close']) / 3) * frame['volume']).sum() / volume), 5) if volume > 0 else None
    return result