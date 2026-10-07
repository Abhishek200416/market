from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, ConfigDict
from fastapi import HTTPException
from core import now
from quality import require_fresh

IST = ZoneInfo('Asia/Kolkata')

class RiskSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    risk_per_trade: float = Field(default=0.5, gt=0, le=2)
    daily_loss_limit: float = Field(default=2, gt=0, le=10)
    max_consecutive_losses: int = Field(default=3, ge=1, le=10)
    max_trades_day: int = Field(default=10, ge=1, le=50)
    cooldown_seconds: int = Field(default=60, ge=30, le=3600)
    max_exposure: float = Field(default=30, gt=0, le=100)
    max_position: float = Field(default=10, gt=0, le=25)
    min_risk_reward: float = Field(default=2, ge=1, le=10)
    min_volume: int = Field(default=1000, ge=1000)
    max_spread_bps: float = Field(default=25, gt=0, le=100)

def trading_day(timestamp):
    return datetime.fromisoformat(timestamp).astimezone(IST).date()

def daily_stats(account):
    today = now().astimezone(IST).date()
    trades = [t for t in account['trades'] if trading_day(t['timestamp']) == today]
    orders = [o for o in account['orders'] if o['side'] == 'BUY' and trading_day(o['timestamp']) == today]
    streak = 0
    for t in reversed(trades):
        if t['pnl'] >= 0:
            break
        streak += 1
    return {'pnl': sum(t['pnl'] for t in trades), 'count': len(orders), 'loss_streak': streak}

def validate_order(account, quote, quantity, stop, target, fill, fees):
    require_fresh(quote)
    r, stats = account['risk'], daily_stats(account)
    reasons = []
    if account['kill_switch']:
        reasons.append('Kill switch engaged')
    if not stop < fill < target:
        reasons.append('A long order requires stop < fill price < target')
    risk = max(0, fill - stop) * quantity + fees
    if risk > account['starting_capital'] * r['risk_per_trade'] / 100:
        reasons.append('Maximum risk per trade exceeded')
    if fill > stop and (target - fill) / (fill - stop) < r['min_risk_reward']:
        reasons.append('Minimum risk/reward not met after slippage')
    if stats['pnl'] + account.get('open_pnl_for_risk', 0) <= -account['starting_capital'] * r['daily_loss_limit'] / 100:
        reasons.append('Daily loss lock active')
    if stats['loss_streak'] >= r['max_consecutive_losses']:
        reasons.append('Loss-streak cooldown active until next trading day')
    if stats['count'] >= r['max_trades_day']:
        reasons.append('Maximum trades per day reached')
    if account['orders'] and (now() - datetime.fromisoformat(account['orders'][-1]['timestamp'])).total_seconds() < r['cooldown_seconds']:
        reasons.append('Trade cooldown active')
    if any(p['symbol'] == quote['symbol'] for p in account['positions']):
        reasons.append('Duplicate position blocked')
    cost = fill * quantity + fees
    exposure = sum(p['quantity'] * p['entry'] for p in account['positions'])
    if cost > account['cash']:
        reasons.append('Insufficient paper cash')
    if cost > account['starting_capital'] * r['max_position'] / 100:
        reasons.append('Maximum position size exceeded')
    if exposure + cost > account['starting_capital'] * r['max_exposure'] / 100:
        reasons.append('Maximum total exposure exceeded')
    if quote.get('volume') is None or quote['volume'] < r['min_volume']:
        reasons.append('Insufficient or unknown liquidity')
    bid, ask = quote.get('bid'), quote.get('ask')
    if not bid or not ask or bid <= 0 or ask < bid:
        reasons.append('Valid bid/ask spread is required')
    elif (ask - bid) / quote['ltp'] * 10000 > r['max_spread_bps']:
        reasons.append('Spread limit exceeded')
    if reasons:
        raise HTTPException(409, 'NO TRADE — ' + '; '.join(reasons))
    return {'risk_amount': round(risk, 2), 'risk_reward': round((target - fill) / (fill - stop), 2)}