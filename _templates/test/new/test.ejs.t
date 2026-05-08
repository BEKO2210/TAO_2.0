---
to: tests/test_<%= h.snake(name) %>.py
---
"""Tests for <%= h.snake(name) %> (<%= kind %>)."""

import pytest

<% if (kind === 'agent') { -%>
from src.agents.<%= h.snake(name) %>_agent import <%= h.pascal(name) %>Agent


def test_agent_runs():
    agent = <%= h.pascal(name) %>Agent()
    result = agent.run({"type": "ping"})
    assert result["status"] == "ok"
<% } else if (kind === 'collector') { -%>
from src.collectors.<%= h.snake(name) %> import <%= h.pascal(name) %>Collector


def test_collector_returns_payload():
    collector = <%= h.pascal(name) %>Collector()
    payload = collector.collect()
    assert "collector" in payload
<% } else if (kind === 'scoring') { -%>
from src.scoring.<%= h.snake(name) %>_score import <%= h.pascal(name) %>Scorer


def test_scorer_returns_score():
    scorer = <%= h.pascal(name) %>Scorer(weights={"x": 1.0})
    out = scorer.score({"x": 50})
    assert 0.0 <= out["score"] <= 100.0
<% } else if (kind === 'orchestrator') { -%>
from src.orchestrator.<%= h.snake(name) %> import *  # noqa: F401,F403


def test_module_imports():
    pass
<% } else { -%>
def test_placeholder():
    # TODO: write real tests
    assert True
<% } -%>
