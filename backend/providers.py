"""Provider boundaries: trading logic consumes these contracts, not vendor SDKs."""
from typing import Protocol
import os
import httpx
from fastapi import HTTPException
from quality import normalize_quote, normalize_candles

class MarketDataProvider(Protocol):
    async def quote(self, symbol: str) -> dict: ...
    async def candles(self, symbol: str, resolution: str, start: int, end: int) -> list: ...

class NewsProvider(Protocol):
    async def events(self, symbols: list[str], as_of: str) -> list: ...
class OptionsProvider(Protocol):
    async def chain(self, underlying: str, expiry: str) -> list: ...
class MacroProvider(Protocol):
    async def observations(self, series: str, as_of: str) -> list: ...
class SentimentProvider(Protocol):
    async def observations(self, symbol: str, as_of: str) -> list: ...
class EconomicCalendarProvider(Protocol):
    async def events(self, start: str, end: str) -> list: ...
class CorporateEventsProvider(Protocol):
    async def events(self, symbol: str, as_of: str) -> list: ...
class BrokerProvider(Protocol):
    async def get_account(self) -> dict: ...
    async def get_balance(self) -> dict: ...
    async def get_positions(self) -> dict: ...
    async def get_orders(self) -> dict: ...
    async def get_quote(self, symbol: str) -> dict: ...
    async def place_order(self, order: dict) -> dict: ...
    async def modify_order(self, order: dict) -> dict: ...
    async def cancel_order(self, order_id: str) -> dict: ...

class FyersMarketDataProvider:
    name = 'FYERS'
    def __init__(self, credentials):
        self.credentials = credentials
        self.headers = {'Authorization': f"{credentials['client_id']}:{credentials['access_token']}"}

    async def request(self, path, params=None, account=False):
        base = os.environ['FYERS_ACCOUNT_URL' if account else 'FYERS_DATA_URL']
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(f'{base}/{path}', headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get('s') != 'ok':
                raise HTTPException(502, f"FYERS rejected request (code {data.get('code', 'unknown')}). Check token, permissions and plan.")
            return data
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'FYERS unavailable or authentication rejected. No data substituted.')

    async def quote(self, symbol):
        data = await self.request('quotes', {'symbols': symbol})
        rows = data.get('d', [])
        if not rows or rows[0].get('s') != 'ok':
            raise HTTPException(502, 'FYERS returned no valid quote for this instrument.')
        return normalize_quote(symbol, rows[0].get('v', {}))

    async def candles(self, symbol, resolution, start, end):
        data = await self.request('history', {'symbol': symbol, 'resolution': resolution,
            'date_format': '0', 'range_from': str(start), 'range_to': str(end), 'cont_flag': '1'})
        return normalize_candles(symbol, data.get('candles', []), resolution, end)

class FyersBrokerProvider(FyersMarketDataProvider):
    async def get_account(self):
        return await self.request('profile', account=True)
    async def get_balance(self):
        return await self.request('funds', account=True)
    async def get_positions(self):
        return await self.request('positions', account=True)
    async def get_orders(self):
        return await self.request('orders', account=True)
    async def get_quote(self, symbol):
        return await self.quote(symbol)
    async def place_order(self, order):
        raise HTTPException(403, 'Live execution is disabled. Use the risk-checked paper engine.')
    async def modify_order(self, order):
        raise HTTPException(403, 'Live execution is disabled.')
    async def cancel_order(self, order_id):
        raise HTTPException(403, 'Live execution is disabled.')