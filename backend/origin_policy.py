"""One explicit browser-origin policy shared by CORS and mutation guards.

The optional alias file adds approved preview origins without changing the
canonical API URL, APP_ORIGIN, database configuration or session secrets.
Deployment environment variables take precedence over either dotenv file.
"""
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / '.env')
load_dotenv(_ROOT / '.env.origins')


def trusted_origins():
    primary = os.environ['APP_ORIGIN']
    aliases = os.environ.get('APP_ALIAS_ORIGINS', '')
    origins = []
    for value in [primary, *aliases.split(',')]:
        origin = value.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or '*' in origin
                or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment):
            raise ValueError('Browser origins must be explicit HTTPS origins without paths or wildcards.')
        # Validate a supplied port rather than accepting a malformed netloc.
        _ = parsed.port
        if origin not in origins:
            origins.append(origin)
    return tuple(origins)


ALLOWED_ORIGINS = trusted_origins()


def is_trusted_origin(origin):
    return origin in ALLOWED_ORIGINS
