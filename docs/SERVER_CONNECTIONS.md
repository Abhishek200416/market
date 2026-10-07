# Application-wide receiver and connection details

This feature is a broker-neutral **JSON receiving address**, not universal broker credentials, OAuth, signature validation, or trading support.

- Existing frontend/API origin configuration is retained.
- Each browser workspace gets an independent, unguessable POST URL. The same workspace URL can be registered with multiple services that accept this JSON delivery contract.
- POST accepts a JSON object/array (256 KiB maximum), acknowledges new records with202 and duplicate canonical bodies with200, encrypts payloads and stores UNVERIFIED receipts for30 days. It never changes paper trades, orders, balances, provider credentials, or risk settings.
- GET on a receive URL returns only generic health and does not store query parameters or authorization codes. It is NOT a universal OAuth redirect.
- The receive URL is a secret capability. Keep it private, share only with intended senders, and rotate if exposed. URL recovery/rotation requires the workspace session and CSRF. An inbound URL grants send-only access, never inbox read access.
- Access logs redact the receive token and query. Reverse-proxy/platform logging is outside this application's control; use a trusted hosting environment before sending sensitive production events.
- The authenticated receipt list contains metadata only; no payload or credentials are returned to the browser.
- Outbound-IP observation is manual/on-demand, briefly cached, and explicitly OBSERVED_NOT_RESERVED. It does not provision static networking or a secondary/failover IP. `SERVER_PRIMARY_EGRESS_IP`/`SERVER_SECONDARY_EGRESS_IP`, if supplied by an operator, are configured values, not automatic proof of reservation.
- The current address may be a preview alias; HTTPS reachability does not establish that a broker accepts it or that it is permanent.

## Private API
- GET `/api/server/connection-details`: metadata and last real egress observation
- POST `/api/server/postback`: idempotent create or authorized recovery of this workspace's receiving path
- POST `/api/server/postback/rotate`: revoke the old receiving token, preserve receipts
- GET `/api/server/events`: latest12 private receipt summaries
- POST `/api/server/observe-egress`: check configured external observation service, no broker requests

## Public receiver
- POST `/api/server/receive/{token}`: receive bounded JSON, no cookie required
- GET `/api/server/receive/{token}`: generic health only, no database lookup

All application API requests still use the configured REACT_APP_BACKEND_URL. Database settings, API origin, encryption settings for existing broker keys, and server ports are unchanged. New receiver encryption uses WEBHOOK_FERNET_KEY from backend/.env.server (or environment). Preserve this key alongside the existing secrets.

### Remaining prerequisites
A provider that requires signed deliveries, challenge responses, form/XML encoding or specific OAuth state needs its own compatible adapter. Live broker deliveries have not been validated without broker setup. Genuine fixed outbound IPs need hosting-provider allocation/routing confirmation; never choose arbitrary shared pool IPs or a website's DNS IP.
