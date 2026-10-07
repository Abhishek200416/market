import hashlib
import secrets
from datetime import timedelta
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError
from core import db, now, stamp, uid, audit, Payload
from origin_policy import is_trusted_origin

router = APIRouter(prefix='/api/auth')

class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=72)
    name: str = Field(default='Researcher', min_length=1, max_length=60)

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

async def optional_user(request: Request):
    token = request.cookies.get('terminal_session')
    if not token:
        return None
    session = await db.sessions.find_one({'token_hash': digest(token), 'expires_at': {'$gt': now()}}, {'_id': 0})
    if not session:
        return None
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        csrf = request.headers.get('X-CSRF-Token', '')
        if not secrets.compare_digest(digest(csrf), session['csrf_hash']):
            raise HTTPException(403, 'Workspace verification expired. Reopen the page to reconnect.')
    return await db.users.find_one({'id': session['user_id']}, {'_id': 0, 'password_hash': 0})

async def user_required(user=Depends(optional_user)):
    if not user:
        raise HTTPException(401, 'Workspace session expired. Reopen the page to reconnect.')
    return user

def public_user(user):
    return {k: user[k] for k in ('id', 'email', 'name', 'is_guest') if k in user}


def set_session_cookie(response, token, max_age):
    response.set_cookie('terminal_session', token, httponly=True, secure=True,
                        samesite='lax', max_age=max_age, path='/api')


async def session_response(user, response):
    token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
    lifetime = timedelta(days=90) if user.get('is_guest') else timedelta(hours=12)
    await db.sessions.insert_one({'token_hash': digest(token), 'csrf_hash': digest(csrf), 'csrf_token': csrf,
        'user_id': user['id'], 'expires_at': now() + lifetime})
    set_session_cookie(response, token, int(lifetime.total_seconds()))
    await audit(user['id'], 'session_created')
    return {'user': public_user(user), 'csrf_token': csrf}


@router.post('/workspace', response_model=Payload)
async def open_workspace(request: Request, response: Response):
    """Create or resume an isolated workspace. Never select an account by public ID.

    Trusted app origins may bootstrap CSRF; subsequent writes still require it.
    The opaque HttpOnly cookie is the only workspace access credential.
    """
    from risk import RiskSettings
    if not is_trusted_origin(request.headers.get('origin')):
        raise HTTPException(403, 'Open the workspace from the application.')
    token = request.cookies.get('terminal_session')
    if token:
        session = await db.sessions.find_one({'token_hash': digest(token), 'expires_at': {'$gt': now()}})
        if session:
            user = await db.users.find_one({'id': session['user_id']}, {'_id': 0, 'password_hash': 0})
            if user:
                csrf = session.get('csrf_token') or secrets.token_urlsafe(32)
                lifetime = timedelta(days=90) if user.get('is_guest') else timedelta(hours=12)
                await db.sessions.update_one({'token_hash': digest(token)}, {'$set': {
                    'csrf_token': csrf, 'csrf_hash': digest(csrf), 'expires_at': now() + lifetime}})
                set_session_cookie(response, token, int(lifetime.total_seconds()))
                return {'user': public_user(user), 'csrf_token': csrf}
    user_id = uid()
    user = {'id': user_id, 'name': 'My workspace', 'email': f'{user_id}@guest.invalid',
            'is_guest': True, 'created_at': stamp()}
    await db.users.insert_one(user.copy())
    await db.accounts.insert_one({'user_id': user_id, 'starting_capital': 1000000.0,
        'cash': 1000000.0, 'realized_pnl': 0.0, 'fees_paid': 0.0, 'peak_equity': 1000000.0,
        'positions': [], 'orders': [], 'trades': [], 'risk': RiskSettings().model_dump(),
        'kill_switch': False, 'market_provider': 'upstox', 'version': 0, 'created_at': stamp()})
    await audit(user_id, 'workspace_created', {'mode': 'guest', 'execution': 'PAPER'})
    return await session_response(user, response)

@router.post('/register', response_model=Payload)
async def register(data: Credentials, response: Response):
    from risk import RiskSettings
    if len(data.password.encode()) > 72:
        raise HTTPException(422, 'Password must be at most 72 bytes.')
    user = {'id': uid(), 'name': data.name.strip(), 'email': data.email.lower(),
        'password_hash': bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(), 'created_at': stamp()}
    try:
        await db.users.insert_one(user.copy())
    except DuplicateKeyError:
        raise HTTPException(409, 'An account already exists for this email.')
    await db.accounts.insert_one({'user_id': user['id'], 'starting_capital': 1000000.0,
        'cash': 1000000.0, 'realized_pnl': 0.0, 'fees_paid': 0.0, 'peak_equity': 1000000.0,
        'positions': [], 'orders': [], 'trades': [], 'risk': RiskSettings().model_dump(),
        'kill_switch': False, 'market_provider': 'upstox', 'version': 0, 'created_at': stamp()})
    return await session_response(user, response)

@router.post('/login', response_model=Payload)
async def login(data: Credentials, response: Response):
    if len(data.password.encode()) > 72:
        raise HTTPException(422, 'Password must be at most 72 bytes.')
    user = await db.users.find_one({'email': data.email.lower()}, {'_id': 0})
    if not user or not user.get('password_hash') or not bcrypt.checkpw(data.password.encode(), user['password_hash'].encode()):
        raise HTTPException(401, 'Email or password is incorrect.')
    return await session_response(user, response)

@router.get('/me', response_model=Payload)
async def me(user=Depends(optional_user)):
    return {'user': user}

@router.get('/csrf', response_model=Payload)
async def csrf_for_session(request: Request, user=Depends(user_required)):
    token_hash = digest(request.cookies['terminal_session'])
    session = await db.sessions.find_one({'token_hash': token_hash}, {'_id': 0})
    csrf = session.get('csrf_token')
    if not csrf:
        csrf = secrets.token_urlsafe(32)
        await db.sessions.update_one({'token_hash': token_hash}, {'$set': {'csrf_token': csrf, 'csrf_hash': digest(csrf)}})
    return {'csrf_token': csrf}

@router.post('/logout', response_model=Payload)
async def logout(request: Request, response: Response, user=Depends(user_required)):
    await db.sessions.delete_one({'token_hash': digest(request.cookies['terminal_session'])})
    response.delete_cookie('terminal_session', path='/api', secure=True, httponly=True, samesite='lax')
    return {'ok': True}