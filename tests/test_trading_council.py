"""
Tests for the TradingCouncil expert-team aggregator (PR 2T).

Coverage
========

AgentSignal:
- Constructor validation (score, confidence, direction).
- as_dict round-trips through json.dumps.

Each per-agent extractor:
- Returns None on missing context.
- Returns a well-formed AgentSignal when the upstream agent has
  published its report.
- Maps the underlying domain-data to a sensible direction.

TradingCouncil.collect:
- Returns all signals when every agent has published.
- Skips Nones from extractors that don't have data yet.
- Survives an extractor raising (defensive — never propagates).

TradingCouncil.aggregate:
- VETO from risk/qa with high confidence → halt.
- Low-confidence veto degrades to a heavy bearish weight.
- Weighted average maps to bullish/bearish/neutral by thresholds.
- Empty context → neutral with reason.
- Custom weights override defaults.
"""

from __future__ import annotations

import json

import pytest

from tao_swarm.orchestrator.context import AgentContext
from tao_swarm.trading import (
    AgentSignal,
    CouncilDecision,
    TradingCouncil,
)
from tao_swarm.trading.council import (
    DEFAULT_WEIGHTS,
    extract_dashboard_design,
    extract_documentation,
    extract_fullstack_dev,
    extract_infra_devops,
    extract_market_trade,
    extract_miner_engineering,
    extract_protocol_research,
    extract_qa_test,
    extract_risk_security,
    extract_subnet_discovery,
    extract_subnet_scoring,
    extract_system_check,
    extract_training_experiment,
    extract_validator_engineering,
    extract_wallet_watch,
)

# ---------------------------------------------------------------------------
# Helpers — build a fully-published AgentContext for tests.
# ---------------------------------------------------------------------------

def _build_full_context() -> AgentContext:
    """A context where every relevant agent has published a
    representative output. Used as the baseline for the per-agent
    extractor tests."""
    ctx = AgentContext()
    ctx.publish("subnet_scoring_agent", {
        "scored_subnets": [
            {"netuid": 7, "name": "Apex", "final_score": 78.5},
            {"netuid": 4, "name": "Targon", "final_score": 65.0},
            {"netuid": 1, "name": "Root", "final_score": 50.0},
        ],
        "total_scored": 3,
    })
    ctx.publish("market_trade_agent", {
        "price_change": {"7d_pct": 7.5, "24h_pct": -0.5},
    })
    ctx.publish("wallet_watch_agent", {
        "portfolio": {
            "addresses": [
                {"address": "5A", "balance_tao": 10.0},
                {"address": "5B", "balance_tao": 5.0},
            ],
        },
    })
    ctx.publish("subnet_discovery_agent", {
        "subnets": [
            {"netuid": i, "tao_in": 100_000.0 + i * 1000} for i in range(20)
        ],
    })
    ctx.publish("protocol_research_agent", {
        "network_health": {"subnet_count": 129, "validator_count": 256},
    })
    ctx.publish("risk_security_agent", {
        "classification": "SAFE",
        "findings": [],
    })
    ctx.publish("qa_test_agent", {
        "findings_count": 0,
        "severities": {"critical": 0, "high": 0},
    })
    ctx.publish("system_check_agent", {
        "hardware_report": {"ram_total_gb": 16, "cpu_count": 8},
    })
    ctx.publish("miner_engineering_agent", {
        "complexity": "low",
        "hardware_compatible": True,
    })
    ctx.publish("validator_engineering_agent", {
        "feasibility": "feasible",
    })
    ctx.publish("training_experiment_agent", {
        "training_plan": {"epochs": 10},
    })
    ctx.publish("infra_devops_agent", {
        "dockerfile": "FROM python:3.11",
    })
    ctx.publish("fullstack_dev_agent", {
        "focus_subnet": {"netuid": 7},
        "plan": {"steps": []},
    })
    ctx.publish("documentation_agent", {
        "coverage": 80,
    })
    return ctx


# ---------------------------------------------------------------------------
# AgentSignal validation
# ---------------------------------------------------------------------------

