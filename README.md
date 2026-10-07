# EDGE INDIA — experimental trading research terminal

India-first research built around **Tauric Research TradingAgents v0.6.0**, with FastAPI, React and MongoDB. This is a first implementation, **not a production-approved trading system**. Real broker execution is absent. Prefer NO TRADE over an unsupported trade.

## Start here
**Latest update:** the terminal now defaults to **Upstox** with FYERS as an explicitly selected alternative. Read [Upstox connection guidance](docs/UPSTOX_CONNECTION.md) before configuring broker forms. The interface has larger text, stronger dark-mode contrast, restrained status colors, expanded mobile touch targets and no page entrance/background motion. Broker registration details and a PNG app logo are available in API Connections.

For the simplest Upstox market-data-only path, generate an Analytics Token in Upstox Developer Apps and save it in API Connections. Official Upstox documentation distinguishes market quotes/history (no static IP needed for this token category) from restricted account/portfolio APIs. The adapter only calls data endpoints. The UI never invents an IP or callback hostname. Paytm Money remains separate and deferred.

The original FYERS-first walkthrough below remains applicable **only after selecting FYERS** in the active-market-data selector. For Upstox, use the token connection and provider-neutral Markets/Signals/Paper workflows instead.

1. Open the terminal and select **Sign in → Create an account**. Account creation initializes ₹10,00,000 in simulated capital. No demo account or artificial market feed is created.
2. Open **API Connections**. Save your FYERS client ID/access token (obtained through the official FYERS dashboard), then test the connection. Automated OAuth is not implemented. Tokens may need renewal; permission/plan errors remain explicit.
3. Add your Google Gemini API key. Test validates the configured quick model; stronger-model availability is checked when actually used. No credentials were supplied for development, so real-key live runs remain unverified.
4. Markets provides completed FYERS candles at 1m/5m/15m/30m/1h/1D. REST polling, not WebSocket, refreshes while the view is open. Missing source timestamps mean UNKNOWN; source age >15 seconds means STALE. Neither can authorize a signal or order.
5. AI Signals runs the real upstream graph over a frozen 5-minute technical snapshot, with Bull/Bear debate, Research Manager, Trader, three risk debaters, Portfolio Manager, checkpoints and reports. No news/options data is invented. Research is **technical-only and uncalibrated**. AI never sends orders.
6. Paper Trading accepts manual long-equity orders only. Indices are research-only. Risk checks run on fresh broker data; fills use the ask +5bps or bid −5bps. Close positions or select Refresh positions to evaluate stops/targets. **No unattended protective-stop monitoring**.
7. Prediction Ledger stores original forecasts separately from outcomes. Evaluate due forecasts against the completed 1-minute bar at the exact horizon endpoint. Missing market bars stay pending. No exact-price or calibrated-profit probability is claimed.

## Implemented controls
Per-trade risk default 0.5%, daily realized-plus-open loss check 2%, 3 consecutive losses lock, 60-second cooldown, maximum 10 opening trades/day, maximum 30% exposure / 10% per position, minimum 2:1 risk/reward, 1,000 shares daily volume, 25bps spread cap. Configurable within bounded ranges. Kill switch blocks new paper orders and research; fresh-data risk-reducing closes remain available. Versioned single-document account writes prevent concurrent cash/fill divergence. Idempotency prevents double execution.

Fees are explicit **assumptions**, not broker invoices: equity-intraday brokerage 0.03% capped at ₹20/order; exchange 0.00297%, SEBI 0.0001%, GST 18% on brokerage/exchange/SEBI, buy stamp duty 0.003%, sell STT 0.025%. These require regulatory/broker verification before any use beyond experiments. No delivery/futures/options fee model is claimed.

## Architecture and provenance
- [Repository audit](docs/ARCHITECTURE_AUDIT.md): upstream verified release and commit, modules inspected, limitations; secondary Indian reference returned HTTP 404 and was not imported.
- [Architecture and migration](docs/ARCHITECTURE.md): user-approved React/MongoDB first-delivery deviation from Next.js/PostgreSQL/Redis.
- [Upstream extension record](docs/UPSTREAM_CHANGES.md): narrow model injection/stronger Trader changes; no graph topology rewrite.
- [Security boundaries](docs/SECURITY_BOUNDARIES.md): encryption, sessions, CSRF, edge cookie observation, scaling caveats.
- [Third-party notices](THIRD_PARTY_NOTICES.md) and original `vendor/TradingAgents/LICENSE`.

## Local environment
Python 3.11+, Node 22+, Yarn, MongoDB. Set backend environment using `.env.example` as a reference; in this hosted workspace preserve the supplied MONGO_URL and REACT_APP_BACKEND_URL. Generate ENCRYPTION_KEY once and retain it securely: changing it without migration makes stored provider keys unreadable. APP_ORIGIN must equal the external browser origin. Secure cookies require HTTPS (including a trusted local TLS proxy for local auth).

```sh
pip install --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -r backend/requirements.txt
cd frontend && yarn install --frozen-lockfile
```

The editable upstream source is expected at `/app/vendor/TradingAgents`; for another checkout path, install that directory explicitly with pip and adjust the editable requirement using your package manager. Hosted services are already managed by supervisor on frontend 3000/backend 8001; ordinary source changes hot reload. Restart via supervisor after dependency/environment changes.

## Container packaging
Copy `.env.example` to a private root `.env`, set external HTTPS origin, encryption key and internal Mongo/upstream URLs. `docker compose up --build` defines frontend/nginx, backend and Mongo services. Terminate TLS at a trusted proxy. The research worker is a bounded per-request subprocess in the backend, **not yet a durable standalone worker service**. Compose is provided as packaging scaffolding; a Docker build and external HTTPS smoke test have not been performed in this environment. PostgreSQL/Redis services are intentionally deferred to the documented migration rather than pretending they back the app.

## Tests
```sh
pytest tests -q
pytest vendor/TradingAgents/tests/test_graph_end_to_end.py \
       vendor/TradingAgents/tests/test_memory_pointintime.py \
       vendor/TradingAgents/tests/test_tool_date_enforcement.py \
       vendor/TradingAgents/tests/test_checkpoint_resume.py -q
cd frontend && yarn build
```
API integration tests read the external URL from frontend/.env and create isolated QA accounts. Synthetic prices/scripted model responses exist **only in isolated unit tests**, never in the runtime feed. Initial verification:13 app/unit tests and57 focused upstream tests passed; expanded first delivery22 tests; Upstox revision23 original-suite and9 additional provider/API tests passed before final mobile fixes. Reports are under `test_reports/`; they do not prove real provider availability or financial edge.

## Monitoring and fail-safe operation
`/api/health` reports DB/API/mode; authenticated System Health exposes provider status, audit events and request/token counters. Missing pricing yields unknown cost, not invented cost. Mongo failure returns TRADING DISABLED. Secrets and raw SDK exceptions are not logged to clients. Provider outage or unknown/stale prices block orders. Back up Mongo, the encryption secret, and per-user runtime checkpoints/reports together. Inspect process logs, connection errors and blocked risk events; do not automatically widen limits on failure.

## Remaining release gates / NO-GO
No proven edge, out-of-sample acceptance or eligibility for real trading. WebSocket recovery, durable job queue and scheduled pre-market reports, licensed options/news/macro, ML/ensembles, walk-forward/cost-adjusted execution backtesting, multi-horizon calibration, shadow trading, distributed rate limits, full exchange calendars, security hardening and broker/regulatory review remain subsequent work. Risk engine is not a market halt/holiday oracle; fresh quotes alone do not establish regulatory eligibility.