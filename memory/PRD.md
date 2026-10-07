# EDGE INDIA — product requirements and handoff

## Original problem statement
Build an experimental India-first AI market intelligence, quantitative research, backtesting, paper trading and eventual broker-integration terminal. Primary market NSE/BSE, NIFTY/BANKNIFTY and selected liquid equities; licensed F&O later. Use TauricResearch/TradingAgents latest stable (target v0.6.0) as the real multi-agent LangGraph orchestration foundation, inspect secondary pradeepsiddappa/indian-trading-agent, preserve Apache-2.0 notices. Do not blindly merge. First delivery: audit, architecture, upstream integration, FastAPI, terminal, market and Gemini adapters, real-data chart, paper/risk engines, immutable prediction ledger, dashboard. Later phases options/news/macro/ML/backtests/shadow/calibration. Never fabricate data, promise performance, leak future data, or send real orders. Prefer NO TRADE. Full reference requirements were provided in the project brief (phases 0–38).

## User choices
- Credentials setup first: no invented market data or AI while disconnected.
- React + FastAPI + MongoDB accepted for initial delivery instead of Next.js/PostgreSQL/Redis; migration boundaries documented.
- Email/password; initial paper capital ₹10,00,000; risk/trade0.5%, daily loss2%, 3-loss cooldown.
- Follow-up: current tiny/low-contrast UI strained eyes; retain a dignified dark theme, clearer colors, readable PC/mobile, no distracting motion. Asked for broker app name/website/redirect/postback/IP/logo and Upstox (originally “hub stocks”), Gemini and Paytm Money.
- User pasted credentials in chat; advised rotation and secure form entry. NEVER assigned them to any test account or made requests with them.
- Follow-up response selected mutually exclusive broker/domain choices. Proceeded with original likely intent: Upstox first; Paytm deferred; permanent hostname/IP pending. No fabricated IPs or guessed active callback URL.

## Personas / core static requirements
Private Indian-market researcher comparing AI model performance, and cautious paper trader eliminating overtrading. Values: inspectable evidence, risk control, actual outcome evaluation, source provenance and reproducibility. No real-money trade path, no profit promises. Account-specific secrets, data and ledger; high readability/mobile touch targets.

## Architecture
React pages consume environment external `/api` URL. FastAPI with Mongo-only supplied MONGO_URL. Secure HttpOnly sessions, CSRF token and Origin checks; bcrypt; Fernet credentials. Provider protocols separate from deterministic risk. Upstream v0.6.0 vendored at1394a3f72aa4393e1a98f51b382434c4b4c2d972; original license retained. Minimal optional client factory + stronger Trader patch. One bounded isolated subprocess per research request; frozen provider candles; source data only, no Yahoo fallback. Atomic versioned paper account contains cash/positions/orders/trades. Predictions insert-only API, outcomes separate. Per-user upstream SQLite checkpoints/files. No Redis or unattended streaming worker; limitations explicit.

## Implemented — 2026-10-07 initial delivery
- Repository audit/architecture/third-party notice/minimal upstream changes docs; secondary repo404, comparison impossible.
- Dark terminal with auth, markets, signals, paper/risk, ledger, journal, models, health, connections, settings, eligibility. Future modules honestly not enabled.
- FYERS read-only HTTPX REST adapter (SDK requests-version conflict documented). Normalization/source-time freshness, stale/unknown/anomaly/out-of-order detection.
- Gemini via actual upstream Google client per-user key; real LangGraph market analyst, debate/research/trader/risk/portfolio; memory/report/checkpoint preserved at compatible boundaries; daily reflection deferred for intraday mismatch.
- Manual long-equity paper fills; fees/slippage assumptions; cash/PnL; kill/cooldown/exposure/liquidity/spread/duplicate/daily&streak limits; source validation before commit. Stops checked on Refresh only, never claimed unattended.
- Immutable 5-minute prediction ledger; exact-horizon completed1m outcome settlement; missing bars pending; probabilities null (uncalibrated).
- Docker/frontend/backend/nginx/compose scaffolding, env example, README; container build not verified.
- Tests iteration1 13 local/API +57 focused upstream; iteration2 expanded22 tests and desktop/mobile/browser flows passed. Session CSRF recovery, positive paper accounting, stops/target gaps, immutable settlement covered. Warnings: third-party multipart PendingDeprecationWarning, no functional defect.

