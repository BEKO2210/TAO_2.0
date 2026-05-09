"""
End-to-end regression test for the SubnetRepoHealth example plug-in
(``examples/subnet_repo_health/``).

This is the smoke test that proves the whole plug-in pipeline works
from a path that's NOT under ``src/`` — exactly the position a user's
external repo would be in. If anything in the loader / agent contract
breaks, this test catches it.

Concretely, the test:

1. Locates ``examples/subnet_repo_health/`` on disk.
2. Loads it via ``load_plugins(orch, paths=[...])`` — the same call
   a user would make.
3. Verifies registration: ``subnet_repo_health_agent`` is in the
   orchestrator's agents dict, the context-bus injection happened,
   and the SPEC.md contract is in place.
4. Exercises three scoring scenarios (direct repo URL, archived repo,
   context-fed via subnet_discovery) and checks output shape + values.
5. Verifies the safety guarantee: DANGER actions are still blocked
   even with the plug-in registered.
"""

from __future__ import annotations

from pathlib import Path

from src.agents import SubnetDiscoveryAgent
from src.orchestrator import (
    AgentContext,
    SwarmOrchestrator,
    load_plugins,
)


_PLUGIN_DIR = (
    Path(__file__).resolve().parent.parent / "examples" / "subnet_repo_health"
)


def _load_orch_with_plugin(use_subnet_discovery: bool = False) -> SwarmOrchestrator:
    orch = SwarmOrchestrator({"use_mock_data": True})
    if use_subnet_discovery:
        orch.register_agent(SubnetDiscoveryAgent({"use_mock_data": True}))
    summary = load_plugins(orch, paths=[_PLUGIN_DIR], entry_point_group=None)
    assert "subnet_repo_health_agent" in summary.loaded, summary.as_dict()
    return orch


# ---------------------------------------------------------------------------
# 1. Discovery + registration
# ---------------------------------------------------------------------------

def test_plugin_directory_exists():
    """Sanity: the example dir is checked into the repo at the
    expected location."""
    assert _PLUGIN_DIR.exists(), f"missing: {_PLUGIN_DIR}"
    assert (_PLUGIN_DIR / "subnet_repo_health_agent.py").exists()
    assert (_PLUGIN_DIR / "README.md").exists()


def test_load_plugins_picks_up_subnet_repo_health():
    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=[_PLUGIN_DIR], entry_point_group=None)
    assert summary.loaded == ["subnet_repo_health_agent"]
    assert summary.errors == []
    assert "subnet_repo_health_agent" in orch.agents


def test_loaded_plugin_satisfies_spec_md_contract():
    """The agent class must expose run / get_status / validate_input
    + AGENT_NAME / AGENT_VERSION."""
    orch = _load_orch_with_plugin()
    agent = orch.agents["subnet_repo_health_agent"]
    for method in ("run", "get_status", "validate_input"):
        assert callable(getattr(agent, method, None)), f"missing method: {method}"
    status = agent.get_status()
    assert status["agent_name"] == "subnet_repo_health_agent"
    assert status["state"] == "idle"
    assert status["calls"] == 0


def test_loaded_plugin_received_context_injection():
    """The orchestrator wires self.context onto the plug-in at
    register time — same pull-bus as built-ins."""
    orch = _load_orch_with_plugin()
    agent = orch.agents["subnet_repo_health_agent"]
    assert isinstance(agent.context, AgentContext)
    assert agent.context is orch.context


# ---------------------------------------------------------------------------
# 2. Domain logic
# ---------------------------------------------------------------------------

def test_repo_health_with_direct_repo_url():
    """Caller-supplied repo URL takes priority over context lookup."""
    orch = _load_orch_with_plugin()
    out = orch.agents["subnet_repo_health_agent"].run({
        "type": "subnet_repo_health",
        "repo_url": "https://github.com/opentensor/bittensor",
    })
    assert out["status"] == "complete"
    assert out["repo_url"] == "https://github.com/opentensor/bittensor"
    assert out["repo_source"] == "task"
    assert isinstance(out["repo_health_score"], float)
    assert 0.0 <= out["repo_health_score"] <= 100.0
    assert out["verdict"] in {"HEALTHY", "MAINTAINED", "STALE", "DORMANT", "ABANDONED"}
    assert out["score_components"]["stars"] == 1100
    assert out["data_mode"] == "mock"


