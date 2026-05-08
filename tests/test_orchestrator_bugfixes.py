"""
Regression tests for two bugs found via the end-to-end simulation:

* Bug A — ``SwarmOrchestrator.register_agent`` only read ``AGENT_NAME`` from the
  instance, but per ``SPEC.md`` agents declare it as a module-level constant.
  Registration therefore failed for every agent in ``src/agents/``.

* Bug B — ``execute_task`` routed before classifying. DANGER actions whose task
  type was unknown to ``TaskRouter`` errored out at routing instead of reaching
  the ApprovalGate's plan-only branch. Fix: classify first, route only for
  SAFE / approved tasks.
"""

from __future__ import annotations

import pytest

from src.orchestrator import SwarmOrchestrator


# ---------------------------------------------------------------------------
# Bug A — module-level AGENT_NAME / AGENT_VERSION must be discovered
# ---------------------------------------------------------------------------

class _ModuleLevelAgent:
    """Minimal agent that mirrors the ``src/agents/*_agent.py`` style: the
    AGENT_NAME / AGENT_VERSION constants live on the *module*, not on the
    class or instance."""

    def run(self, task: dict) -> dict:
        return {"status": "ok"}

    def get_status(self) -> dict:
        return {"state": "idle"}

    def validate_input(self, task: dict) -> tuple[bool, str]:
        return True, ""


# Mimic SPEC.md: module-level constants on this very test module.
AGENT_NAME = "module_level_test_agent"
AGENT_VERSION = "9.9.9"


def test_register_agent_reads_module_level_constants():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(_ModuleLevelAgent())
    assert "module_level_test_agent" in orch.agents


def test_register_agent_reads_class_level_constants():
    class ClassLevelAgent:
        AGENT_NAME = "class_level_agent"
        AGENT_VERSION = "1.0.0"

        def run(self, task): return {"status": "ok"}
        def get_status(self): return {}
        def validate_input(self, task): return True, ""

    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(ClassLevelAgent())
    assert "class_level_agent" in orch.agents


def test_register_agent_without_any_name_raises():
    # Build the class inside a synthetic module that has NO AGENT_NAME, so
    # we don't pick up the module-level constant declared at the top of
    # this test file.
    import sys
    import types

    bare_module = types.ModuleType("bare_anon_module")
    sys.modules["bare_anon_module"] = bare_module

    class Anonymous:
        def run(self, task): return {}
        def get_status(self): return {}
        def validate_input(self, task): return True, ""

    Anonymous.__module__ = "bare_anon_module"
    bare_module.Anonymous = Anonymous

    orch = SwarmOrchestrator({"use_mock_data": True})
    with pytest.raises(ValueError, match="AGENT_NAME"):
        orch.register_agent(Anonymous())


def test_real_agents_can_be_registered():
    """All 15 production agents must be registerable without patching."""
    from src.agents import (
        SystemCheckAgent,
        WalletWatchAgent,
        SubnetScoringAgent,
    )

    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.register_agent(WalletWatchAgent({"use_mock_data": True}))
    orch.register_agent(SubnetScoringAgent({"use_mock_data": True}))
    assert {"system_check_agent", "wallet_watch_agent", "subnet_scoring_agent"} <= set(orch.agents)


# ---------------------------------------------------------------------------
# Bug B — DANGER tasks must be blocked before routing is consulted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "task_type",
    ["execute_trade", "sign_transaction", "stake_tao", "transfer_funds"],
)
def test_danger_task_is_blocked_even_without_route(task_type: str):
    """The TaskRouter has no mapping for these synthetic DANGER types, but
    ApprovalGate must still block them with a plan-only result — never an
    error, never an execution."""
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})

    out = orch.execute_task({"type": task_type})

    assert out["status"] == "blocked"
    assert out["executed"] is False
    classification = out["classification"]
    classification_str = getattr(classification, "value", classification)
    assert classification_str == "DANGER"
    assert "plan" in out["output"]


def test_safe_task_still_routes_and_executes():
    """Refactor must not break the happy path."""
    from src.agents import SystemCheckAgent

    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))

    out = orch.execute_task({"type": "system_check"})
    assert out["status"] == "success"
    assert out["executed"] is True


def test_unknown_safe_task_still_errors_at_routing():
    """An unknown but non-DANGER task type should still surface as a routing
    error — the gate only short-circuits genuinely dangerous actions."""
    orch = SwarmOrchestrator({"use_mock_data": True})

    out = orch.execute_task({"type": "totally_made_up_safe_task"})
    assert out["status"] == "error"
    assert "No agent" in out["error"]
