---
to: <%= out_dir %>/test_<%= h.snake(name) %>_agent.py
---
"""Tests for the <%= h.pascal(name) %> plug-in."""

import importlib.util
from pathlib import Path

import pytest


def _load(plugin_name: str = "<%= h.snake(name) %>_agent"):
    """Load the plug-in module by file path so the test runs without
    the plug-in being installed."""
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        plugin_name, here / f"{plugin_name}.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_exposes_agent_name_and_version():
    mod = _load()
    assert mod.AGENT_NAME == "<%= h.snake(name) %>_agent"
    assert isinstance(mod.AGENT_VERSION, str)


def test_run_validates_input():
    mod = _load()
    agent = mod.<%= h.pascal(name) %>Agent()
    bad = agent.run({})
    assert bad["status"] == "error"


def test_run_succeeds_on_valid_task():
    mod = _load()
    agent = mod.<%= h.pascal(name) %>Agent()
    out = agent.run({"type": "ping"})
    assert out["status"] == "complete"
    assert out["task_type"] == "ping"


def test_get_status_reports_idle_after_init():
    mod = _load()
    agent = mod.<%= h.pascal(name) %>Agent()
    status = agent.get_status()
    assert status["state"] == "idle"
    assert status["calls"] == 0
