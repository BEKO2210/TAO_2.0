"""
Tests for ``src.orchestrator.capabilities`` (Capability + discovery)
and ``src.orchestrator.progress`` (heartbeat / progress reporting).

Both are LLM-free patterns picked up from the orchestration research:

- ``AGENT_CAPABILITIES``: agents (built-in or plug-in) declare what
  task types they can handle, the TaskRouter auto-registers them on
  ``register_agent``, and the dashboard / CLI can render
  "what can the swarm do?".
- ``report_progress(percent, message)``: long-running agents can
  heartbeat. The orchestrator records every event in ``run_log``
  and tracks last-seen timestamps for stale-task detection.
"""

from __future__ import annotations

import time

from src.orchestrator import SwarmOrchestrator
from src.orchestrator.capabilities import Capability, discover_capabilities
from src.orchestrator.progress import _OrchestratorProgressChannel

# ---------------------------------------------------------------------------
# Capability dataclass + discover_capabilities
# ---------------------------------------------------------------------------

def test_capability_to_dict_round_trip():
    cap = Capability(
        task_type="fish_check",
        description="score a subnet's fishiness",
        inputs={"subnet_id": "int"},
        outputs={"fishiness": "float"},
        tags=["scoring"],
    )
    d = cap.to_dict()
    assert d["task_type"] == "fish_check"
    assert d["description"].startswith("score")
    assert d["tags"] == ["scoring"]


def test_discover_caps_from_class_attribute():
    class _Stub:
        AGENT_CAPABILITIES = [
            Capability(task_type="alpha", description="A"),
            Capability(task_type="beta", description="B"),
        ]
        def run(self, t): return {}
        def get_status(self): return {}
        def validate_input(self, t): return True, ""

    caps = discover_capabilities(_Stub())
    assert [c.task_type for c in caps] == ["alpha", "beta"]


def test_discover_caps_accepts_dict_form():
    class _Stub:
        AGENT_CAPABILITIES = [{"task_type": "gamma", "description": "G"}]
        def run(self, t): return {}
        def get_status(self): return {}
        def validate_input(self, t): return True, ""

    caps = discover_capabilities(_Stub())
    assert len(caps) == 1
    assert caps[0].task_type == "gamma"


def test_discover_caps_skips_invalid_dict_entries(caplog):
    class _Stub:
        AGENT_CAPABILITIES = [
            {"not_a_real_field": "boom"},          # invalid → skipped
            {"task_type": "ok", "description": "OK"},
        ]
        def run(self, t): return {}
        def get_status(self): return {}
        def validate_input(self, t): return True, ""

    caps = discover_capabilities(_Stub())
    assert [c.task_type for c in caps] == ["ok"]


def test_discover_caps_returns_empty_when_no_declaration():
    class _Stub:
        def run(self, t): return {}
        def get_status(self): return {}
        def validate_input(self, t): return True, ""

    assert discover_capabilities(_Stub()) == []


# ---------------------------------------------------------------------------
# TaskRouter auto-registration
# ---------------------------------------------------------------------------

class _CapabilityAgent:
    """A minimal agent that declares two capabilities."""

    AGENT_NAME = "fish_test_agent"
    AGENT_VERSION = "1.0.0"
    AGENT_CAPABILITIES = [
        Capability(
            task_type="fish_check",
            description="Assess subnet fishiness",
            inputs={"subnet_id": "int"},
            outputs={"fishiness": "float"},
            tags=["scoring", "demo"],
        ),
        Capability(
            task_type="fish_history",
            description="Historical fishiness time-series",
            tags=["history"],
        ),
    ]

    def __init__(self, config=None):
        self.config = config or {}
        self.calls = 0

    def run(self, task):
        self.calls += 1
        return {"status": "complete", "task_type": task.get("type")}

    def get_status(self):
        return {"state": "idle"}

    def validate_input(self, task):
        return True, ""


def test_task_router_auto_registers_capabilities():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(_CapabilityAgent())

    # The router now knows both fish_check and fish_history → fish_test_agent
    assert orch.task_router.list_task_types().count("fish_check") == 1
    assert "fish_history" in orch.task_router.list_task_types()


def test_capability_routing_executes_via_orchestrator():
    orch = SwarmOrchestrator({"use_mock_data": True})
    agent = _CapabilityAgent()
    orch.register_agent(agent)

    out = orch.execute_task({"type": "fish_check", "subnet_id": 12})
    assert out["status"] == "success"
    assert agent.calls == 1


def test_default_task_map_wins_on_conflict():
    """An agent's capability MUST NOT silently override
    _DEFAULT_TASK_MAP. The curated default routing wins."""
    class _Hijacker:
        AGENT_NAME = "hijacker_agent"
        AGENT_VERSION = "1.0.0"
        # Try to claim system_check, which is already mapped to
        # system_check_agent in _DEFAULT_TASK_MAP.
        AGENT_CAPABILITIES = [Capability(task_type="system_check")]
        def __init__(self, config=None): self.config = config or {}
        def run(self, t): return {"status": "complete"}
        def get_status(self): return {"state": "idle"}
        def validate_input(self, t): return True, ""

    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(_Hijacker())
    # The default mapping must still point at system_check_agent
    assert orch.task_router._task_map["system_check"] == "system_check_agent"


