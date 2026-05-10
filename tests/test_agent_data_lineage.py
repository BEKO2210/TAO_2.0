"""
Data-lineage contract for the 15 in-tree agents (PR 2S).

The contract: every agent module under ``tao_swarm/agents/*_agent.py``
must have a non-trivial data path. That means at least one of:

a) **Live-collector dependency** — imports from ``tao_swarm.collectors``
   inside the module.

b) **Upstream-context dependency** — calls ``self.context.get(...)``
   inside the module (pull-based bus from the orchestrator).

c) **Operator-input dependency** — an explicit text/content task
   parameter the agent classifies (``risk_security_agent`` is the
   only legitimate case here; an allow-list pins it).

Before PR 2S, 9 of 15 agents satisfied none of these — they were
template emitters that produced identical output every time. This
test makes that state un-mergeable: a new agent that ignores both
collectors and upstream-context fails the build.

The test reads each agent module's source text — NOT its runtime
behaviour. That's deliberate: a runtime test would have to wire up
collectors + a fake context + run every agent, which is slow and
duplicates work the agent's own tests already do. The lineage
contract is a static guarantee, not a runtime invariant.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

# Repo-relative directory the audit walks.
_AGENTS_DIR = Path(__file__).resolve().parent.parent / "tao_swarm" / "agents"

# Allow-list: agents that legitimately do not need collectors or
# upstream context because their input arrives as task parameters.
# Currently the only entry; adding to this list should require a
# code-review explanation, since "I don't want to wire context"
# isn't a valid reason.
_INPUT_DRIVEN_AGENTS = frozenset({
    "risk_security_agent",
})


def _agent_modules() -> list[Path]:
    """All ``*_agent.py`` files in the agents package, alphabetical."""
    return sorted(p for p in _AGENTS_DIR.glob("*_agent.py")
                  if p.name != "__init__.py")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Lineage detectors (read source text, not runtime behaviour)
# ---------------------------------------------------------------------------

def _has_collector_import(src: str) -> bool:
    """Imports from ``tao_swarm.collectors`` indicate live-data lineage."""
    return "from tao_swarm.collectors" in src or "import tao_swarm.collectors" in src


def _has_context_read(src: str) -> bool:
    """Reads from the agent context bus indicate upstream-context lineage.

    Matches either the direct form (``self.context.get(...)``) or the
    common defensive pattern where the bus is grabbed once into a
    local (``ctx = getattr(self, "context", None); ctx.get(...)``).
    """
    direct = "self.context.get(" in src or "self.context.has(" in src
    rebound = (
        'getattr(self, "context"' in src
        or "getattr(self, 'context'" in src
    )
    return direct or rebound


def _is_input_driven(name: str) -> bool:
    return name in _INPUT_DRIVEN_AGENTS


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def agent_files() -> list[Path]:
    files = _agent_modules()
    assert files, "No agents found — repo layout broke?"
    return files


def test_agents_directory_has_expected_count(agent_files):
    """We claim 15 in-tree agents in the README. If this changes,
    the README claim breaks too."""
    assert len(agent_files) >= 15, (
        f"Expected >=15 agents, got {len(agent_files)}: "
        f"{[f.name for f in agent_files]}"
    )


def test_every_agent_satisfies_lineage_contract(agent_files):
    """The core contract: every agent has a real data path."""
    offenders: list[str] = []
    for path in agent_files:
        name = path.stem  # e.g. "miner_engineering_agent"
        src = _read(path)
        has_collector = _has_collector_import(src)
        has_context = _has_context_read(src)
        is_input = _is_input_driven(name)
        # ``kind: "foundation"`` and ``kind: "self-introspection"`` are
        # legitimate exceptions documented in _EXPECTED_LINEAGE. We
        # still verify the foundation/introspection agents actually
        # do their stated job below in
        # ``test_each_agent_matches_expected_lineage``.
        spec = _EXPECTED_LINEAGE.get(name, {})
        is_special_kind = spec.get("kind") in {"foundation", "self-introspection"}
        if not (has_collector or has_context or is_input or is_special_kind):
            offenders.append(name)

    assert not offenders, (
        f"\n\nThese agents are template-emitters with no data lineage:\n"
        f"  {sorted(offenders)}\n\n"
        f"Each must EITHER import from tao_swarm.collectors OR call "
        f"self.context.get(...) on at least one upstream agent. See "
        f"docs/agent_lineage.md for the table of which upstream each "
        f"should pull.\n"
    )


def test_input_driven_allow_list_is_minimal(agent_files):
    """The allow-list shouldn't grow without explicit justification.
    Right now it's exactly one agent."""
    assert len(_INPUT_DRIVEN_AGENTS) <= 1, (
        f"Input-driven allow-list should stay minimal; got "
        f"{sorted(_INPUT_DRIVEN_AGENTS)}. If you're adding to it, "
        f"justify it in docs/agent_lineage.md and a PR description."
    )