## Implemented — 2026-10-07 readability / Upstox revision
- `readability.css`: charcoal/slate surfaces, stronger text contrast, body12–16px, captions11px, larger touch targets, no page entrance/background animation; restrained gain/loss/warning colors. Sidebar primary workflow prioritized, Research Labs expandable; full search available.
- Upstox API Connections with secure token and optional app-key/secret forms. Per-account explicit provider selector; Upstox default, FYERS alternative. No automatic fallback; provider changes blocked with open positions; quotes invalidated on switch.
- Official NSE JSON master actually fetched and resolved (NSE_INDEX|Nifty50 actual includes spaces: `NSE_INDEX|Nifty 50`; Nifty Bank likewise). Runtime on-demand IST-day cache. Read-only quote depth/feed timestamp/last-trade separate; V3 historical + today's intraday candles; missing values remain null.
- Upstox connection test uses a market quote, not profile/account API. Docs state Analytics Token market quotes/history do not require static IP, but account/portfolio categories may; linked official policy. No guarantees of account entitlement.
- Gated OAuth POST start/GET callback: permanent HTTPS origin required; state hashes, session/user binding,10min expiry, atomic consume, credential-change check, server-side token exchange, sanitized redirect. Application access log redacts callback queries. Provider token integration unverified without rotated credentials; interactive OAuth unverified without permanent origin.
- Broker registration panel: app name/description/copy controls, actual callback path/method; absolute URL and IPs pending, no postback needed for read-only route, Paytm deferred. Original PNG logo downloadable.
- `docs/UPSTOX_CONNECTION.md` describes exact rules and limitations. Design agent's generic IP/fallback advice corrected to verified implementation guidance.

## Prioritized backlog / release gates
### P0
1. Upstox revision regression completed:23 original-suite tests +9 addedprovider/API tests passed. Final mobile fixes increased menu/kill targets44px and changed narrow metrics to full-width; verify element-level overflow and confirm OAuth state invariants in isolated tests before finish.
2. User rotates exposed secrets, signs in to THEIR account, securely supplies Upstox Analytics/access token + Gemini key. No production proof until real-data smoke checks.
3. Permanent HTTPS origin if OAuth desired; register exact Upstox callback; confirm broker rules for selected token/API categories. No dedicated static outbound IP verified. Paytm requires separate verified adapter/registration.
4. No real execution enable path under any current setting.
### P1
Streaming/reconnect worker with source-quality tracking and unattended stop monitoring; durable queues/cache/rate limits; instrument/holiday/calendar validation; complete account/risk persistence hardening and backups; credential rotation/KMS; real provider failure testing; source licensing.
### P2
Options/news/macro/social, ML and calibrated ensemble, multi-horizon forecasts, realistic walk-forward/out-of-sample backtesting, shadow trading, full performance metrics and regime analysis, scheduled pre-market reports, PostgreSQL/Redis migration, multi-worker durability. Quantitative acceptance gates and compliance review before any future real-money work.

## Latest continuation — login-free runtime restoration
- User explicitly replaced the email/password UX with free browser-isolated access and bring-your-own API keys. Removed all app sign-in/modal/logout prompts. Legacy account endpoints remain for existing accounts; no existing account is exposed to a guest.
- Restored missing backend/frontend environment files (none existed), exact upstream v0.6.0 commit `1394a3f72aa4393e1a98f51b382434c4b4c2d972` HTTP archive, and documented client_factory/strong Trader extensions. Mongo initially contained no app data. Removed only unused template emergentintegrations dependency because its old OpenAI pin conflicted with upstream; pip check clean.
- POST `/api/auth/workspace` with exact APP_ORIGIN resumes an opaque secure HttpOnly cookie or creates a unique guest/account. CSRF required on ordinary writes; per-workspace credentials/account/ledger remain isolated. Guest cookie renews for 90 days; clearing cookies or expiry loses access. Never seed user API keys into every browser.
- Fixed user-reported server unavailable banner: frontend had started before .env restoration and compiled `undefined/api`; supervisor restart reloaded the environment.
- Added persistent light/dark/system controls, mobile refinements, dashboard setup links, browser-storage disclosure and upstream scope in Settings. Existing trading/risk/market/research setups preserved.
- Registration panel now displays copyable current website/callback from configured API origin with explicit preview-only warning. OAuth gate unchanged: permanent HTTPS BROKER_PUBLIC_ORIGIN required. IP fields explain market-data Analytics Token exemption; no reserved IP invented or account/trading eligibility claimed.
- User's Gemini key privately validated successfully through original GoogleClient quick model `gemini-3.5-flash-lite`; retained original deep model `gemini-3.1-pro-preview` but no full research validation without a broker token. Key exists only in ignored backend/.env as GEMINI_VALIDATION_KEY for validation, NOT a runtime global fallback. Users save their own keys through Connections. Rotate chat-exposed credentials.
- Verified GitHub repository linked by user: v0.6.0/latest commit matches restored source. Core graph preserved, but web terminal runs technical-only Indian snapshots; upstream news/social/fundamentals/backtesting are not automatically active. No real orders.
- Testing: 14 new backend API checks plus 44 existing tests passed; real Gemini quick test passed and temporary credential removed. Frontend agent validated routes, no login/no error banner, risk save/reload, kill toggle, provider switch, credential UI, isolation, themes, copy controls, mobile. Production frontend build passed. Independent final screenshots at 1920x800 and390x844 in both themes show no overflow. This is not certification for production trading.

## Known limitations
Gemini quick connection tested, but no demonstrated financial edge or live broker end-to-end validation. No automated model evaluation proof, no websocket, no unattended stops, no Paytm adapter, no postback receiver. Token costs unknown until pricing configured. Original predictions protected from edits through API, not from a Mongo administrator. Preview ingress rewrites cookie SameSite; independent Origin+CSRF controls tested. Outbound pool is not reserved per-app IP. Upstox research and fills remain gated by valid current source data.