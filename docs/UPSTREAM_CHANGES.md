# Minimal upstream extension record

The original Apache-2.0 source remains intact except these explicitly documented additions:
1. `graph/trading_graph.py`: optional `client_factory` constructor parameter enables per-instance Google API keys without process-global credentials. Default behavior unchanged. Optional `strong_trader` configuration selects the deep model for Trader.
2. `graph/setup.py`: optional `trader_llm` parameter; default remains upstream quick model. Graph nodes, edges and analyst/researcher/risk prompts unchanged.

Application-owned `research_worker.py` subclasses the graph only at India instrument identity and intraday memory settlement boundaries. Runtime provider registration and verified snapshot substitution occur inside a short-lived isolated process, not the shared web server. Frozen FYERS 5-minute candles are the only price data accessible to tools. No external Yahoo lookup or fallback is permitted. Upstream daily reflection is retained in source but is not auto-run against incompatible intraday data. Previously validated lessons are read point-in-time; outcome evaluation is in the separate immutable ledger.

Full upstream historical backtesting and reflection remain available for later adaptation, not silently claimed to be India-intraday ready.