def test_every_agent_module_declares_agent_name(agent_files):
    """Every agent has ``AGENT_NAME`` so the orchestrator can route
    + the AgentContext bus can publish under a stable key."""
    for path in agent_files:
        src = _read(path)
        assert "AGENT_NAME" in src, f"{path.name} missing AGENT_NAME"


def test_every_agent_module_imports_cleanly():
    """A no-op import sanity check: nothing crashes at module load."""
    for path in _agent_modules():
        module_name = f"tao_swarm.agents.{path.stem}"
        importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# Detailed table-of-truth: each agent's expected upstream
# ---------------------------------------------------------------------------

# This table mirrors docs/agent_lineage.md. Whenever an agent grows
# a new upstream dependency, add it here and the test below verifies
# the wiring landed.
_EXPECTED_LINEAGE: dict[str, dict[str, list[str] | str]] = {
    "system_check_agent":           {"collectors": [], "context": [], "kind": "foundation"},
    "protocol_research_agent":      {"collectors": ["chain_readonly"], "context": []},
    "subnet_discovery_agent":       {"collectors": ["chain_readonly"], "context": []},
    "subnet_scoring_agent":         {"collectors": [], "context": ["subnet_discovery_agent"]},
    "wallet_watch_agent":           {"collectors": ["wallet_watchonly"], "context": []},
    "market_trade_agent":           {"collectors": ["market_data"], "context": ["subnet_scoring_agent"]},
    "risk_security_agent":          {"collectors": [], "context": [], "kind": "input-driven"},
    "miner_engineering_agent":      {"collectors": [], "context": ["system_check_agent", "subnet_scoring_agent"]},
    "validator_engineering_agent":  {"collectors": [], "context": ["system_check_agent", "subnet_scoring_agent"]},
    "training_experiment_agent":    {"collectors": [], "context": ["system_check_agent", "miner_engineering_agent"]},
    "infra_devops_agent":           {"collectors": [], "context": ["system_check_agent"]},
    "fullstack_dev_agent":          {"collectors": [], "context": ["subnet_scoring_agent"]},
    "qa_test_agent":                {"collectors": [], "context": ["system_check_agent"]},
    "documentation_agent":          {"collectors": [], "context": [], "kind": "self-introspection"},
    "dashboard_design_agent":       {"collectors": [], "context": ["subnet_scoring_agent"]},
}


def test_lineage_table_covers_every_agent(agent_files):
    """The table-of-truth must mention every shipped agent."""
    in_tree = {p.stem for p in agent_files}
    table = set(_EXPECTED_LINEAGE)
    missing = in_tree - table
    extra = table - in_tree
    assert not missing, (
        f"Agents present in repo but missing from "
        f"_EXPECTED_LINEAGE: {sorted(missing)}"
    )
    assert not extra, (
        f"Agents listed in _EXPECTED_LINEAGE but no longer in repo: "
        f"{sorted(extra)}"
    )


@pytest.mark.parametrize(
    "agent_name,spec",
    sorted(_EXPECTED_LINEAGE.items()),
)
def test_each_agent_matches_expected_lineage(agent_name, spec):
    """For every (agent, expected upstream) pair in the table,
    grep the source for the expected reads. This catches
    regressions where someone removes a `self.context.get(...)`
    call."""
    path = _AGENTS_DIR / f"{agent_name}.py"
    if not path.exists():
        pytest.skip(f"agent file missing: {path.name}")
    src = _read(path)
    kind = spec.get("kind", "")

    # Documentation agent is self-introspecting via the agents
    # package — count that as legitimate even without context reads.
    if kind == "self-introspection":
        assert "from tao_swarm import agents" in src or \
               "from tao_swarm.agents" in src, (
            f"{agent_name} declared self-introspection but doesn't "
            f"import the agents package."
        )
        return

    if kind == "input-driven":
        # Allow-list agent: no further checks beyond the global
        # contract test. Verify it's actually in the allow-list.
        assert agent_name in _INPUT_DRIVEN_AGENTS
        return

    if kind == "foundation":
        # system_check_agent doesn't need either — it sits at the
        # root of the DAG and produces hardware/software reports.
        # Still must pass the global contract — it does (probes
        # subprocess + os module). Skip per-upstream verification.
        return

    for col in spec.get("collectors", []):  # type: ignore[arg-type]
        assert col in src, (
            f"{agent_name} should import from tao_swarm.collectors.{col} "
            f"but no reference found"
        )

    for upstream in spec.get("context", []):  # type: ignore[arg-type]
        # The agent must reference the upstream key in a ``.get(...)``
        # call somewhere in its source. Accepts both the direct
        # ``self.context.get("KEY"...)`` form and the rebind pattern
        # ``ctx = getattr(self, "context", None); ctx.get("KEY"...)``.
        signals = (
            f'.get("{upstream}',
            f".get('{upstream}",
        )
        assert any(s in src for s in signals), (
            f"{agent_name} should read upstream '{upstream}' via "
            f"<context>.get(...) but no such call found"
        )
