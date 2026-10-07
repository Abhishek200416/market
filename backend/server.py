import os
import time
import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from pymongo.errors import PyMongoError
from core import db, client, indexes, stamp, now, Payload
from auth import router as auth_router, optional_user, user_required
from connections import router as connection_router, statuses
from markets import router as market_router, INSTRUMENTS
from paper import router as paper_router, account_for, account_summary
from research import router as research_router
from quality import assess_quote
from market_routing import router as market_selection_router
from upstox_oauth import router as upstox_oauth_router
from origin_policy import ALLOWED_ORIGINS, is_trusted_origin
from server_connections import router as server_connections_router, public_router as server_public_router, receiver_indexes

class OAuthAccessLogRedaction(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3 and isinstance(record.args[2], str):
            args = list(record.args)
            if '/oauth/callback' in args[2]:
                args[2] = args[2].split('?', 1)[0] + '?[redacted]'
                record.args = tuple(args)
            elif '/api/server/receive/' in args[2]:
                args[2] = args[2].split('/api/server/receive/', 1)[0] + '/api/server/receive/[redacted]'
                record.args = tuple(args)
        return True

logging.getLogger('uvicorn.access').addFilter(OAuthAccessLogRedaction())

@asynccontextmanager
async def lifespan(app):
    await indexes()
    await receiver_indexes()
    # Runs interrupted by a server restart are visible as failed, never secretly resumed.
    await db.agent_runs.update_many({'status': 'RUNNING'}, {'$set': {'status': 'INTERRUPTED'}})
    yield
    client.close()

app = FastAPI(title='EDGE INDIA · Paper Research API', lifespan=lifespan)
windows = defaultdict(deque)

@app.middleware('http')
async def safety_headers(request: Request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        if origin and not is_trusted_origin(origin):
            return JSONResponse(status_code=403, content={'detail': 'Request origin rejected.'})
    if request.url.path.startswith('/api') and request.method != 'OPTIONS':
        ip = request.client.host if request.client else 'unknown'
        sensitive = request.url.path in ('/api/auth/login','/api/auth/register')
        key = (ip, 'auth' if sensitive else 'api')
        window = windows[key]
        current = time.monotonic()
        while window and window[0] < current - 60:
            window.popleft()
        if len(window) >= (20 if sensitive else 300):
            return JSONResponse(status_code=429, content={'detail': 'Request limit reached. Try again in a minute.'}, headers={'Retry-After':'60'})
        window.append(current)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.exception_handler(PyMongoError)
async def database_failure(request, exc):
    return JSONResponse(status_code=503, content={'detail': 'Database unavailable. TRADING DISABLED.'})

for router in (auth_router, connection_router, market_router, paper_router, research_router, market_selection_router, upstox_oauth_router, server_connections_router, server_public_router):
    app.include_router(router)

@app.get('/api/health', response_model=Payload)
async def health():
    await db.command('ping')
    return {'database': 'CONNECTED', 'api': 'HEALTHY', 'timestamp': stamp(), 'mode': 'PAPER', 'live_enabled': False,
        'upstream_version': '0.6.0', 'streaming': 'NOT_IMPLEMENTED', 'redis': 'NOT_CONFIGURED'}

@app.get('/api/overview', response_model=Payload)
async def overview(user=Depends(optional_user)):
    await db.command('ping')
    connections = await statuses(user['id'] if user else None)
    account = await account_summary(await account_for(user['id'])) if user else None
    predictions = await db.predictions.count_documents({'user_id': user['id']}) if user else 0
    quotes = await db.quotes.find({'user_id': user['id']}, {'_id': 0, 'user_id': 0}).to_list(50) if user else []
    quotes = [{**quote, 'freshness': assess_quote(quote)} for quote in quotes]
    return {'user': user, 'account': account, 'database': 'CONNECTED', 'connections': connections,
        'predictions_count': predictions, 'regime': None, 'decision': 'NO TRADE', 'quotes': quotes,
        'market_provider': account.get('market_provider', 'upstox') if account else 'upstox',
        'system_status': 'KILL SWITCH ACTIVE' if account and account['kill_switch'] else 'AWAITING VALIDATED DATA',
        'timestamp': stamp(), 'live_enabled': False}

@app.get('/api/system', response_model=Payload)
async def system(user=Depends(user_required)):
    connection_status = await statuses(user['id'])
    events = await db.audit_events.find({'user_id': user['id']}, {'_id': 0, 'user_id': 0}).sort('timestamp', -1).to_list(100)
    usage = await db.llm_usage.find({'user_id': user['id'], 'timestamp': {'$gte': now().replace(hour=0,minute=0,second=0,microsecond=0).isoformat()}}, {'_id': 0}).to_list(5000)
    return {'connections': connection_status, 'events': events, 'database': 'CONNECTED',
        'requests_today': len(usage), 'tokens_today': sum(u.get('tokens') or 0 for u in usage),
        'estimated_cost': 0 if not usage else None, 'quick_model': os.environ['GEMINI_QUICK_MODEL'],
        'deep_model': os.environ['GEMINI_DEEP_MODEL'], 'upstream_version': '0.6.0', 'timestamp': stamp()}


# Wrap the complete ASGI app so middleware errors retain explicit CORS headers
# for trusted callers. Arbitrary origins receive no cross-origin access.
app = CORSMiddleware(
    app=app,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=['Content-Type', 'X-CSRF-Token'],
)
