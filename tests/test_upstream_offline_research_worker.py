"""Offline upstream integration test for research_worker graph and client-factory wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

import sys

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/vendor/TradingAgents")

import research_worker  # noqa: E402
from tradingagents.dataflows.vendors.yahoo import market as yahoo_market  # noqa: E402


class ScriptedModel(BaseChatModel):
    """Simple scripted model: execute tools once, then return deterministic text."""

    tools: tuple = ()
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"tools": tuple(tools)})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(1)
        if self.tools and not isinstance(messages[-1], ToolMessage):
            calls = []
            for i, tool in enumerate(self.tools):
                schema_props = tool.tool_call_schema.model_json_schema().get("properties", {})
                args = {
                    "symbol": "RELIANCE.NS",
                    "ticker": "RELIANCE.NS",
                    "curr_date": "2026-01-09",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-09",
                    "indicator": "rsi",
                    "topic": "none",
                    "freq": "quarterly",
                    "as_of_date": "2026-01-09",
                }
                calls.append({"name": tool.name, "id": f"call_{i}", "args": {k: v for k, v in args.items() if k in schema_props}})
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=calls))])
        text = "Report.\n\n**Rating**: Overweight\n\nFINAL TRANSACTION PROPOSAL: **BUY**"
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


class _Client:
    def __init__(self, model):
        self._model = model

    def get_llm(self):
        return self._model


def test_research_worker_runs_offline_with_patched_client_factory(monkeypatch, tmp_path):
    model = ScriptedModel()
    monkeypatch.setattr(research_worker, "create_tier_client", lambda config, tier, **kw: _Client(model))

    def _no_yahoo(*_args, **_kwargs):
        raise AssertionError("Yahoo should never be called in this offline run")

    monkeypatch.setattr(yahoo_market.yf, "Ticker", _no_yahoo)

    start = 1736200000
    candles = []
    for i in range(300):
        base = 2500 + i * 0.7
        ts = start + i * 300
        candles.append(
            {
                "symbol": "NSE:RELIANCE-EQ",
                "timestamp": "2026-01-09T10:00:00+00:00",
                "time": ts,
                "open": base,
                "high": base + 2,
                "low": base - 2,
                "close": base + 0.4,
                "volume": 100000 + i,
            }
        )

    payload = {
        "snapshot": {
            "candles": candles,
            "quote": {
                "symbol": "NSE:RELIANCE-EQ",
                "ltp": 2600,
                "source_timestamp": "2026-01-09T10:00:00+00:00",
            },
            "cutoff": "2026-01-09T10:00:00+00:00",
        },
        "user_id": "offline-user",
        "api_key": "TEST_KEY",
        "run_id": "run-1",
        "quick_model": "gemini-3.5-flash-lite",
        "deep_model": "gemini-3.1-pro-preview",
        "runtime_dir": str(tmp_path),
        "ticker": "RELIANCE.NS",
    }

    result = research_worker.run(payload)
    assert result["rating"] in {"Overweight", "Buy", "Hold", "Underweight", "Sell"}
    assert "report" in result and result["report"].strip()
    assert isinstance(result["usage"], list)
    nodes = result.get("nodes", [])
    assert nodes
    lowered = " ".join(str(n).lower() for n in nodes)
    assert "market" in lowered
    assert "portfolio" in lowered or "manager" in lowered
    assert "aggressive analyst" in lowered and "neutral analyst" in lowered and "conservative analyst" in lowered

    reports_root = Path(tmp_path) / "offline-user" / "reports" / "run-1"
    assert reports_root.exists()
    assert model.calls, "Model should be used through patched client_factory"
