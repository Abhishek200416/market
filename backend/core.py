import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import RootModel

load_dotenv(Path(__file__).parent / '.env')
client = AsyncIOMotorClient(os.environ['MONGO_URL'], serverSelectionTimeoutMS=3000)
db = client[os.environ['DB_NAME']]

class Payload(RootModel[dict[str, Any]]):
    pass

def now():
    return datetime.now(timezone.utc)

def stamp():
    return now().isoformat()

def uid():
    return str(uuid.uuid4())

async def audit(user_id, event, detail=None):
    await db.audit_events.insert_one({'id': uid(), 'user_id': user_id, 'event': event,
                                      'detail': detail or {}, 'timestamp': stamp()})

async def indexes():
    await db.users.create_index('email', unique=True)
    await db.sessions.create_index('token_hash', unique=True)
    await db.sessions.create_index('expires_at', expireAfterSeconds=0)
    await db.credentials.create_index([('user_id', 1), ('provider', 1)], unique=True)
    await db.accounts.create_index('user_id', unique=True)
    await db.predictions.create_index('prediction_id', unique=True)
    await db.outcomes.create_index('prediction_id', unique=True)
    await db.quotes.create_index([('user_id', 1), ('symbol', 1)], unique=True)
    await db.agent_runs.create_index([('user_id', 1), ('snapshot_hash', 1)], unique=True)
    await db.oauth_states.create_index('state_hash', unique=True)
    await db.oauth_states.create_index('expires_at', expireAfterSeconds=0)