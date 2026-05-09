"""
Tests for ``src.orchestrator.plugin_loader``.

The loader's contract:

1. Path-based discovery imports any ``*_agent.py`` file in the listed
   directories, finds the agent class via SPEC.md contract, and
   registers it with the orchestrator.
2. Entry-point discovery resolves ``[project.entry-points."tao.agents"]``
   declarations and registers them.
3. Plug-ins that don't satisfy the contract are skipped with a logged
   reason — never silently registered.
4. Name conflicts are handled per ``on_conflict`` policy
   (skip / replace / error).
5. Plug-ins receive the orchestrator's ``AgentContext`` automatically
   (via the existing ``register_agent`` injection).
6. Plug-ins go through the ApprovalGate like any built-in — loading
   does not raise their trust level.
"""

from __future__ import annotations

import pytest

from src.orchestrator import (
    AgentContext,
    ON_CONFLICT_ERROR,
    ON_CONFLICT_REPLACE,
    ON_CONFLICT_SKIP,
    PluginLoadSummary,
    SwarmOrchestrator,
    load_plugins,
)


# ---------------------------------------------------------------------------
# Helpers — write a synthetic plug-in to disk for path-based loading
# ---------------------------------------------------------------------------

_VALID_PLUGIN_SRC = '''
"""A test plug-in with the minimum SPEC.md-compliant shape."""

AGENT_NAME = "{name}"
AGENT_VERSION = "0.1.0"


class {cls_name}:
    """Minimal SPEC.md-compliant plug-in agent."""

    def __init__(self, config=None):
        self.config = config or {{}}
        self._status = "idle"
        self._calls = 0

    def run(self, task):
        self._calls += 1
        self._status = "complete"
        return {{
            "status": "complete",
            "agent": AGENT_NAME,
            "task_type": task.get("type"),
            "calls": self._calls,
        }}

    def get_status(self):
        return {{
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "state": self._status,
        }}

    def validate_input(self, task):
        if not isinstance(task, dict):
            return False, "task must be a dict"
        return True, ""
'''


def _write_plugin(tmp_path, filename: str, name: str, cls_name: str | None = None) -> None:
    cls_name = cls_name or "".join(p.capitalize() for p in name.split("_")) + "Agent"
    src = _VALID_PLUGIN_SRC.format(name=name, cls_name=cls_name)
    (tmp_path / filename).write_text(src)


# ---------------------------------------------------------------------------
# Path-based discovery
# ---------------------------------------------------------------------------

def test_load_plugins_from_path_registers_valid_agent(tmp_path):
    _write_plugin(tmp_path, "example_one_agent.py", "example_one_agent", "ExampleOneAgent")

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[tmp_path], entry_point_group=None)

    assert summary.loaded == ["example_one_agent"]
    assert summary.skipped == []
    assert summary.errors == []
    assert "example_one_agent" in orch.agents


def test_path_loaded_agent_can_be_run_via_orchestrator(tmp_path):
    _write_plugin(tmp_path, "example_two_agent.py", "example_two_agent",
                  "ExampleTwoAgent")

    orch = SwarmOrchestrator({"use_mock_data": True})
    load_plugins(orch, paths=[tmp_path], entry_point_group=None)

    # The router doesn't know the new task type, so call the agent
    # directly — but verify it's wired into the orchestrator's registry.
    agent = orch.agents["example_two_agent"]
    out = agent.run({"type": "ping"})
    assert out["status"] == "complete"
    assert out["agent"] == "example_two_agent"


def test_loaded_plugin_has_context_injected(tmp_path):
    _write_plugin(tmp_path, "ctx_probe_agent.py", "ctx_probe_agent", "CtxProbeAgent")

    orch = SwarmOrchestrator({"use_mock_data": True})
    load_plugins(orch, paths=[tmp_path], entry_point_group=None)

    plug = orch.agents["ctx_probe_agent"]
    assert isinstance(plug.context, AgentContext)
    assert plug.context is orch.context  # same shared instance


def test_load_plugins_loads_multiple_files(tmp_path):
    _write_plugin(tmp_path, "alpha_agent.py", "alpha_agent", "AlphaAgent")
    _write_plugin(tmp_path, "beta_agent.py", "beta_agent", "BetaAgent")

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[tmp_path], entry_point_group=None)

    assert sorted(summary.loaded) == ["alpha_agent", "beta_agent"]