def test_list_capabilities_groups_by_agent():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(_CapabilityAgent())
    caps = orch.task_router.list_capabilities()
    assert len(caps) == 2
    assert all(c["agent"] == "fish_test_agent" for c in caps)


# ---------------------------------------------------------------------------
# Progress / heartbeat
# ---------------------------------------------------------------------------

class _ProgressAgent:
    """Agent that calls report_progress during its run."""

    AGENT_NAME = "progress_test_agent"
    AGENT_VERSION = "1.0.0"

    def __init__(self, config=None):
        self.config = config or {}
        # Will be filled by orchestrator.register_agent
        self.report_progress = None

    def run(self, task):
        for i in range(3):
            self.report_progress(
                percent=(i + 1) / 3 * 100,
                message=f"step {i+1}/3",
            )
        return {"status": "complete"}

    def get_status(self):
        return {"state": "idle"}

    def validate_input(self, task):
        return True, ""


def test_orchestrator_injects_report_progress_on_register():
    orch = SwarmOrchestrator({"use_mock_data": True})
    agent = _ProgressAgent()
    assert agent.report_progress is None
    orch.register_agent(agent)
    assert callable(agent.report_progress)


def test_progress_events_land_in_run_log():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(_ProgressAgent())
    orch.task_router._task_map["progress_task"] = "progress_test_agent"

    orch.execute_task({"type": "progress_task"})

    progress_events = [e for e in orch.run_log
                       if e.get("event_type") == "progress"]
    assert len(progress_events) == 3
    assert progress_events[0]["agent_name"] == "progress_test_agent"
    assert progress_events[0]["message"] == "step 1/3"
    assert progress_events[2]["percent"] == 100.0


def test_progress_percent_clamped_to_0_100():
    """Out-of-range percentages get clamped silently."""
    sink_log = []
    chan = _OrchestratorProgressChannel(
        log_event=lambda **kw: sink_log.append(kw),
    )
    chan.report("agent", percent=150, message="too high")
    chan.report("agent", percent=-10, message="too low")
    chan.report("agent", percent="not a number", message="garbage")

    assert sink_log[0]["percent"] == 100.0
    assert sink_log[1]["percent"] == 0.0
    assert sink_log[2]["percent"] is None  # garbage → None


def test_last_progress_at_tracks_per_agent():
    chan = _OrchestratorProgressChannel(log_event=lambda **kw: None)
    assert chan.last_progress_at("alpha") is None

    chan.report("alpha", percent=10)
    chan.report("beta", percent=50)
    assert chan.last_progress_at("alpha") is not None
    assert chan.last_progress_at("beta") is not None


def test_stale_agents_returns_only_those_past_threshold():
    chan = _OrchestratorProgressChannel(log_event=lambda **kw: None)
    chan.report("recent", percent=10)
    # Force "ancient" to look old by patching its timestamp directly
    chan.report("ancient", percent=10)
    chan._last_progress["ancient"] = time.time() - 60.0

    stale = chan.stale_agents(threshold_seconds=10.0)
    names = [s[0] for s in stale]
    assert "ancient" in names
    assert "recent" not in names


def test_progress_reporter_is_bound_to_agent_name():
    """make_reporter_for binds the reporter to a single agent —
    call sites can't accidentally cross-report."""
    chan = _OrchestratorProgressChannel(log_event=lambda **kw: None)
    rep_alpha = chan.make_reporter_for("alpha")
    rep_alpha(percent=42, message="alpha-only")
    assert chan.last_progress_at("alpha") is not None
    assert chan.last_progress_at("beta") is None  # didn't leak


# ---------------------------------------------------------------------------
# Plug-ins can declare AGENT_CAPABILITIES too (composes with PR #20)
# ---------------------------------------------------------------------------

def test_plugin_declared_capabilities_become_routable(tmp_path):
    """A user plug-in (loaded via load_plugins) gets its
    AGENT_CAPABILITIES auto-registered just like a built-in."""
    src = '''
from src.orchestrator.capabilities import Capability

AGENT_NAME = "fish_plugin_agent"
AGENT_VERSION = "0.1.0"
AGENT_CAPABILITIES = [
    Capability(
        task_type="fish_plugin_check",
        description="Plug-in fishiness check",
        tags=["plugin", "demo"],
    ),
]


class FishPluginAgent:
    def __init__(self, config=None): self.config = config or {}
    def run(self, t): return {"status": "complete", "task_type": t.get("type")}
    def get_status(self): return {"state": "idle"}
    def validate_input(self, t): return True, ""
'''
    (tmp_path / "fish_plugin_agent.py").write_text(src)

    from src.orchestrator import load_plugins
    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[tmp_path], entry_point_group=None)

    assert "fish_plugin_agent" in summary.loaded
    assert "fish_plugin_check" in orch.task_router.list_task_types()

    out = orch.execute_task({"type": "fish_plugin_check"})
    assert out["status"] == "success"
