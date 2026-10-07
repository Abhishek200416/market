import copy
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from auth import user_required
from core import db, stamp, uid, audit, Payload
from markets import get_quote, instrument
from risk import RiskSettings, validate_order, daily_stats
from quality import require_fresh, assess_quote

router = APIRouter(prefix='/api/paper')

class OrderInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    symbol: str
    quantity: int = Field(gt=0, le=100000)
    stop: float = Field(gt=0)
    target: float = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=100)

class KillInput(BaseModel):
    enabled: bool

async def account_for(user_id):
    account = await db.accounts.find_one({'user_id': user_id}, {'_id': 0})
    if not account:
        raise HTTPException(503, 'Paper account unavailable. Trading disabled.')
    return account

async def persist(account, old_version):
    account['version'] = old_version + 1
    result = await db.accounts.replace_one({'user_id': account['user_id'], 'version': old_version}, account.copy())
    if result.modified_count != 1:
        raise HTTPException(409, 'Account changed concurrently. Refresh before trying again.')

def costs(turnover, sell=False):
    # Explicit equity-intraday assumptions, not a broker invoice: brokerage cap,
    # exchange, SEBI, GST, stamp duty on buy, STT on sell; see README.
    brokerage = min(20, turnover * .0003)
    exchange = turnover * .0000297
    sebi = turnover * .000001
    gst = (brokerage + exchange + sebi) * .18
    stamp_duty = 0 if sell else turnover * .00003
    stt = turnover * .00025 if sell else 0
    return round(brokerage + exchange + sebi + gst + stamp_duty + stt, 2)

async def account_summary(account):
    positions, unrealized, marked_value = [], 0.0, 0.0
    fully_marked = True
    for position in account['positions']:
        quote = await db.quotes.find_one({'user_id': account['user_id'], 'symbol': position['symbol']}, {'_id': 0})
        fresh = quote and assess_quote(quote) == 'FRESH'
        mark = quote['ltp'] if fresh else None
        pnl = round((mark - position['entry']) * position['quantity'] - position['entry_fees'], 2) if mark is not None else None
        positions.append({**position, 'mark': mark, 'unrealized_pnl': pnl, 'freshness': assess_quote(quote)})
        fully_marked = fully_marked and bool(fresh)
        if fresh:
            unrealized += pnl
            marked_value += mark * position['quantity']
    equity = round(account['cash'] + marked_value, 2) if fully_marked else None
    return {**account, 'positions': positions, 'equity': equity,
        'unrealized_pnl': round(unrealized, 2) if fully_marked else None,
        'drawdown': round(max(0, (account['peak_equity'] - equity) / account['peak_equity'] * 100), 3) if equity is not None else None,
        'daily': daily_stats(account), 'execution_mode': 'PAPER', 'live_enabled': False}

@router.get('', response_model=Payload)
async def account(user=Depends(user_required)):
    return {'account': await account_summary(await account_for(user['id']))}

@router.put('/risk', response_model=Payload)
async def risk(data: RiskSettings, user=Depends(user_required)):
    account = await account_for(user['id'])
    stats = daily_stats(account)
    locked = stats['pnl'] <= -account['starting_capital'] * account['risk']['daily_loss_limit'] / 100
    if locked and data.daily_loss_limit > account['risk']['daily_loss_limit']:
        raise HTTPException(409, 'Daily loss lock active. Its threshold cannot be relaxed until the next trading day.')
    if stats['loss_streak'] >= account['risk']['max_consecutive_losses'] and data.max_consecutive_losses > account['risk']['max_consecutive_losses']:
        raise HTTPException(409, 'Loss-streak lock active. Its threshold cannot be relaxed until the next trading day.')
    # Tightening existing limits is safe; changes cannot clear daily locks/history.
    account['risk'] = data.model_dump()
    await persist(account, account['version'])
    await audit(user['id'], 'risk_updated', data.model_dump())
    return {'risk': account['risk']}

@router.post('/kill-switch', response_model=Payload)
async def kill(data: KillInput, user=Depends(user_required)):
    account = await account_for(user['id'])
    account['kill_switch'] = data.enabled
    await persist(account, account['version'])
    await audit(user['id'], 'kill_switch', {'enabled': data.enabled})
    return {'enabled': data.enabled}