def test_non_agent_files_are_ignored(tmp_path):
    """Files NOT matching ``*_agent.py`` are not picked up."""
    (tmp_path / "helpers.py").write_text("PI = 3.14159\n")
    _write_plugin(tmp_path, "real_agent.py", "real_agent", "RealAgent")

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[tmp_path], entry_point_group=None)
    assert summary.loaded == ["real_agent"]


def test_invalid_path_recorded_in_errors(tmp_path):
    nonexistent = tmp_path / "does_not_exist"
    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[nonexistent], entry_point_group=None)
    assert summary.loaded == []
    assert any("does not exist" in e["reason"] for e in summary.errors)


def test_env_var_paths_picked_up(tmp_path, monkeypatch):
    _write_plugin(tmp_path, "envvar_agent.py", "envvar_agent", "EnvvarAgent")
    monkeypatch.setenv("TAO_PLUGIN_PATHS", str(tmp_path))

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=None, entry_point_group=None)
    assert "envvar_agent" in summary.loaded


def test_pathsep_separated_env_var(tmp_path, monkeypatch):
    """Multiple paths in TAO_PLUGIN_PATHS, separated by os.pathsep."""
    import os
    a = tmp_path / "a"; a.mkdir()
    b = tmp_path / "b"; b.mkdir()
    _write_plugin(a, "left_agent.py", "left_agent", "LeftAgent")
    _write_plugin(b, "right_agent.py", "right_agent", "RightAgent")
    monkeypatch.setenv("TAO_PLUGIN_PATHS", f"{a}{os.pathsep}{b}")

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=None, entry_point_group=None)
    assert sorted(summary.loaded) == ["left_agent", "right_agent"]


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------

def test_plugin_without_required_methods_is_skipped(tmp_path):
    """A class that doesn't implement run/get_status/validate_input is
    not registered — but the loader doesn't crash."""
    bad = '''
AGENT_NAME = "broken_agent"
AGENT_VERSION = "0.1.0"

class BrokenAgent:
    """Missing run / get_status / validate_input."""
    pass
'''
    (tmp_path / "broken_agent.py").write_text(bad)

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[tmp_path], entry_point_group=None)
    assert summary.loaded == []
    assert summary.skipped, "broken plug-in must be skipped, not registered"


def test_plugin_without_agent_name_is_skipped(tmp_path):
    bad = '''
class NoNameAgent:
    def __init__(self, config=None): self.config = config or {}
    def run(self, task): return {"status": "ok"}
    def get_status(self): return {"state": "idle"}
    def validate_input(self, task): return True, ""
'''
    (tmp_path / "noname_agent.py").write_text(bad)

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[tmp_path], entry_point_group=None)
    assert summary.loaded == []


def test_import_error_recorded(tmp_path):
    (tmp_path / "broken_agent.py").write_text("import this_does_not_exist_123\n")

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[tmp_path], entry_point_group=None)
    assert summary.loaded == []
    assert any("import failed" in e["reason"] for e in summary.errors)


# ---------------------------------------------------------------------------
# Conflict policy
# ---------------------------------------------------------------------------

def test_on_conflict_skip_keeps_existing(tmp_path):
    _write_plugin(tmp_path, "dupe_agent.py", "dupe_agent", "DupeAgent")

    orch = SwarmOrchestrator({"use_mock_data": True})
    load_plugins(orch, paths=[tmp_path], entry_point_group=None)
    first = orch.agents["dupe_agent"]

    # Re-load with skip — must keep the first instance
    summary = load_plugins(
        orch, paths=[tmp_path], entry_point_group=None,
        on_conflict=ON_CONFLICT_SKIP,
    )
    assert orch.agents["dupe_agent"] is first
    assert any("already registered" in s["reason"] for s in summary.skipped)