def test_agent_signal_rejects_score_out_of_range():
    with pytest.raises(ValueError):
        AgentSignal(name="x", score=1.5, confidence=0.5,
                    direction="bullish", evidence="")
    with pytest.raises(ValueError):
        AgentSignal(name="x", score=-0.1, confidence=0.5,
                    direction="bullish", evidence="")


def test_agent_signal_rejects_confidence_out_of_range():
    with pytest.raises(ValueError):
        AgentSignal(name="x", score=0.5, confidence=2.0,
                    direction="bullish", evidence="")


def test_agent_signal_rejects_unknown_direction():
    with pytest.raises(ValueError):
        AgentSignal(name="x", score=0.5, confidence=0.5,
                    direction="rocket", evidence="")


@pytest.mark.parametrize("direction", ["bullish", "bearish", "neutral", "veto"])
def test_agent_signal_accepts_valid_directions(direction):
    sig = AgentSignal(name="x", score=0.5, confidence=0.5,
                      direction=direction, evidence="ok")
    assert sig.direction == direction


def test_agent_signal_as_dict_serialisable():
    sig = AgentSignal(
        name="x", score=0.7, confidence=0.6,
        direction="bullish", evidence="ev",
        meta={"key": "value"},
    )
    payload = sig.as_dict()
    json.dumps(payload)  # no raise
    assert payload["score"] == 0.7
    assert payload["meta"]["key"] == "value"


# ---------------------------------------------------------------------------
# Extractors — None on missing context
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("extractor", [
    extract_subnet_scoring, extract_market_trade, extract_wallet_watch,
    extract_subnet_discovery, extract_protocol_research,
    extract_risk_security, extract_qa_test, extract_system_check,
    extract_miner_engineering, extract_validator_engineering,
    extract_training_experiment, extract_infra_devops,
    extract_fullstack_dev, extract_documentation,
])
def test_extractor_returns_none_on_empty_context(extractor):
    """Every extractor must tolerate an empty context bus."""
    ctx = AgentContext()
    assert extractor(ctx) is None


def test_extractor_returns_none_on_None_context():
    """Defensive: passing None as context must not raise."""
    for ext in (
        extract_subnet_scoring, extract_market_trade,
        extract_risk_security, extract_qa_test,
    ):
        assert ext(None) is None


def test_dashboard_design_is_honest_stub():
    """Honest stub — UI work, not a trading signal."""
    ctx = _build_full_context()
    assert extract_dashboard_design(ctx) is None


# ---------------------------------------------------------------------------
# Extractors — per-agent business logic
# ---------------------------------------------------------------------------

def test_subnet_scoring_maps_top_score_to_bullish():
    ctx = _build_full_context()
    sig = extract_subnet_scoring(ctx)
    assert sig is not None
    assert sig.score == pytest.approx(0.785)
    assert sig.direction == "bullish"
    assert "Apex" in sig.evidence


def test_subnet_scoring_low_score_is_bearish():
    ctx = AgentContext()
    ctx.publish("subnet_scoring_agent", {
        "scored_subnets": [{"netuid": 1, "final_score": 20.0}],
    })
    sig = extract_subnet_scoring(ctx)
    assert sig is not None
    assert sig.direction == "bearish"


def test_market_trade_uptrend_is_bullish():
    ctx = _build_full_context()
    sig = extract_market_trade(ctx)
    assert sig is not None
    assert sig.direction == "bullish"
    # Score reflects positive 7d (heavy weight) + slight 24h drag.
    assert 0.55 < sig.score < 0.75


def test_market_trade_downtrend_is_bearish():
    ctx = AgentContext()
    ctx.publish("market_trade_agent", {
        "price_change": {"7d_pct": -15.0, "24h_pct": -3.0},
    })
    sig = extract_market_trade(ctx)
    assert sig is not None
    assert sig.direction == "bearish"


def test_wallet_watch_concentration_pushes_bearish():
    """One huge position → bearish (don't pile on)."""
    ctx = AgentContext()
    ctx.publish("wallet_watch_agent", {
        "portfolio": {
            "addresses": [
                {"address": "5A", "balance_tao": 100.0},
                {"address": "5B", "balance_tao": 1.0},
            ],
        },
    })
    sig = extract_wallet_watch(ctx)
    assert sig is not None
    assert sig.direction == "bearish"