def test_repo_health_no_repo_returns_no_repo_verdict():
    """When neither task['repo_url'] nor a context entry is available,
    the agent reports NO_REPO with score 0 — graceful degradation."""
    orch = _load_orch_with_plugin()
    out = orch.agents["subnet_repo_health_agent"].run({
        "type": "subnet_repo_health",
        "subnet_id": 999,  # no context entry for this netuid
    })
    assert out["status"] == "complete"
    assert out["verdict"] == "NO_REPO"
    assert out["repo_health_score"] == 0.0
    assert out["repo_source"] == "missing"


def test_repo_health_pulls_repo_url_from_subnet_discovery_context():
    """When subnet_discovery_agent has run first, the plug-in reads
    the published repo_url from the context bus."""
    orch = _load_orch_with_plugin(use_subnet_discovery=True)

    orch.context.publish("subnet_discovery_agent", {
        "subnets": [
            {
                "netuid": 1,
                "name": "Text Prompting",
                "repo_url": "https://github.com/opentensor/bittensor",
            },
        ],
    })

    out = orch.agents["subnet_repo_health_agent"].run({
        "type": "subnet_repo_health",
        "subnet_id": 1,
    })
    assert out["status"] == "complete"
    assert out["repo_source"] == "subnet_discovery_agent"
    assert out["repo_url"] == "https://github.com/opentensor/bittensor"
    assert isinstance(out["repo_health_score"], float)


def test_repo_health_archived_repo_collapses_to_zero():
    """An archived repo is, by construction, ABANDONED — score 0
    regardless of stars or recency. Stub the collector to return an
    archived repo to lock this in."""
    from examples.subnet_repo_health.subnet_repo_health_agent import (
        SubnetRepoHealthAgent,
    )

    class _StubCollector:
        def get_repo_info(self, url):
            return {
                "full_name": "old/project",
                "stars": 5000,
                "open_issues": 10,
                "pushed_at": "2024-01-01T00:00:00Z",
                "archived": True,
                "_meta": {"mode": "stub"},
            }

    agent = SubnetRepoHealthAgent({"collector": _StubCollector()})
    out = agent.run({
        "type": "subnet_repo_health",
        "repo_url": "https://github.com/old/project",
    })
    assert out["status"] == "complete"
    assert out["repo_archived"] is True
    assert out["verdict"] == "ABANDONED"
    assert out["repo_health_score"] == 0.0


def test_validate_input_rejects_bad_subnet_id():
    orch = _load_orch_with_plugin()
    out = orch.agents["subnet_repo_health_agent"].run({
        "type": "subnet_repo_health",
        "subnet_id": "not-an-int",
    })
    assert out["status"] == "error"
    assert "subnet_id" in out["reason"]


def test_validate_input_rejects_missing_type():
    orch = _load_orch_with_plugin()
    out = orch.agents["subnet_repo_health_agent"].run({
        "subnet_id": 1,
    })
    assert out["status"] == "error"
    assert "type" in out["reason"]


# ---------------------------------------------------------------------------
# 3. Safety: plug-in does NOT get to bypass the gate
# ---------------------------------------------------------------------------

def test_danger_actions_still_blocked_with_plugin_loaded():
    """Loading a plug-in must not raise its trust level. DANGER
    actions remain blocked at the gate, BEFORE reaching any agent."""
    orch = _load_orch_with_plugin()
    out = orch.execute_task({"type": "execute_trade", "amount": 100})
    assert out["status"] == "blocked"
    assert out["classification"] == "DANGER"


def test_run_call_count_increments():
    """get_status reports a calls counter — useful for the dashboard."""
    orch = _load_orch_with_plugin()
    agent = orch.agents["subnet_repo_health_agent"]
    for _ in range(3):
        agent.run({
            "type": "subnet_repo_health",
            "repo_url": "https://github.com/opentensor/bittensor",
        })
    assert agent.get_status()["calls"] == 3
