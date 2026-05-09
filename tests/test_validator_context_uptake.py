"""
Tests for ``ValidatorEngineeringAgent`` consuming the
``system_check_agent.hardware_report`` from the orchestrator's
context bus, plus a smoke check that the shared
``hardware_profile_from_context`` adapter works for both
miner and validator.

Mirrors the miner uptake tests added in PR #7 — same pattern, same
guarantees: cold start without context returns ``ready=False`` with
an actionable reason; after a ``system_check`` run, validator sees
real specs; explicit config still wins; safety properties hold.
"""

from __future__ import annotations

from tao_swarm.agents import (
    MinerEngineeringAgent,
    SystemCheckAgent,
    ValidatorEngineeringAgent,
)
from tao_swarm.agents._hardware import hardware_profile_from_context
from tao_swarm.orchestrator import AgentContext, SwarmOrchestrator

# ---------------------------------------------------------------------------
# Shared adapter unit-level
# ---------------------------------------------------------------------------

def _stub_agent_with_context(report: dict | None) -> object:
    """Tiny shim so we can call hardware_profile_from_context without a
    real agent instance."""
    class _Stub:
        pass
    a = _Stub()
    if report is None:
        a.context = None
    else:
        ctx = AgentContext()
        ctx.publish("system_check_agent", {"hardware_report": report})
        a.context = ctx
    return a


def test_helper_returns_empty_when_no_context():
    profile = hardware_profile_from_context(_stub_agent_with_context(None))
    assert profile == {}


def test_helper_returns_empty_when_no_report_published():
    a = _stub_agent_with_context({})  # publishes empty report
    # An empty hardware_report dict is still a dict; helper should
    # return zeroed values, not {}, since the report exists.
    profile = hardware_profile_from_context(a)
    # Core fields the miner / validator agents actually read.
    assert profile["ram_gb"] == 0
    assert profile["has_gpu"] is False
    assert profile["vram_gb"] == 0
    assert profile["cpu_cores"] == 0
    assert profile["_source"] == "system_check_agent.hardware_report"


def test_helper_translates_system_check_shape():
    report = {
        "cpu": {"cores": 8, "architecture": "x86_64"},
        "ram": {"total_gb": 32, "available_gb": 30},
        "gpu": {"available": True, "vram_gb": 24, "count": 1},
        "disk": {"total_gb": 1000, "free_gb": 500},
    }
    profile = hardware_profile_from_context(_stub_agent_with_context(report))
    assert profile["ram_gb"] == 32
    assert profile["has_gpu"] is True
    assert profile["vram_gb"] == 24
    assert profile["cpu_cores"] == 8
    assert profile["_source"] == "system_check_agent.hardware_report"


def test_helper_works_for_miner_too():
    """Same adapter must serve both miner and validator without
    drift."""
    report = {"cpu": {"cores": 4}, "ram": {"total_gb": 8}, "gpu": {"available": False}}
    a = _stub_agent_with_context(report)
    profile = hardware_profile_from_context(a)
    assert profile["ram_gb"] == 8
    assert profile["cpu_cores"] == 4


# ---------------------------------------------------------------------------
# Validator integration
# ---------------------------------------------------------------------------

def test_validator_status_has_actionable_reason_without_context():
    """Cold start: explicit message tells the user what to do."""
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(ValidatorEngineeringAgent({"use_mock_data": True}))
    out = orch.execute_task({"type": "validator_setup", "subnet_id": 12})
    hw = out["output"]["hardware_check"]
    assert hw["ready"] is False
    assert any("system_check" in i for i in hw["issues"])


def test_validator_picks_up_system_check_via_context():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.register_agent(ValidatorEngineeringAgent({"use_mock_data": True}))

    orch.execute_task({"type": "system_check"})
    out = orch.execute_task({"type": "validator_setup", "subnet_id": 12})
    hw = out["output"]["hardware_check"]

    # The cold-start "no profile" issue must be gone.
    assert not any("system_check" in i for i in hw["issues"])
    # The specs block now carries a real source attribution.
    assert hw["specs"]["source"] == "system_check_agent.hardware_report"
    # Numeric specs are populated (exact values depend on the runner,
    # so just check the type and that the field is present).
    for field in ("ram_gb", "vram_gb", "cpu_cores"):
        assert field in hw["specs"]
        assert isinstance(hw["specs"][field], (int, float))


def test_validator_explicit_config_profile_wins_over_context():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.register_agent(ValidatorEngineeringAgent({
        "use_mock_data": True,
        "hardware_profile": {
            "ram_gb": 256,
            "has_gpu": True,
            "vram_gb": 80,
            "cpu_cores": 64,
        },
    }))
    orch.execute_task({"type": "system_check"})
    out = orch.execute_task({"type": "validator_setup", "subnet_id": 12})
    hw = out["output"]["hardware_check"]
    # Explicit config dominates: source NOT from context, ram is 256
    assert hw["specs"]["ram_gb"] == 256
    assert hw["specs"]["source"] == "config:hardware_profile"


# ---------------------------------------------------------------------------
# Cross-agent: miner and validator both consume the same context entry
# ---------------------------------------------------------------------------

def test_miner_and_validator_share_same_system_check_report():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.register_agent(MinerEngineeringAgent({"use_mock_data": True}))
    orch.register_agent(ValidatorEngineeringAgent({"use_mock_data": True}))

    orch.execute_task({"type": "system_check"})

    orch.execute_task({"type": "miner_setup", "subnet_id": 12})
    orch.execute_task({"type": "validator_setup", "subnet_id": 12})

    miner_profile = orch.agents["miner_engineering_agent"]._hardware_profile
    validator_profile = orch.agents["validator_engineering_agent"]._hardware_profile

    # Both agents resolved the same numeric specs from the same context entry.
    for field in ("ram_gb", "has_gpu", "vram_gb", "cpu_cores"):
        assert miner_profile[field] == validator_profile[field]


# ---------------------------------------------------------------------------
# Safety: validator never publishes seed/key signals into context
# ---------------------------------------------------------------------------

def test_validator_published_output_has_no_credential_surface_words():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.register_agent(ValidatorEngineeringAgent({"use_mock_data": True}))

    orch.execute_task({"type": "system_check"})
    orch.execute_task({"type": "validator_setup", "subnet_id": 12})

    published = orch.context.get("validator_engineering_agent") or {}
    serialized = repr(published).lower()
    for surface in ("seed phrase", "mnemonic", "private key", "private_key"):
        assert surface not in serialized
