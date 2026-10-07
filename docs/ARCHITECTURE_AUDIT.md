# Architecture audit — India AI Research Terminal

## Evidence and provenance
Audit performed against the latest stable GitHub release returned by the upstream Releases API: **TradingAgents v0.6.0**, commit `1394a3f72aa4393e1a98f51b382434c4b4c2d972` (release published 2026-10-03). The repository was cloned and checked out at that tag, not blindly merged. Source and Apache-2.0 LICENSE remain under `vendor/TradingAgents/`. No upstream NOTICE file was present at this tag; none was removed.

Secondary reference `https://github.com/pradeepsiddappa/indian-trading-agent` returned HTTP 404 from GitHub's repository API, and an anonymous clone failed. It may be private, renamed, or unavailable. **Its architecture, license, adaptations and reusable components cannot be verified. No code from it has been copied.** Request a public archive or access before claiming comparison completeness.

## Inspected implementation
| Area | Actual upstream evidence | Treatment |
|---|---|---|
| Configuration | `default_config.py`, environment override coercion, independent quick/deep providers, exact vendor chains | Reuse; supply per-run India configuration |
| Analysts | Four built-in analyst types: market, social, news, fundamentals | Reuse market first; unavailable source-dependent analysts not run |
| Orchestration | `graph/setup.py`: parallel analysts + Memory Log, Bull/Bear debate, Research Manager, Trader, three risk debaters, Portfolio Manager | Preserve nodes/edges; never substitute a buy/sell chatbot |
| Model routing | `llm_clients/factory.py`, Google client supports explicit per-instance API key | Extend constructor injection only; no shared user key in environment |
| Data routing | `dataflows/router.py` vendor registry, typed missing/unavailable errors; exact fallback chains | Register FYERS snapshot-backed tools; disable unselected vendors |
| Hard-coded Yahoo boundaries | verified snapshot and instrument identity bypass vendor registry | Override only these boundaries in isolated research worker; document explicitly |
| Memory | `memory/log.py`, `reflection.py`, `settlement.py` | Preserve; live daily reflection requires validated FYERS historical outcomes, not Yahoo fallback |
| Checkpoints | per-symbol SQLite `SqliteSaver`, config-aware signatures, successful-run cleanup | Preserve in per-user runtime directory |
| Reports | `reporting.py`, HTML rendering, Markdown sections, run settings | Reuse; API serves plain report text, never arbitrary HTML |
| Backtest | `backtest.py`: ticker/date grid, independent decisions, alpha scoring | Leave untouched; NOT a fill simulator, walk-forward or cost-adjusted portfolio backtest |
| Tests | ~100 upstream test modules, including graph end-to-end, date cutoffs, news/fundamental leakage, credentials, routing, checkpoint resume | Retain; run key offline tests plus platform tests |
| Docker | Python 3.13 multi-stage CLI image, non-root runtime, upstream compose | Preserve original; add surrounding application packaging separately |

## What upstream does not provide
FYERS, India intraday execution, normalized tick quality, paper-account cash ledger, Indian fees, deterministic risk limits, options microstructure, intraday forecast settlement, production web auth, encrypted multi-user secrets, Redis queues, walk-forward portfolio validation and calibration are surrounding-platform work. Upstream five-tier ratings are not calibrated probabilities or executable order plans. No probabilities should be inferred from rating prose.

Upstream memory is append-oriented but **settlement rewrites a pending entry**, and optional pruning exists. It is not the immutable prediction ledger requested here. Store original predictions separately with insert-only API and outcomes in a second collection.

## Modules to extend / replace / leave untouched
- Extend: provider boundary, data-quality schemas, per-instance model injection, configurable stronger Trader, India instrument identity, deterministic local technical snapshot.
- Replace at surrounding-platform boundary: CLI with web/API; US default data sources with explicitly selected FYERS. Do not rewrite orchestration, debate prompts, research/risk agents, report writers or checkpoint implementation.
- Leave untouched: upstream backtesting, social/fundamental/news vendor code, reflection and provider factories. Do not imply these have been validated for intraday India.
- API requirements: FYERS client ID and access token for quotes/history/profile/funds; source timestamps and liquidity for paper fills; Gemini API key for analysis; vendor news/calendar/options entitlements before enabling those features.

## Dependency risk
Initial combined install found FYERS SDK releases pinning `requests==2.31.0`, conflicting with upstream `requests>=2.32.4`. Use documented FYERS REST endpoints through HTTPX for first delivery. Do not downgrade upstream or force incompatible packages. A separately isolated official-SDK streaming worker is follow-up work; REST refresh is labelled polling, not WebSocket.

## First implementation plan
1. Secure per-user email/password session, encrypted credential vault, connection testing and sanitized errors.
2. FYERS read-only REST provider, normalization, candle chart, explicit stale/unknown/no-data states.
3. Upstream LangGraph research adapter, bounded isolated execution, deterministic technical tools, logs/reports/cost counters. No real-key verification possible until connected.
4. Atomic paper-account ledger, deterministic risk, cooldowns, duplicate suppression, kill switch; long liquid equities only initially. Indices are research-only; F&O waits for instrument/lot metadata and licensed data.
5. Immutable prediction storage with source snapshot hash; no invented calibrated probability. Out-of-sample and multi-horizon scoring are subsequent work.
6. Responsive terminal/dashboard, Markets, Signals, Paper Trading, Ledger, Risk, Journal, Health, Connections and Settings. Future research modules explicitly indicate prerequisites, not fabricated results.

## Go / No-Go
**NO-GO for real money**, regardless of elapsed time. No live broker-order path. No empirical edge, out-of-sample results or calibration claimed. Live provider smoke tests, failure-mode tests, licensed history, robust fee/spread models, holidays, distributed workers, backups, monitoring and regulatory eligibility remain release gates.