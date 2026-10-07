import asyncio
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError
from auth import user_required
from core import db, now, stamp, uid, audit, Payload
from connections import credentials
from markets import get_quote, instrument
from providers import FyersMarketDataProvider
from quality import require_fresh
from paper import account_for
from market_routing import market_provider

router = APIRouter(prefix='/api')
semaphore = asyncio.Semaphore(1)

class RunInput(BaseModel):
    symbol: str

@router.post('/research/run', response_model=Payload)
async def research(data: RunInput, user=Depends(user_required)):
    item = instrument(data.symbol)
    account = await account_for(user['id'])
    if account['kill_switch']:
        raise HTTPException(409, 'Kill switch active. Research generation blocked.')
    gemini = await credentials(user['id'], 'gemini')
    quote = await get_quote(user['id'], data.symbol)
    require_fresh(quote)
    provider = await market_provider(user['id'])
    if provider.name != quote.get('provider'):
        raise HTTPException(409, 'Selected provider changed before research capture. Retry with a consistent source.')
    cutoff = now()
    candles = await provider.candles(data.symbol, '5', int(cutoff.timestamp()) - 5 * 86400, int(cutoff.timestamp()))
    if len(candles) < 50 or cutoff.timestamp() - candles[-1]['time'] > 900:
        raise HTTPException(409, 'NO TRADE — insufficient or stale completed 5-minute candles.')
    snapshot = {'candles': candles, 'quote': quote, 'cutoff': cutoff.isoformat(), 'provider': provider.name}
    # Same candle set and model configuration is cached; receipt-time changes cannot evade deduplication.
    fingerprint = hashlib.sha256(json.dumps({'symbol': data.symbol, 'provider': provider.name, 'bars': [{k:c[k] for k in ('time','open','high','low','close','volume')} for c in candles],
        'quick': os.environ['GEMINI_QUICK_MODEL'], 'deep': os.environ['GEMINI_DEEP_MODEL']}, sort_keys=True).encode()).hexdigest()
    previous = await db.agent_runs.find_one({'user_id': user['id'], 'snapshot_hash': fingerprint}, {'_id': 0})
    if previous:
        if previous['status'] == 'COMPLETED':
            return {'run': previous, 'cached': True}
        raise HTTPException(409, f"Previous run is {previous['status']}. Wait for a new completed 5-minute bar before retrying.")
    recent = await db.agent_runs.count_documents({'user_id': user['id'], 'timestamp': {'$gte': (now()-timedelta(days=1)).isoformat()}})
    if recent >= 10 or semaphore.locked():
        raise HTTPException(429, 'Research capacity limit. Maximum 10 runs/day and one concurrent run.')
    run = {'id': uid(), 'user_id': user['id'], 'symbol': data.symbol, 'timestamp': stamp(), 'status': 'RUNNING', 'snapshot_hash': fingerprint}
    try:
        await db.agent_runs.insert_one(run.copy())
    except DuplicateKeyError:
        raise HTTPException(409, 'This snapshot is already being analyzed.')
    payload = {'snapshot': snapshot, 'user_id': user['id'], 'api_key': gemini['api_key'], 'run_id': run['id'],
        'quick_model': os.environ['GEMINI_QUICK_MODEL'], 'deep_model': os.environ['GEMINI_DEEP_MODEL'],
        'runtime_dir': os.environ['RUNTIME_DIR'], 'ticker': data.symbol.replace('NSE:', '').replace('-EQ', '.NS')}
    result = {}
    async with semaphore:
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'research_worker', cwd=str(Path(__file__).parent),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), timeout=240)
            line = next((line for line in reversed(output.decode().splitlines()) if line.startswith('TERMINAL_RESULT=')), None)
            result = json.loads(line.split('=', 1)[1]) if line else {'error': 'Research worker did not produce a report.'}
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            result = {'error': 'Research time budget exceeded. No signal released.'}
    run.update(status='FAILED' if result.get('error') else 'COMPLETED', completed_at=stamp(), result=result)
    await db.agent_runs.update_one({'id': run['id']}, {'$set': {'status': run['status'], 'completed_at': run['completed_at'], 'result': result}})
    for usage in result.get('usage', []):
        await db.llm_usage.insert_one({'user_id': user['id'], 'timestamp': stamp(), 'run_id': run['id'], 'purpose': 'research', 'estimated_cost': None, **usage})
    if result.get('error'):
        raise HTTPException(502, result['error'])
    # Revalidate input at release time; an LLM report alone is never an executable signal.
    fresh = await get_quote(user['id'], data.symbol)
    if fresh.get('provider') != provider.name:
        raise HTTPException(409, 'Research saved, but provider changed. No cross-provider prediction released.')
    require_fresh(fresh)
    account = await account_for(user['id'])
    if account['kill_switch']:
        raise HTTPException(409, 'Research saved, but kill switch blocks prediction release.')
    direction = {'Buy': 'UP', 'Overweight': 'UP', 'Underweight': 'DOWN', 'Sell': 'DOWN', 'Hold': 'NEUTRAL'}.get(result['rating'], 'NO TRADE')
    created = now()
    prediction = {'prediction_id': uid(), 'user_id': user['id'], 'timestamp': created.isoformat(), 'asset': data.symbol,
        'horizon': '5m', 'horizon_end': datetime.fromtimestamp(math.ceil((created.timestamp()+300)/60)*60, created.tzinfo).isoformat(),
        'direction': direction, 'probability': None, 'confidence': None, 'expected_return': None, 'expected_range': None,
        'entry': fresh['ltp'], 'stop': None, 'target': None, 'provider': provider.name, 'model': os.environ['GEMINI_DEEP_MODEL'], 'agent': 'TradingAgents Portfolio Manager',
        'reason': result['report'], 'input_snapshot_hash': hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
        'input_snapshot': snapshot, 'run_id': run['id'], 'execution_state': 'NO TRADE', 'calibration_status': 'UNCALIBRATED'}
    await db.predictions.insert_one(prediction.copy())
    await audit(user['id'], 'research_completed', {'run_id': run['id'], 'prediction_id': prediction['prediction_id']})
    return {'run': run, 'prediction_id': prediction['prediction_id'], 'execution_state': 'NO TRADE'}