def test_wallet_watch_diversified_is_bullish():
    """Even split → room to grow → bullish."""
    ctx = AgentContext()
    ctx.publish("wallet_watch_agent", {
        "portfolio": {
            "addresses": [
                {"address": "5A", "balance_tao": 10.0},
                {"address": "5B", "balance_tao": 10.0},
                {"address": "5C", "balance_tao": 10.0},
                {"address": "5D", "balance_tao": 10.0},
            ],
        },
    })
    sig = extract_wallet_watch(ctx)
    assert sig is not None
    assert sig.direction == "bullish"


def test_wallet_watch_empty_portfolio_is_neutral():
    ctx = AgentContext()
    ctx.publish("wallet_watch_agent", {"portfolio": {"addresses": []}})
    sig = extract_wallet_watch(ctx)
    assert sig is not None
    assert sig.direction == "neutral"


def test_subnet_discovery_high_volume_is_bullish():
    """Mainnet-realistic volumes (∼5 M TAO total) are bullish."""
    ctx = AgentContext()
    ctx.publish("subnet_discovery_agent", {
        "subnets": [
            {"netuid": 0, "tao_in": 5_267_561},
            {"netuid": 1, "tao_in": 28_385},
            {"netuid": 4, "tao_in": 133_561},
            {"netuid": 64, "tao_in": 211_422},
        ],
    })
    sig = extract_subnet_discovery(ctx)
    assert sig is not None
    assert sig.score > 0.5


def test_protocol_research_minimal_data_falls_back_to_neutral():
    ctx = AgentContext()
    ctx.publish("protocol_research_agent", {})
    sig = extract_protocol_research(ctx)
    assert sig is not None
    assert sig.direction == "neutral"


def test_risk_security_DANGER_is_veto():
    ctx = AgentContext()
    ctx.publish("risk_security_agent", {
        "classification": "DANGER",
        "findings": ["coldkey_swap_pattern"],
    })
    sig = extract_risk_security(ctx)
    assert sig is not None
    assert sig.direction == "veto"
    assert sig.confidence > 0.9


def test_risk_security_SAFE_is_bullish():
    ctx = _build_full_context()
    sig = extract_risk_security(ctx)
    assert sig is not None
    assert sig.direction == "bullish"


def test_risk_security_CAUTION_is_bearish():
    ctx = AgentContext()
    ctx.publish("risk_security_agent", {
        "classification": "CAUTION", "findings": ["foo"],
    })
    sig = extract_risk_security(ctx)
    assert sig is not None
    assert sig.direction == "bearish"


def test_qa_test_critical_finding_is_veto():
    ctx = AgentContext()
    ctx.publish("qa_test_agent", {
        "findings_count": 3,
        "severities": {"critical": 1, "high": 2},
    })
    sig = extract_qa_test(ctx)
    assert sig is not None
    assert sig.direction == "veto"


def test_qa_test_clean_is_bullish():
    ctx = _build_full_context()
    sig = extract_qa_test(ctx)
    assert sig is not None
    assert sig.direction == "bullish"


def test_system_check_strong_hardware_is_bullish():
    ctx = AgentContext()
    ctx.publish("system_check_agent", {
        "hardware_report": {"ram_total_gb": 64, "cpu_count": 16},
    })
    sig = extract_system_check(ctx)
    assert sig is not None
    assert sig.direction == "bullish"


def test_miner_engineering_low_complexity_is_bullish():
    ctx = AgentContext()
    ctx.publish("miner_engineering_agent", {
        "complexity": "low", "hardware_compatible": True,
    })
    sig = extract_miner_engineering(ctx)
    assert sig is not None
    assert sig.direction == "bullish"


def test_validator_engineering_feasible_is_bullish():
    ctx = AgentContext()
    ctx.publish("validator_engineering_agent", {"feasibility": "feasible"})
    sig = extract_validator_engineering(ctx)
    assert sig is not None
    assert sig.direction == "bullish"


