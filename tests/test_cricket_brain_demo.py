"""
End-to-end regression test for the CricketBrain demo plug-in
(``examples/cricket_brain/``).

This is the smoke test that proves the whole plug-in pipeline works
from a path that's NOT under ``src/`` — exactly the position a user's
external repo would be in. If anything in the loader / agent contract
breaks, this test catches it.

Concretely, the test:

1. Locates ``examples/cricket_brain/`` on disk.
2. Loads it via ``load_plugins(orch, paths=[...])`` — the same call
   a user would make.
3. Verifies registration: ``cricket_brain_agent`` is in the
   orchestrator's agents dict, the context-bus injection happened,
   and the SPEC.md contract is in place.
4. Exercises three scoring scenarios (no text, explicit text,
   context-fed) and checks the output shape + values.
5. Verifies the safety guarantee: DANGER actions are still blocked
   even with the plug-in registered.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.agents import SubnetDiscoveryAgent
from src.orchestrator import (
    AgentContext,
    SwarmOrchestrator,
    load_plugins,
)


_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "examples" / "cricket_brain"


def _load_orch_with_cricket_brain(use_subnet_discovery: bool = False) -> SwarmOrchestrator:
    orch = SwarmOrchestrator({"use_mock_data": True})
    if use_subnet_discovery:
        orch.register_agent(SubnetDiscoveryAgent({"use_mock_data": True}))
    summary = load_plugins(orch, paths=[_PLUGIN_DIR], entry_point_group=None)
    assert "cricket_brain_agent" in summary.loaded, summary.as_dict()
    return orch


# ---------------------------------------------------------------------------
# 1. Discovery + registration
# ---------------------------------------------------------------------------

def test_plugin_directory_exists():
    """Sanity: the example dir is checked into the repo at the
    expected location."""
    assert _PLUGIN_DIR.exists(), f"missing: {_PLUGIN_DIR}"
    assert (_PLUGIN_DIR / "cricket_brain_agent.py").exists()
    assert (_PLUGIN_DIR / "README.md").exists()


def test_load_plugins_picks_up_cricket_brain():
    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[_PLUGIN_DIR], entry_point_group=None)
    assert summary.loaded == ["cricket_brain_agent"]
    assert summary.errors == []
    assert "cricket_brain_agent" in orch.agents


def test_loaded_plugin_satisfies_spec_md_contract():
    """The agent class must expose run / get_status / validate_input
    + AGENT_NAME / AGENT_VERSION."""
    orch = _load_orch_with_cricket_brain()
    agent = orch.agents["cricket_brain_agent"]
    for method in ("run", "get_status", "validate_input"):
        assert callable(getattr(agent, method, None)), (
            f"missing method: {method}"
        )
    status = agent.get_status()
    assert status["agent_name"] == "cricket_brain_agent"
    assert status["state"] == "idle"
    assert status["calls"] == 0


def test_loaded_plugin_received_context_injection():
    """The orchestrator wires self.context onto the plug-in at
    register time — same pull-bus as built-ins."""
    orch = _load_orch_with_cricket_brain()
    agent = orch.agents["cricket_brain_agent"]
    assert isinstance(agent.context, AgentContext)
    assert agent.context is orch.context


# ---------------------------------------------------------------------------
# 2. Domain logic
# ---------------------------------------------------------------------------

def test_cricket_brain_no_vibes_for_synthetic_text():
    """A subnet id with no context data and no explicit text scores 0
    (the synthesised placeholder ``subnet_X placeholder description``
    contains no cricket tokens)."""
    orch = _load_orch_with_cricket_brain()
    out = orch.agents["cricket_brain_agent"].run({
        "type": "cricket_vibes",
        "subnet_id": 12,
    })
    assert out["status"] == "complete"
    assert out["vibes_score"] == 0.0
    assert out["verdict"] == "NO_VIBES"
    assert out["matched_tokens"] == []
    assert out["context_source"] == "synthesized"


def test_cricket_brain_strong_vibes_for_explicit_text():
    """Lots of cricket tokens → STRONG_VIBES (score >= 60)."""
    orch = _load_orch_with_cricket_brain()
    out = orch.agents["cricket_brain_agent"].run({
        "type": "cricket_vibes",
        "text": (
            "wicket pitch over innings bowl spin stump yorker "
            "googly duck boundary century lbw powerplay bat cricket"
        ),
    })
    assert out["status"] == "complete"
    # 16 unique tokens × 6 pts each, capped at 100 → 96
    assert out["vibes_score"] >= 90
    assert out["verdict"] == "STRONG_VIBES"
    # Every token should match
    assert len(out["matched_tokens"]) >= 10


def test_cricket_brain_picks_up_subnet_discovery_via_context():
    """When subnet_discovery_agent has run first, cricket_brain reads
    the published subnets from the context bus instead of synthesising."""
    orch = _load_orch_with_cricket_brain(use_subnet_discovery=True)

    # Populate the context with a fake subnet that's full of cricket
    # words. (We patch the orchestrator's context directly rather than
    # running the real subnet_discovery_agent — the exact mock fixture
    # of the discovery agent doesn't matter to this test.)
    orch.context.publish("subnet_discovery_agent", {
        "subnets": [
            {
                "netuid": 99,
                "name": "Wicket-Spin Bowling",
                "description": "Pitch innings boundary century powerplay",
            },
        ],
    })

    out = orch.agents["cricket_brain_agent"].run({
        "type": "cricket_vibes",
        "subnet_id": 99,
    })
    assert out["status"] == "complete"
    assert out["context_source"] == "subnet_discovery_agent"
    # 7 cricket tokens (wicket, spin, bowl, pitch, innings, boundary,
    # century, powerplay) → 8 hits × 6 = 48 → MIXED_VIBES at minimum
    assert out["vibes_score"] >= 30
    assert "wicket" in out["matched_tokens"]
    assert "boundary" in out["matched_tokens"]


def test_cricket_brain_validate_input_rejects_bad_subnet_id():
    orch = _load_orch_with_cricket_brain()
    out = orch.agents["cricket_brain_agent"].run({
        "type": "cricket_vibes",
        "subnet_id": "not-an-int",
    })
    assert out["status"] == "error"
    assert "subnet_id" in out["reason"]


# ---------------------------------------------------------------------------
# 3. Safety: plug-in does NOT get to bypass the gate
# ---------------------------------------------------------------------------

def test_danger_actions_still_blocked_with_cricket_brain_loaded():
    """Loading a plug-in must not raise its trust level. DANGER
    actions remain blocked at the gate, BEFORE reaching any agent."""
    orch = _load_orch_with_cricket_brain()
    out = orch.execute_task({"type": "execute_trade", "amount": 100})
    assert out["status"] == "blocked"
    assert out["classification"] == "DANGER"


def test_cricket_brain_run_call_count_increments():
    """get_status reports a calls counter — useful for the dashboard."""
    orch = _load_orch_with_cricket_brain()
    agent = orch.agents["cricket_brain_agent"]
    for _ in range(3):
        agent.run({"type": "cricket_vibes", "text": "bat"})
    assert agent.get_status()["calls"] == 3
