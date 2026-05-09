"""
Structural + runtime contract test for all built-in agents.

Locks in three guarantees from CLAUDE.md and SPEC.md:

1. ``run()`` MUST return a flat dict with a top-level ``status`` key —
   never raise to the orchestrator. The error path must produce
   ``{"status": "error", "reason": ..., "agent_name": ..., ...}``,
   not propagate the exception.
2. ``run()`` MUST NOT contain a bare ``raise`` (re-raising swallows
   per-agent failure context and triggers spurious resilience-retries).
3. ``validate_input()`` MUST reject obviously-invalid input — at
   minimum non-dicts and dicts missing the ``type`` field.

The structural part walks each agent module via AST so future regressions
fail at test time, not at runtime when an agent happens to misbehave.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from tao_swarm.agents import (
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
    TrainingExperimentAgent,
    ValidatorEngineeringAgent,
    WalletWatchAgent,
)

_AGENT_DIR = Path(__file__).resolve().parent.parent / "src" / "agents"

# (cls, valid_task) — the task is one the agent will process happily so
# we exercise the success path of run().
_AGENT_PROBES: list[tuple[type, dict]] = [
    (DashboardDesignAgent,    {"type": "dashboard", "params": {"action": "spec"}}),
    (DocumentationAgent,      {"type": "documentation"}),
    (FullstackDevAgent,       {"type": "development"}),
    (InfraDevopsAgent,        {"type": "infrastructure"}),
    (MarketTradeAgent,        {"type": "market_analysis"}),
    (MinerEngineeringAgent,   {"type": "miner_setup"}),
    (ProtocolResearchAgent,   {"type": "protocol_research"}),
    (QATestAgent,             {"type": "quality_assurance",
                               "params": {"action": "wallet_compliance"}}),
    (RiskSecurityAgent,       {"type": "risk_review"}),
    (SubnetDiscoveryAgent,    {"type": "subnet_discovery"}),
    (SubnetScoringAgent,      {"type": "subnet_scoring", "subnet_id": 1}),
    (SystemCheckAgent,        {"type": "system_check"}),
    (TrainingExperimentAgent, {"type": "training"}),
    (ValidatorEngineeringAgent,{"type": "validator_setup"}),
    (WalletWatchAgent,        {"type": "wallet_watch",
                               "address": "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"}),
]


# ---------------------------------------------------------------------------
# Structural: walk run() of every agent module via AST
# ---------------------------------------------------------------------------

def _agent_files() -> list[Path]:
    return sorted(p for p in _AGENT_DIR.glob("*_agent.py") if not p.name.startswith("_"))


def _find_run_node(tree: ast.AST) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            return node
    return None


def test_no_agent_run_method_contains_bare_raise():
    """A bare ``raise`` (re-raise) inside ``run()`` violates the
    contract — agents must turn failures into ``{"status":"error",...}``
    so the resilience layer doesn't fire for ordinary domain errors and
    so callers always get an inspectable dict."""
    offenders: list[str] = []
    for f in _agent_files():
        tree = ast.parse(f.read_text())
        run = _find_run_node(tree)
        if run is None:
            continue
        for sub in ast.walk(run):
            if isinstance(sub, ast.Raise) and sub.exc is None:
                offenders.append(f"{f.name}:{sub.lineno}")
    assert not offenders, (
        "run() must not re-raise — return a {'status':'error',...} dict "
        f"instead. Offenders: {offenders}"
    )


def test_every_agent_module_declares_name_and_version():
    """``AGENT_NAME`` and ``AGENT_VERSION`` are module-level required
    by SPEC.md — the plug-in loader and capability discovery both
    rely on them."""
    for f in _agent_files():
        tree = ast.parse(f.read_text())
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        assert "AGENT_NAME" in names, f"{f.name}: missing AGENT_NAME"
        assert "AGENT_VERSION" in names, f"{f.name}: missing AGENT_VERSION"


# ---------------------------------------------------------------------------
# Runtime: success path returns flat dict with status
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls,task", _AGENT_PROBES, ids=lambda x: getattr(x, "__name__", str(x)))
def test_run_returns_flat_dict_with_status(cls, task):
    agent = cls({"use_mock_data": True})
    out = agent.run(task)
    assert isinstance(out, dict), f"{cls.__name__}.run() must return a dict, got {type(out).__name__}"
    assert "status" in out, f"{cls.__name__}.run() return dict must have a top-level 'status' key. keys={sorted(out)}"
    assert "result" not in out, (
        f"{cls.__name__}.run() must return flat — 'result' key suggests "
        "nesting; orchestrator already wraps under 'output'."
    )


# ---------------------------------------------------------------------------
# Runtime: failure path returns error-dict instead of raising
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls,task", _AGENT_PROBES, ids=lambda x: getattr(x, "__name__", str(x)))
def test_run_failure_returns_error_dict_not_raise(cls, task):
    """Force one of the agent's instance methods to blow up and verify
    the agent catches it, returning a structured error dict rather than
    letting the exception escape."""
    agent = cls({"use_mock_data": True})

    # Find any callable instance attribute starting with '_' (private
    # helper) that the agent uses; we'll patch it to raise. Most agents
    # delegate from run() into a helper, so this triggers the except.
    helper_name: str | None = None
    for name in dir(agent):
        if name.startswith("__"):
            continue
        if name in {"run", "get_status", "validate_input"}:
            continue
        attr = getattr(agent, name, None)
        if callable(attr) and name.startswith("_"):
            helper_name = name
            break

    if helper_name is None:
        pytest.skip(f"{cls.__name__}: no private helper found to patch")

    with patch.object(agent, helper_name, side_effect=RuntimeError("boom-from-test")):
        try:
            out = agent.run(task)
        except Exception as e:
            pytest.fail(
                f"{cls.__name__}.run() raised {type(e).__name__} "
                f"instead of returning an error dict: {e}"
            )

    # Some agents won't actually call the patched helper for this task;
    # if so they may still succeed — that's acceptable. But if they DID
    # take the error path, the dict must be well-formed.
    assert isinstance(out, dict)
    if out.get("status") == "error":
        assert "reason" in out, (
            f"{cls.__name__}.run() error path must include 'reason'. got={sorted(out)}"
        )
        assert "agent_name" in out, (
            f"{cls.__name__}.run() error path must include 'agent_name'. got={sorted(out)}"
        )


# ---------------------------------------------------------------------------
# Runtime: validate_input rejects garbage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls,_task", _AGENT_PROBES, ids=lambda x: getattr(x, "__name__", str(x)))
def test_validate_input_rejects_non_dict(cls, _task):
    agent = cls({"use_mock_data": True})
    ok, reason = agent.validate_input("not a dict")
    assert ok is False, f"{cls.__name__} accepted a string as task"
    assert reason, f"{cls.__name__}.validate_input gave no reason"


@pytest.mark.parametrize("cls,_task", _AGENT_PROBES, ids=lambda x: getattr(x, "__name__", str(x)))
def test_validate_input_rejects_missing_type(cls, _task):
    """Tasks missing ``type`` are unroutable — every agent must reject."""
    agent = cls({"use_mock_data": True})
    ok, reason = agent.validate_input({"foo": "bar"})
    assert ok is False, (
        f"{cls.__name__} accepted a task without 'type' — every agent "
        "should require it (the orchestrator routes by it)."
    )
    assert reason, f"{cls.__name__}.validate_input gave no reason"


@pytest.mark.parametrize("cls,task", _AGENT_PROBES, ids=lambda x: getattr(x, "__name__", str(x)))
def test_validate_input_accepts_canonical_task(cls, task):
    agent = cls({"use_mock_data": True})
    ok, reason = agent.validate_input(task)
    assert ok is True, (
        f"{cls.__name__}.validate_input rejected its own canonical task "
        f"{task!r}: {reason}"
    )
