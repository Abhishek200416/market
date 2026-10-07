# Platform architecture

## Update: Upstox and readability revision
Upstox is now the explicit default selected market-data provider, with FYERS selectable as an alternative (never silent fallback). Both implement the same normalized quote/candle contract; risk/fills/research consume the provider abstraction. Predictions preserve original provider for outcome settlement. Upstox instrument mappings resolve the official JSON master on demand with an IST-day cache. Analytics-token connection tests use quotes, not account APIs. OAuth start/callback is implemented but remains gated until a permanent HTTPS origin is configured; no guessed public URL or reserved outbound IP is supplied. See `UPSTOX_CONNECTION.md`. This is still REST-only and paper-only.

## Accepted first-delivery stack deviation
The user explicitly approved React + FastAPI + MongoDB in place of Next.js + PostgreSQL + Redis. This is an experimental paper-only first delivery, not a claim of production trading readiness.

React → authenticated FastAPI → provider interfaces / deterministic risk / paper account / upstream research worker → MongoDB and per-user upstream checkpoint/report files.

- MongoDB URL comes only from the supplied backend environment. UUID public identities, UTC timestamps and Asia/Kolkata trading-day boundaries; `_id` never leaves API.
- Mongo collections: users, sessions, credentials, accounts, quotes, agent_runs, predictions, outcomes, audit_events, llm_usage. Account cash, positions, fills and trades are changed atomically in a versioned single document; duplicate idempotency keys cannot fill twice.
- Secrets: bcrypt password hashing, hashed opaque session IDs, Secure HttpOnly SameSite cookies, request-origin and CSRF checks, Fernet encrypted provider fields, authenticated user ownership, rate limiting, sanitized errors. Encryption key supplied by environment; no cleartext secrets returned.
- REST market polling only initially. Freshness derives from source timestamps, never receipt time. Missing fields stay null; stale data blocks orders and research.
- Broker provider has read-only operations. All broker mutation methods refuse live execution; paper fills use a separate engine. Indices cannot be purchased as cash equities.
- Upstream graph research runs in a bounded subprocess; per-run credentials passed on stdin, not disk or command line. FYERS candles are frozen at the input cutoff and tool calls cannot obtain future observations.
- No LLM-to-order path. Reports are research opinions, not calibrated probability. Probabilities remain null until empirically supported. Deterministic risk independently guards every fill.

## Migration boundaries
Provider Protocols are independent of storage. Mongo access is confined to backend service/repository modules. PostgreSQL migration maps UUID fields and account events to tables with serializable transactions. Predictions become insert-only rows, outcomes a keyed related table; enforce immutability with DB permissions/triggers. Move upstream checkpoint files to supported shared durable storage before multiple workers. Replace single-instance in-memory rate limiter with Redis, move worker requests to a durable queue, and cache provider payloads with source-time metadata and tenant ownership. React components consume `/api` independently of router framework; Next.js can replace presentation without changing these contracts.

## Deliberately deferred
Automated pre-market schedules, reliable WebSocket streaming/reconnect, options/Greeks, news/macro/social ingestion, ML ensembles, economic calendars, realistic exchange holiday sessions, walk-forward backtests, shadow trades and calibration. No timers impersonating a durable job scheduler. Execution is manual paper-only and observations update only while clients fetch data; unattended protective stop monitoring needs the streaming worker. This limitation is shown in the paper account.