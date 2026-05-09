"""
Regression tests for finding M3: orchestrator output and agent return-shape
consistency. The audit showed three different return styles coexisting:

- 9 agents: flat dict with top-level ``status``
- 5 agents: raw report (no ``status``)
- Hygen template: wrapped under ``result`` (a 3rd style)

The fix:
1. Hygen template aligned to the flat-with-status majority.
2. The orchestrator lifts the agent's per-call ``status`` (when present)
   into a top-level ``agent_result_status`` so consumers don't have to
   dig into ``output`` and don't have to handle it being missing.
3. CLAUDE.md documents the convention.

These tests pin down (a) the orchestrator output shape, (b) the
``agent_result_status`` lifting, and (c) the contract minimum for any
agent registered into the swarm.
"""

from __future__ import annotations

import json

import pytest

from src.agents import (
    DashboardDesignAgent,
    DocumentationAgent,
    FullstackDevAgent,
    InfraDevopsAgent,
    MarketTradeAgent,
    MinerEngineeringAgent,
    ProtocolResearchAgent,
    QATestAgent,
    RiskSecurityAgent,
    SubnetDiscoveryAgent,
    SubnetScoringAgent,
    SystemCheckAgent,
    ValidatorEngineeringAgent,
    WalletWatchAgent,
)
from src.orchestrator import SwarmOrchestrator

REQUIRED_ORCH_FIELDS: set[str] = {
    "status",
    "task_type",
    "agent_name",
    "classification",
    "executed",
    "output",
    "agent_status",
    "agent_result_status",
    "timestamp",
}


def _build_orchestrator() -> SwarmOrchestrator:
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    for AgentCls in (
        SystemCheckAgent, ProtocolResearchAgent, SubnetDiscoveryAgent,
        SubnetScoringAgent, WalletWatchAgent, MarketTradeAgent,
        RiskSecurityAgent, MinerEngineeringAgent, ValidatorEngineeringAgent,
        InfraDevopsAgent, DashboardDesignAgent, FullstackDevAgent,
        QATestAgent, DocumentationAgent,
    ):
        orch.register_agent(AgentCls({"use_mock_data": True}))
    return orch


# ---------------------------------------------------------------------------
# Orchestrator output shape: same fields for every successful execution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "task",
    [
        {"type": "system_check"},
        {"type": "subnet_discovery"},
        {"type": "subnet_scoring", "subnet_id": 12},
        {"type": "wallet_watch", "address": "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"},
        {"type": "market_analysis", "params": {"pair": "TAO/USD"}},
    ],
)
def test_orchestrator_output_has_consistent_top_level_fields(task: dict):
    orch = _build_orchestrator()
    out = orch.execute_task(task)
    missing = REQUIRED_ORCH_FIELDS - set(out)
    assert not missing, f"orchestrator result missing fields: {missing}"
    assert out["status"] == "success"
    assert out["executed"] is True


def test_orchestrator_blocked_task_has_consistent_shape():
    orch = _build_orchestrator()
    out = orch.execute_task({"type": "execute_trade", "amount": 50})
    # Blocked path doesn't run an agent, so agent_status / agent_result_status
    # don't apply, but the top-level orchestrator fields must still be there.
    for field in ("status", "task_type", "classification", "executed", "output", "timestamp"):
        assert field in out, f"blocked result missing {field}"
    assert out["status"] == "blocked"
    assert out["executed"] is False


# ---------------------------------------------------------------------------
# agent_result_status: lifted from agent output when present
# ---------------------------------------------------------------------------

def test_agent_result_status_is_lifted_from_agent_output():
    orch = _build_orchestrator()
    # wallet_watch's run() puts a top-level "status" on its return dict.
    out = orch.execute_task({
        "type": "wallet_watch",
        "address": "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy",
    })
    assert out["agent_result_status"] is not None
    assert out["agent_result_status"] == out["output"]["status"]


def test_agent_result_status_is_none_when_agent_omits_it():
    orch = _build_orchestrator()
    # system_check_agent's run() returns a raw report without a status key.
    out = orch.execute_task({"type": "system_check"})
    if "status" not in out["output"]:
        assert out["agent_result_status"] is None
    else:
        assert out["agent_result_status"] == out["output"]["status"]


# ---------------------------------------------------------------------------
# Per-agent contract: every agent in src/agents/ returns a dict from run()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "AgentCls,task",
    [
        (SystemCheckAgent,           {"type": "system_check"}),
        (ProtocolResearchAgent,      {"type": "protocol_research"}),
        (SubnetDiscoveryAgent,       {"type": "subnet_discovery"}),
        (SubnetScoringAgent,         {"type": "subnet_scoring", "subnet_id": 1}),
        (WalletWatchAgent,           {"type": "wallet_watch"}),
        (MarketTradeAgent,           {"type": "market_analysis", "params": {"pair": "TAO/USD"}}),
        (RiskSecurityAgent,          {"params": {"target": "general", "content": "read subnet data"}}),
        (MinerEngineeringAgent,      {"type": "miner_setup"}),
        (ValidatorEngineeringAgent,  {"type": "validator_setup"}),
        (InfraDevopsAgent,           {"type": "infrastructure"}),
        (DashboardDesignAgent,       {"type": "dashboard_design"}),
        (FullstackDevAgent,          {"type": "development"}),
        # QATestAgent's default action is full_scan, which shells out to
        # pytest/etc. and takes minutes. We only need to assert the shape,
        # so use the lightweight secret_check action over an empty content.
        (QATestAgent,                {"params": {"action": "secret_check", "content": ""}}),
        (DocumentationAgent,         {"type": "documentation"}),
    ],
)
def test_every_production_agent_returns_a_dict(AgentCls, task):
    """The minimal agent contract per SPEC.md: ``run()`` returns a dict."""
    agent = AgentCls({"use_mock_data": True})
    out = agent.run(task)
    assert isinstance(out, dict), f"{AgentCls.__name__}.run() must return a dict"


# ---------------------------------------------------------------------------
# Hygen template: locks the convention down so future generated agents
# can't drift back to a different shape
# ---------------------------------------------------------------------------

def test_hygen_template_uses_flat_with_status_pattern():
    """Read the template source and assert it does not wrap under 'result'."""
    template_path = "_templates/agent/new/agent.ejs.t"
    with open(template_path, encoding="utf-8") as fh:
        source = fh.read()
    # Negative: the old wrap pattern must not return.
    assert '"result": result' not in source, (
        "Hygen template regressed to the wrapped {status, result: …} shape. "
        "Convention: flat dict with top-level status."
    )
    # Positive: the new pattern unpacks the report inline.
    assert "**report" in source


# ---------------------------------------------------------------------------
# Documentation: CLAUDE.md must mention the convention
# ---------------------------------------------------------------------------

def test_claude_md_documents_return_shape_convention():
    with open("CLAUDE.md", encoding="utf-8") as fh:
        text = fh.read()
    assert "Return-shape convention" in text
    assert "agent_result_status" in text


# ---------------------------------------------------------------------------
# JSON-cleanliness: orchestrator output must serialize without help
# ---------------------------------------------------------------------------

def test_orchestrator_result_is_json_serializable():
    orch = _build_orchestrator()
    out = orch.execute_task({"type": "system_check"})
    # default=str should NOT be needed for our top-level fields. Drop the
    # potentially-arbitrary nested 'output' before encoding so we test the
    # framing fields specifically.
    framing = {k: v for k, v in out.items() if k != "output"}
    json.dumps(framing)  # must not raise
