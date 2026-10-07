"""Isolated upstream graph execution. Input is passed over stdin, never a file.
The only outbound source during reasoning is the selected LLM; tools use frozen FYERS data.
"""
import copy
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from langchain_core.callbacks import BaseCallbackHandler
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients import create_tier_client
from tradingagents.agents import tools
from tradingagents.dataflows.router import VENDOR_METHODS
from quant import indicators

class UsageCounter(BaseCallbackHandler):
    def __init__(self):
        self.rows = []
    def on_llm_end(self, response, **kwargs):
        usage = None
        for generation in response.generations:
            for item in generation:
                usage = getattr(getattr(item, 'message', None), 'usage_metadata', None) or usage
        self.rows.append({'tokens': (usage or {}).get('total_tokens'), 'status': 'SUCCESS'})
    def on_llm_error(self, error, **kwargs):
        self.rows.append({'tokens': None, 'status': 'ERROR'})

class IndiaGraph(TradingAgentsGraph):
    def resolve_instrument_context(self, ticker, asset_type='stock', trade_date=None):
        return (f'Indian instrument {ticker}, NSE. PAPER RESEARCH ONLY. '
            'Inputs are completed 5-minute broker-provider bars; each indicator period denotes a BAR, not a day. '
            'News, macro, options and fundamentals are unavailable. Never infer their contents. '
            'No calibrated profit probability exists. Prefer NO TRADE when evidence is insufficient. '
            'Research opinions cannot override deterministic execution risk limits.')
    def _memory_step(self, state):
        return {'past_context': self.memory_log.get_past_context(state['company_of_interest'], as_of=state['trade_date']),
            'memory_note': 'Intraday outcome evaluation is in the immutable platform ledger. Daily reflection settlement is not enabled for this intraday feed.'}

def run(payload):
    snapshot = payload['snapshot']
    provider = snapshot.get('provider', 'FYERS')
    candles = snapshot['candles']
    cutoff = datetime.fromisoformat(snapshot['cutoff']).timestamp()
    if not candles or any(c['time'] + 300 > cutoff for c in candles):
        raise ValueError('Future or incomplete candle rejected')
    technical = indicators(candles)
    def stock(symbol, start_date, end_date):
        rows = [c for c in candles if start_date <= c['timestamp'][:10] <= end_date]
        return json.dumps({'provider': provider, 'interval': '5 minutes', 'cutoff': snapshot['cutoff'], 'candles': rows[-250:]})
    def indicator(symbol, name, curr_date, look_back_days=30):
        eligible = [c for c in candles if c['timestamp'][:10] <= curr_date]
        return json.dumps({'indicator': name, 'value': indicators(eligible).get(name), 'period_unit': '5-minute bars', 'source': provider})
    def verified(symbol, as_of_date, look_back_days=30):
        eligible = [c for c in candles if c['timestamp'][:10] <= as_of_date]
        return json.dumps({'source': provider, 'cutoff': snapshot['cutoff'], 'interval': '5 minutes',
            'latest': eligible[-1] if eligible else None, 'indicators': indicators(eligible), 'recent': eligible[-30:]})
    VENDOR_METHODS['get_stock_data']['india_snapshot'] = stock
    VENDOR_METHODS['get_indicators']['india_snapshot'] = indicator
    tools.build_verified_market_snapshot = verified
    root = Path(payload['runtime_dir']) / payload['user_id']
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(llm_provider='google', quick_think_llm=payload['quick_model'], deep_think_llm=payload['deep_model'],
        strong_trader=True, max_tool_rounds=3, max_tokens=2000, llm_max_retries=0, temperature=0,
        checkpoint_enabled=True, results_dir=str(root / 'reports'), data_cache_dir=str(root / 'cache'),
        memory_log_path=str(root / 'memory.md'), data_vendors={key:'india_snapshot' for key in DEFAULT_CONFIG['data_vendors']})
    usage = UsageCounter()
    factory = lambda config, tier, **kw: create_tier_client(config, tier, api_key=payload['api_key'], timeout=40, **kw)
    graph = IndiaGraph(selected_analysts=['market'], config=cfg, callbacks=[usage], client_factory=factory)
    ticker = payload['ticker']
    trade_date = datetime.fromisoformat(snapshot['cutoff']).astimezone(ZoneInfo('Asia/Kolkata')).strftime('%Y-%m-%d')
    state, rating = graph.propagate(ticker, trade_date)
    report_path = graph.save_reports(state, ticker, save_path=root / 'reports' / payload['run_id'], html=False)
    return {'rating': rating, 'report': report_path.read_text(), 'usage': usage.rows, 'indicators': technical,
        'nodes': list(graph.graph.get_graph().nodes)}

if __name__ == '__main__':
    try:
        result = run(json.loads(sys.stdin.read()))
        print('TERMINAL_RESULT=' + json.dumps(result))
    except Exception as exc:
        # Do not echo prompts, tokens, provider URLs or SDK exceptions.
        print('TERMINAL_RESULT=' + json.dumps({'error': f'Research failed ({type(exc).__name__}). Check model access, quota and provider status.'}))
        sys.exit(1)