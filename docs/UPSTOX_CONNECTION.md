# Upstox: read-only market data and gated OAuth

## Confirmed references (2026-10-07)
- https://upstox.com/developer/api-documentation/analytics-token/
- https://upstox.com/developer/api-documentation/authorize/
- https://upstox.com/developer/api-documentation/get-token/
- https://upstox.com/developer/api-documentation/get-full-market-quote/
- https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
- https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/
- Official instrument master: https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz

The live public instrument master was actually downloaded and inspected. It identified Nifty 50 as `NSE_INDEX|Nifty 50` (trading symbol NIFTY), Nifty Bank as `NSE_INDEX|Nifty Bank` (BANKNIFTY). Do not use guessed uppercase index IDs. Equities are resolved from NSE_EQ records with exact trading-symbol and EQ type. The runtime resolves the public master on demand, cached by IST date; no scheduled worker is claimed.

## Fastest data-only connection
Upstox documents an **Analytics Token** generated in Developer Apps → Analytics. It supports permitted GET APIs, is documented as valid for one year, and generating another revokes the previous one. Its documentation distinguishes market quotes/history (no static IP required) from user/account/portfolio-related categories (static-IP restrictions may apply). The terminal therefore tests a market quote, **not profile/account APIs**. These are vendor policy statements, not guarantees that a particular account/plan is entitled.

Paste a token into authenticated API Connections. It is Fernet-encrypted server-side; no complete credential is returned. API key+secret alone are not access tokens. No chat credentials have been assigned to a user or used to make requests. Rotate credentials exposed in chat and use the connection form.

## Provider routing
Upstox is the new account default. FYERS remains available through an explicit selector; there is **no automatic fallback**. Switching is prohibited while paper positions are open. Cached quotes are cleared on switch. Original predictions keep their provider for settlement even if the active provider later changes. No source mixing or guessed prices. Upstox quote feed timestamp and last-trade timestamp are separate fields; absent source time stays unknown.

Historical candles use V3 unit/interval mapping; the current day is fetched using the separate intraday endpoint. Only completed candles are retained. Conflicting duplicate timestamps are rejected, missing OHLCV are not filled. The daily endpoint excludes the current day's incomplete daily candle. Transport is REST, not WebSocket.

## OAuth registration fields
- Website: pending until `BROKER_PUBLIC_ORIGIN` is supplied as a permanent HTTPS origin.
- Redirect: `GET /api/integrations/upstox/oauth/callback` on that origin. Exact URL must be registered with Upstox. No fabricated absolute URL is shown while the origin is missing.
- Postback: not implemented or needed for this data-only integration. No receiver should be registered.
- Primary / secondary IP: unknown/not reserved. Do not use DNS ingress IPs or choose two from a shared pool. Verify requirements for the exact API/token category with the broker.
- Paytm Money: deferred. Upstox routes/tokens must not be registered as Paytm Money's.

OAuth start is POST, authenticated and CSRF-guarded. It returns 409 with no outbound request while origin is missing/preview/invalid. State is random, hashed in storage, bound to user+session, expires after ten minutes and is atomically consumed before exchange. Changed credentials invalidate pending authorization. Tokens are exchanged server-to-server with the official form-encoded POST endpoint. A callback returns a clean 303 to Connections without token/code. Application access logging redacts OAuth callback query strings; operators must ALSO configure external edge/proxy request-log redaction. No PKCE or refresh token is assumed because these are not documented in the checked flow.

## Remaining verification
No rotated real access token or permanent origin was supplied. Real authenticated quotes, account entitlement, market-hour freshness, and interactive broker OAuth cannot yet be verified. Static IP provisioning is unresolved but not assumed to block the documented Analytics quotes/history path. No actual order calls exist in this adapter.