@router.get('/research/runs', response_model=Payload)
async def runs(user=Depends(user_required)):
    return {'runs': await db.agent_runs.find({'user_id': user['id']}, {'_id': 0}).sort('timestamp', -1).to_list(100)}

@router.get('/ledger', response_model=Payload)
async def ledger(user=Depends(user_required)):
    items = await db.predictions.find({'user_id': user['id']}, {'_id': 0, 'input_snapshot': 0}).sort('timestamp', -1).to_list(500)
    outcomes = await db.outcomes.find({'user_id': user['id']}, {'_id': 0}).to_list(500)
    return {'predictions': [{**item, 'outcome': next((o for o in outcomes if o['prediction_id'] == item['prediction_id']), None)} for item in items]}

@router.post('/ledger/settle', response_model=Payload)
async def settle(user=Depends(user_required)):
    items = await db.predictions.find({'user_id': user['id'], 'horizon_end': {'$lte': stamp()}}, {'_id': 0}).to_list(500)
    count = 0
    for item in items:
        if await db.outcomes.find_one({'prediction_id': item['prediction_id']}, {'_id': 0}):
            continue
        # Outcomes use the ORIGINAL prediction's provider, never a newly selected feed.
        provider = await market_provider(user['id'], item.get('provider', 'FYERS').lower())
        target = int(datetime.fromisoformat(item['horizon_end']).timestamp())
        rows = await provider.candles(item['asset'], '1', target-60, target+60, )
        candle = next((r for r in rows if r['time'] + 60 == target), None)
        if not candle:
            continue  # Gaps/closed sessions stay unresolved; never substitute a later price.
        actual = (candle['close'] / item['entry'] - 1)
        direction = 'UP' if actual > .0001 else 'DOWN' if actual < -.0001 else 'NEUTRAL'
        outcome = {'prediction_id': item['prediction_id'], 'user_id': user['id'], 'settled_at': stamp(),
            'source_timestamp': candle['timestamp'], 'actual_return': actual, 'actual_direction': direction,
            'correct': direction == item['direction'], 'brier_score': None, 'calibration_bucket': None}
        try:
            await db.outcomes.insert_one(outcome)
            count += 1
        except DuplicateKeyError:
            pass
    return {'settled': count, 'message': f'{count} predictions settled against exact-horizon completed source-provider bars.'}