def test_on_conflict_replace_swaps_in_new_one(tmp_path):
    _write_plugin(tmp_path, "swap_agent.py", "swap_agent", "SwapAgent")

    orch = SwarmOrchestrator({"use_mock_data": True})
    load_plugins(orch, paths=[tmp_path], entry_point_group=None)
    first = orch.agents["swap_agent"]

    summary = load_plugins(
        orch, paths=[tmp_path], entry_point_group=None,
        on_conflict=ON_CONFLICT_REPLACE,
    )
    assert orch.agents["swap_agent"] is not first
    assert "swap_agent" in summary.loaded


def test_on_conflict_error_raises(tmp_path):
    _write_plugin(tmp_path, "err_agent.py", "err_agent", "ErrAgent")

    orch = SwarmOrchestrator({"use_mock_data": True})
    load_plugins(orch, paths=[tmp_path], entry_point_group=None)
    with pytest.raises(ValueError, match="conflicts"):
        load_plugins(
            orch, paths=[tmp_path], entry_point_group=None,
            on_conflict=ON_CONFLICT_ERROR,
        )


# ---------------------------------------------------------------------------
# Entry-point discovery (mocked importlib.metadata)
# ---------------------------------------------------------------------------

class _FakeEntryPoint:
    """Minimal stand-in for ``importlib.metadata.EntryPoint``."""

    def __init__(self, name: str, group: str, target_cls):
        self.name = name
        self.group = group
        self._target = target_cls

    def load(self):
        return self._target


def test_entry_point_loads_agent_class(monkeypatch):
    """The loader resolves ``ep.load()`` to a class and registers it."""
    class ExampleViaEpAgent:
        AGENT_NAME = "example_via_ep"
        AGENT_VERSION = "0.1.0"

        def __init__(self, config=None): self.config = config or {}
        def run(self, task): return {"status": "complete"}
        def get_status(self): return {"state": "idle"}
        def validate_input(self, task): return True, ""

    fake_ep = _FakeEntryPoint("example_via_ep", "tao.agents", ExampleViaEpAgent)

    def fake_entry_points(*, group=None):
        if group == "tao.agents":
            return [fake_ep]
        return []

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[], entry_point_group="tao.agents")
    assert "example_via_ep" in summary.loaded
    assert "example_via_ep" in orch.agents


def test_entry_point_failed_load_recorded_as_error(monkeypatch):
    class _BoomEP:
        name = "boom"
        group = "tao.agents"
        def load(self):
            raise RuntimeError("simulated import explosion")

    def fake_entry_points(*, group=None):
        return [_BoomEP()]

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)

    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[], entry_point_group="tao.agents")
    assert summary.loaded == []
    assert any("simulated" in e["reason"] for e in summary.errors)


# ---------------------------------------------------------------------------
# Safety: plug-ins still go through the gate
# ---------------------------------------------------------------------------

def test_plugin_does_not_get_special_classification_treatment(tmp_path):
    """A plug-in cannot raise its own trust level. DANGER actions
    routed via this plug-in must still be blocked at the gate."""
    src = '''
AGENT_NAME = "evil_test_plugin"
AGENT_VERSION = "0.1.0"

class EvilTestPlugin:
    def __init__(self, config=None): self.config = config or {}
    def run(self, task): return {"status": "complete", "evil_did_run": True}
    def get_status(self): return {"state": "idle"}
    def validate_input(self, task): return True, ""
'''
    (tmp_path / "evil_test_plugin_agent.py").write_text(src)

    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    load_plugins(orch, paths=[tmp_path], entry_point_group=None)

    # Even with a plug-in registered, a DANGER task type the gate
    # knows about must still be blocked. The plug-in's run() must
    # NOT have been called.
    out = orch.execute_task({"type": "execute_trade", "amount": 100})
    assert out["status"] == "blocked"
    assert out.get("output", {}).get("evil_did_run") is None


# ---------------------------------------------------------------------------
# PluginLoadSummary smoke
# ---------------------------------------------------------------------------

def test_summary_as_dict_returns_plain_lists(tmp_path):
    _write_plugin(tmp_path, "summary_agent.py", "summary_agent", "SummaryAgent")
    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[tmp_path], entry_point_group=None)
    d = summary.as_dict()
    assert d["loaded"] == ["summary_agent"]
    assert d["skipped"] == []
    assert d["errors"] == []
    assert isinstance(summary, PluginLoadSummary)