def test_training_experiment_with_plan_is_bullish():
    ctx = AgentContext()
    ctx.publish("training_experiment_agent", {"training_plan": {"x": 1}})
    sig = extract_training_experiment(ctx)
    assert sig is not None
    assert sig.direction == "bullish"


def test_documentation_coverage_above_50_is_neutral_to_bullish():
    ctx = AgentContext()
    ctx.publish("documentation_agent", {"coverage": 100})
    sig = extract_documentation(ctx)
    assert sig is not None
    assert sig.score >= 0.6  # high coverage = good signal


# ---------------------------------------------------------------------------
# TradingCouncil.collect / aggregate
# ---------------------------------------------------------------------------

def test_council_collect_with_full_context_returns_all_signals():
    council = TradingCouncil(_build_full_context())
    signals = council.collect()
    # 14 agents have data (dashboard_design returns None always).
    assert len(signals) >= 12
    names = {s.name for s in signals}
    assert "subnet_scoring_agent" in names
    assert "market_trade_agent" in names
    assert "risk_security_agent" in names


def test_council_collect_with_empty_context_returns_empty():
    council = TradingCouncil(AgentContext())
    assert council.collect() == []


def test_council_aggregate_full_context_is_decision_object():
    council = TradingCouncil(_build_full_context())
    decision = council.aggregate()
    assert isinstance(decision, CouncilDecision)
    assert decision.decision in {"bullish", "bearish", "neutral"}
    assert 0.0 <= (decision.score or 0.0) <= 1.0


def test_council_aggregate_empty_context_is_neutral():
    council = TradingCouncil(AgentContext())
    decision = council.aggregate()
    assert decision.decision == "neutral"
    assert decision.score == 0.5


def test_council_aggregate_DANGER_halts_trading():
    """A high-confidence veto from risk_security must halt regardless
    of how bullish other signals are."""
    ctx = _build_full_context()
    ctx.publish("risk_security_agent", {
        "classification": "DANGER",
        "findings": ["coldkey_swap_social_engineering"],
    })
    council = TradingCouncil(ctx)
    decision = council.aggregate()
    assert decision.decision == "halt"
    assert decision.score is None
    assert "VETO" in decision.reason


def test_council_aggregate_qa_critical_also_halts():
    ctx = _build_full_context()
    ctx.publish("qa_test_agent", {
        "findings_count": 1,
        "severities": {"critical": 1},
    })
    council = TradingCouncil(ctx)
    decision = council.aggregate()
    assert decision.decision == "halt"


def test_council_aggregate_low_confidence_veto_does_not_halt():
    """If we manually publish a low-confidence veto (shouldn't
    normally happen, but defensive), the council shouldn't halt."""

    class _CustomCtx:
        """Pretend context where one extractor returns a low-conf veto."""

        def __init__(self) -> None:
            # Build a real full context for everything else.
            self._real = _build_full_context()

        def get(self, key, default=None):
            return self._real.get(key, default)

    # Use a custom extractor by injecting a low-conf veto via a
    # special signal — the council does veto detection by looking
    # at the AgentSignal direction + confidence after collect().
    # We simulate this by subclassing.

    class _LowConfCouncil(TradingCouncil):
        def collect(self):
            base = super().collect()
            # Drop any high-conf veto and replace with a low-conf one.
            base = [s for s in base if s.direction != "veto"]
            base.append(AgentSignal(
                name="risk_security_agent",
                score=0.0, confidence=0.5,  # below 0.8 threshold
                direction="veto",
                evidence="weak signal",
            ))
            return base

    council = _LowConfCouncil(_build_full_context())
    decision = council.aggregate()
    # Halt is keyed off confidence ≥ veto_confidence (default 0.8).
    # A 0.5 veto must NOT halt — it's just a tilt.
    assert decision.decision != "halt"


def test_council_aggregate_high_quality_signals_yield_bullish():
    """When everything is positive AND no vetoes, council leans bullish."""
    ctx = _build_full_context()
    # Reinforce: top score 95, +20% trend
    ctx.publish("subnet_scoring_agent", {
        "scored_subnets": [{"netuid": 7, "final_score": 95.0}],
    })
    ctx.publish("market_trade_agent", {
        "price_change": {"7d_pct": 20.0, "24h_pct": 5.0},
    })
    council = TradingCouncil(ctx)
    decision = council.aggregate()
    assert decision.decision == "bullish"


