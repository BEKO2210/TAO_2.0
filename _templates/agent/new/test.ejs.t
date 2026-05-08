---
to: tests/test_<%= h.snake(name) %>_agent.py
---
"""Tests for <%= h.pascal(name) %>Agent."""

from src.agents.<%= h.snake(name) %>_agent import (
    <%= h.pascal(name) %>Agent,
    AGENT_NAME,
    AGENT_VERSION,
)


def test_agent_metadata():
    assert AGENT_NAME == "<%= h.snake(name) %>_agent"
    assert AGENT_VERSION == "1.0.0"


def test_agent_run_validates_input():
    agent = <%= h.pascal(name) %>Agent()
    result = agent.run({})
    assert result["status"] == "error"
    assert "task.type" in result["reason"]


def test_agent_run_returns_flat_dict_with_status():
    agent = <%= h.pascal(name) %>Agent()
    result = agent.run({"type": "ping"})
    # Convention: flat dict, top-level "status", no nested "result" wrapper.
    assert result["status"] == "complete"
    assert "result" not in result, "agent.run() must not wrap payload in 'result'"
    assert result["task_type"] == "ping"


def test_agent_get_status_reports_state():
    agent = <%= h.pascal(name) %>Agent()
    status = agent.get_status()
    assert status["agent_name"] == AGENT_NAME
    assert status["state"] == "idle"