@router.post('/orders', response_model=Payload)
async def buy(data: OrderInput, user=Depends(user_required)):
    account = await account_for(user['id'])
    previous = next((o for o in account['orders'] if o.get('idempotency_key') == data.idempotency_key), None)
    if previous:
        if previous['symbol'] != data.symbol or previous['quantity'] != data.quantity:
            raise HTTPException(409, 'Idempotency key already belongs to a different order.')
        return {'order': previous, 'idempotent': True}
    if account['kill_switch']:
        raise HTTPException(409, 'Kill switch engaged. New paper orders are blocked.')
    if instrument(data.symbol)['type'] != 'EQUITY':
        raise HTTPException(409, 'Indices are research-only. Choose a supported liquid equity for paper execution.')
    if len(account['orders']) >= 10000:
        raise HTTPException(409, 'Account archive required before more orders.')
    quote = await get_quote(user['id'], data.symbol)
    require_fresh(quote)
    open_pnl = 0.0
    for existing in account['positions']:
        mark = quote if existing['symbol'] == data.symbol else await get_quote(user['id'], existing['symbol'])
        require_fresh(mark)
        open_pnl += (mark['ltp'] - existing['entry']) * existing['quantity'] - existing['entry_fees']
    risk_account = {**account, 'open_pnl_for_risk': open_pnl}
    fill = round((quote.get('ask') or quote['ltp']) * 1.0005, 2)
    fees = costs(fill * data.quantity)
    try:
        evaluation = validate_order(risk_account, quote, data.quantity, data.stop, data.target, fill, fees)
    except HTTPException as error:
        await audit(user['id'], 'order_blocked', {'reason': error.detail, 'symbol': data.symbol})
        raise
    order = {'id': uid(), 'symbol': data.symbol, 'quantity': data.quantity, 'side': 'BUY', 'fill': fill,
        'fees': fees, 'slippage_bps': 5, 'timestamp': stamp(), 'status': 'FILLED', 'mode': 'PAPER',
        'idempotency_key': data.idempotency_key, 'provider': quote.get('provider'), 'quote_timestamp': quote['source_timestamp'], **evaluation}
    position = {'id': uid(), 'symbol': data.symbol, 'quantity': data.quantity, 'entry': fill, 'entry_fees': fees,
        'stop': data.stop, 'target': data.target, 'provider': quote.get('provider'), 'opened_at': order['timestamp']}
    account['cash'] = round(account['cash'] - fill * data.quantity - fees, 2)
    account['fees_paid'] += fees
    account['orders'].append(order)
    account['positions'].append(position)
    # Re-check at commit time: a quote fetched before several marks may have expired.
    require_fresh(quote)
    await persist(account, account['version'])
    await audit(user['id'], 'paper_fill', {'order_id': order['id']})
    return {'order': order}

async def close_position(user_id, position_id, quote=None, reason='MANUAL'):
    account = await account_for(user_id)
    position = next((p for p in account['positions'] if p['id'] == position_id), None)
    if not position:
        raise HTTPException(404, 'Open position not found.')
    quote = quote or await get_quote(user_id, position['symbol'])
    require_fresh(quote)
    if quote['symbol'] != position['symbol']:
        raise HTTPException(409, 'Quote instrument does not match position.')
    if position.get('provider') and position['provider'] != quote.get('provider'):
        raise HTTPException(409, 'Quote provider does not match the original position.')
    if not quote.get('bid') or quote['bid'] <= 0:
        raise HTTPException(409, 'Valid bid required for closing fill.')
    fill = round(quote['bid'] * .9995, 2)
    fees = costs(fill * position['quantity'], sell=True)
    pnl = round((fill - position['entry']) * position['quantity'] - fees - position['entry_fees'], 2)
    order = {'id': uid(), 'symbol': position['symbol'], 'quantity': position['quantity'], 'side': 'SELL',
        'fill': fill, 'fees': fees, 'timestamp': stamp(), 'status': 'FILLED', 'mode': 'PAPER', 'reason': reason}
    trade = {**position, 'exit': fill, 'exit_fees': fees, 'pnl': pnl, 'timestamp': order['timestamp'], 'reason': reason}
    account['cash'] = round(account['cash'] + fill * position['quantity'] - fees, 2)
    account['realized_pnl'] = round(account['realized_pnl'] + pnl, 2)
    account['fees_paid'] += fees
    account['positions'] = [p for p in account['positions'] if p['id'] != position_id]
    account['orders'].append(order)
    account['trades'].append(trade)
    if not account['positions']:
        account['peak_equity'] = max(account['peak_equity'], account['cash'])
    await persist(account, account['version'])
    await audit(user_id, 'paper_close', {'position_id': position_id, 'reason': reason})
    return {'order': order, 'trade': trade}

@router.post('/positions/{position_id}/close', response_model=Payload)
async def close(position_id: str, user=Depends(user_required)):
    return await close_position(user['id'], position_id)

@router.post('/refresh', response_model=Payload)
async def refresh(user=Depends(user_required)):
    account = await account_for(user['id'])
    for position in account['positions']:
        quote = await get_quote(user['id'], position['symbol'])
        require_fresh(quote)
        if quote['ltp'] <= position['stop'] or quote['ltp'] >= position['target']:
            await close_position(user['id'], position['id'], quote, 'STOP' if quote['ltp'] <= position['stop'] else 'TARGET')
    current = await account_for(user['id'])
    summary = await account_summary(current)
    if summary['equity'] is not None and summary['equity'] > current['peak_equity']:
        current['peak_equity'] = summary['equity']
        await persist(current, current['version'])
        summary = await account_summary(current)
    return {'account': summary}