def test_council_aggregate_negative_signals_yield_bearish():
    """When the heavy-weight signals (scoring, market, wallet, risk)
    all point bearish AND no bullish ops signals are present, the
    council must dip below 0.4."""
    ctx = AgentContext()
    ctx.publish("subnet_scoring_agent", {
        "scored_subnets": [{"netuid": 7, "final_score": 5.0}],
    })
    ctx.publish("market_trade_agent", {
        "price_change": {"7d_pct": -25.0, "24h_pct": -8.0},
    })
    ctx.publish("wallet_watch_agent", {
        "portfolio": {"addresses": [
            {"address": "5A", "balance_tao": 100.0},
            {"address": "5B", "balance_tao": 1.0},
        ]},
    })
    ctx.publish("risk_security_agent", {
        "classification": "CAUTION", "findings": ["x"],
    })
    council = TradingCouncil(ctx)
    decision = council.aggregate()
    assert decision.decision == "bearish", (
        f"expected bearish, got {decision.decision} score={decision.score}"
    )


def test_council_custom_weights_zero_out_signal():
    """If the operator zeroes out subnet_scoring's weight, the
    aggregate should barely move when scoring changes."""
    # Build two fresh contexts (AgentContext can't deepcopy because
    # it owns an RLock). Same baseline + only scoring differs.
    ctx_high = _build_full_context()
    ctx_low = _build_full_context()

    ctx_high.publish("subnet_scoring_agent", {
        "scored_subnets": [{"netuid": 7, "final_score": 95.0}],
    })
    ctx_low.publish("subnet_scoring_agent", {
        "scored_subnets": [{"netuid": 7, "final_score": 5.0}],
    })

    weights = dict(DEFAULT_WEIGHTS)
    weights["subnet_scoring_agent"] = 0.0

    high = TradingCouncil(ctx_high, weights=weights).aggregate()
    low = TradingCouncil(ctx_low, weights=weights).aggregate()
    # With scoring zero-weighted, the two should yield nearly the
    # same score (other agents unchanged).
    assert abs((high.score or 0) - (low.score or 0)) < 0.05


def test_council_aggregate_extractor_exception_doesnt_propagate(monkeypatch):
    """If one extractor blows up, the council still works."""
    from tao_swarm.trading import council as council_mod

    def _boom(_ctx):
        raise RuntimeError("simulated extractor failure")

    # Replace one extractor with a boom-er.
    new_extractors = list(council_mod._EXTRACTORS)
    new_extractors[0] = (new_extractors[0][0], _boom)
    monkeypatch.setattr(council_mod, "_EXTRACTORS", new_extractors)

    council = TradingCouncil(_build_full_context())
    decision = council.aggregate()  # should not raise
    assert isinstance(decision, CouncilDecision)


def test_council_decision_as_dict_round_trip():
    decision = TradingCouncil(_build_full_context()).aggregate()
    payload = decision.as_dict()
    json.dumps(payload)
    assert "decision" in payload
    assert "signals" in payload
    assert isinstance(payload["signals"], list)


def test_council_constructor_validates_thresholds():
    ctx = AgentContext()
    with pytest.raises(ValueError):
        TradingCouncil(ctx, bullish_threshold=0.4)
    with pytest.raises(ValueError):
        TradingCouncil(ctx, bearish_threshold=0.6)
    with pytest.raises(ValueError):
        TradingCouncil(ctx, veto_confidence=1.5)


def test_default_weights_cover_every_agent():
    """Every extractor's agent name has a default weight (so the
    council doesn't silently fall back to weight=1.0 for some agents
    and the documented weight scheme for others)."""
    from tao_swarm.trading.council import _EXTRACTORS
    extractor_names = {name for name, _ in _EXTRACTORS}
    weight_names = set(DEFAULT_WEIGHTS)
    missing = extractor_names - weight_names
    assert not missing, (
        f"Extractors missing default weights: {sorted(missing)}"
    )
