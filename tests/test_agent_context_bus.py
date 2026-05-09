"""
Tests for the pull-based ``AgentContext`` bus (audit finding M2).

Two layers:

* Unit-level — ``AgentContext`` itself: get/has/dotted-path/reset/isolation.
* Integration — the orchestrator publishes after successful runs and
  injects the bus into agents on register, and ``MinerEngineeringAgent``
  actually consumes the ``system_check_agent.hardware_report`` instead
  of returning the ``status: "unknown"`` it produced before this change.
"""

from __future__ import annotations

from src.agents import (
    MinerEngineeringAgent,
    SystemCheckAgent,
    WalletWatchAgent,
)
from src.orchestrator import AgentContext, SwarmOrchestrator

# ---------------------------------------------------------------------------
# Unit-level: AgentContext
# ---------------------------------------------------------------------------

def test_context_publish_and_get_round_trip():
    ctx = AgentContext()
    ctx.publish("foo_agent", {"a": 1, "b": 2})
    assert ctx.get("foo_agent") == {"a": 1, "b": 2}


def test_context_dotted_path_resolves_through_nested_dicts():
    ctx = AgentContext()
    ctx.publish("system_check_agent", {
        "hardware_report": {"cpu": {"cores": 4}, "ram": {"total_gb": 16}},
    })
    assert ctx.get("system_check_agent.hardware_report.cpu.cores") == 4
    assert ctx.get("system_check_agent.hardware_report.ram.total_gb") == 16


def test_context_missing_key_returns_default():
    ctx = AgentContext()
    assert ctx.get("nope") is None
    assert ctx.get("nope", default=42) == 42
    assert ctx.get("foo.bar.baz") is None


def test_context_dotted_path_through_non_dict_returns_default():
    ctx = AgentContext()
    ctx.publish("agent", {"x": 5})
    # x.y traverses through an int → must not raise, must return default
    assert ctx.get("agent.x.y", default="fallback") == "fallback"


def test_context_get_returns_deep_copy_not_alias():
    """A consumer must not be able to mutate another agent's report."""
    ctx = AgentContext()
    ctx.publish("agent", {"items": [1, 2, 3]})
    a = ctx.get("agent")
    a["items"].append(99)
    a["mutated"] = True
    fresh = ctx.get("agent")
    assert fresh == {"items": [1, 2, 3]}


def test_context_has_and_in_operators():
    ctx = AgentContext()
    ctx.publish("agent", {"k": "v"})
    assert ctx.has("agent")
    assert ctx.has("agent.k")
    assert not ctx.has("agent.x")
    assert "agent" in ctx
    assert "agent.k" in ctx


def test_context_reset_wipes_everything():
    ctx = AgentContext()
    ctx.publish("a", {"x": 1})
    ctx.publish("b", {"y": 2})
    assert len(ctx) == 2
    ctx.reset()
    assert len(ctx) == 0
    assert ctx.keys() == []


# ---------------------------------------------------------------------------
# Orchestrator wiring
# ---------------------------------------------------------------------------

def test_orchestrator_owns_a_context():
    orch = SwarmOrchestrator({"use_mock_data": True})
    assert isinstance(orch.context, AgentContext)
    assert len(orch.context) == 0


def test_register_agent_injects_context():
    orch = SwarmOrchestrator({"use_mock_data": True})
    agent = SystemCheckAgent({"use_mock_data": True})
    assert getattr(agent, "context", None) is None
    orch.register_agent(agent)
    assert agent.context is orch.context


def test_register_agent_does_not_overwrite_preexisting_context():
    orch = SwarmOrchestrator({"use_mock_data": True})
    agent = SystemCheckAgent({"use_mock_data": True})
    custom_ctx = AgentContext()
    agent.context = custom_ctx
    orch.register_agent(agent)
    assert agent.context is custom_ctx


def test_successful_task_publishes_output_under_agent_name():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.execute_task({"type": "system_check"})
    assert orch.context.has("system_check_agent")
    assert orch.context.has("system_check_agent.hardware_report")


def test_blocked_task_does_not_publish_to_context():
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    out = orch.execute_task({"type": "execute_trade", "amount": 100})
    assert out["status"] == "blocked"
    assert orch.context.keys() == []


def test_reset_context_clears_published_entries():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.execute_task({"type": "system_check"})
    assert "system_check_agent" in orch.context
    orch.reset_context()
    assert orch.context.keys() == []


# ---------------------------------------------------------------------------
# Integration: MinerEngineeringAgent now consumes the system_check report
# ---------------------------------------------------------------------------

def test_miner_status_unknown_without_system_check():
    """Cold start: with no system_check report and no hardware_profile in
    config, miner reports unknown — explicit, not silently empty."""
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(MinerEngineeringAgent({"use_mock_data": True}))
    out = orch.execute_task({"type": "miner_setup", "subnet_id": 12})
    hwc = out["output"]["hardware_compatibility"]
    assert hwc["status"] == "unknown"
    assert "reason" in hwc


def test_miner_picks_up_system_check_report_via_context():
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.register_agent(MinerEngineeringAgent({"use_mock_data": True}))

    orch.execute_task({"type": "system_check"})
    out = orch.execute_task({"type": "miner_setup", "subnet_id": 12})
    hwc = out["output"]["hardware_compatibility"]
    assert hwc["status"] != "unknown"
    # Profile should now be populated from context with the adapter source tag
    miner = orch.agents["miner_engineering_agent"]
    assert miner._hardware_profile.get("_source") == "system_check_agent.hardware_report"


def test_miner_explicit_config_profile_wins_over_context():
    """If the caller passed a hardware_profile in config, that wins —
    context is only the fallback."""
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))
    orch.register_agent(MinerEngineeringAgent({
        "use_mock_data": True,
        "hardware_profile": {"ram_gb": 99, "has_gpu": True, "vram_gb": 80, "cpu_cores": 32},
    }))
    orch.execute_task({"type": "system_check"})
    orch.execute_task({"type": "miner_setup", "subnet_id": 12})
    miner = orch.agents["miner_engineering_agent"]
    # The configured profile must not have been replaced by the context one.
    assert miner._hardware_profile.get("ram_gb") == 99
    assert miner._hardware_profile.get("_source") is None


# ---------------------------------------------------------------------------
# Safety: context must never carry seed/key flags or dangerous data
# ---------------------------------------------------------------------------

def test_wallet_watch_does_not_leak_safety_flags_through_context():
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    orch.register_agent(WalletWatchAgent({"use_mock_data": True}))
    orch.execute_task({
        "type": "wallet_watch",
        "address": "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy",
    })
    published = orch.context.get("wallet_watch_agent") or {}
    serialized = repr(published).lower()
    # The sensitive surface words must never appear in any published report.
    assert "seed" not in serialized
    assert "mnemonic" not in serialized
    assert "private key" not in serialized
    assert "private_key" not in serialized
