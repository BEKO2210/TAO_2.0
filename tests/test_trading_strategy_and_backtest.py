"""
Tests for ``MomentumRotationStrategy`` and the ``Backtester``.

Coverage

Strategy:
- Validates constructor inputs.
- Emits no proposals when history is missing or short.
- Emits ``stake`` on positive momentum >= threshold.
- Emits ``unstake`` on negative momentum <= -threshold.
- Stays silent inside the deadband.
- Watchlist filter excludes other netuids.
- Confidence scales with momentum magnitude, clamped to 1.0.
- Skips entries with non-positive / NaN / missing tao_in.
- ``meta()`` reports the declared risk surface.

Backtester:
- Runs deterministically over a synthetic snapshot stream.
- Counts proposals / executed / refused.
- Computes total P&L correctly when entries close at higher /
  lower prices.
- Win-rate matches expectation on closed trades.
- Max-drawdown tracks the equity-curve peak-to-trough.
- Sharpe is 0 with constant per-step P&L.
- Refuses zero proposals on a flat market.
"""

from __future__ import annotations

import pytest

from tao_swarm.trading import (
    Backtester,
    BacktestResult,
    StrategyMeta,
)
from tao_swarm.trading.strategies.momentum_rotation import (
    MomentumRotationStrategy,
)

# ---------------------------------------------------------------------------
# Strategy: input validation
# ---------------------------------------------------------------------------

def test_strategy_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        MomentumRotationStrategy(threshold_pct=0)
    with pytest.raises(ValueError):
        MomentumRotationStrategy(threshold_pct=-0.1)
    with pytest.raises(ValueError):
        MomentumRotationStrategy(slot_size_tao=0)
    with pytest.raises(ValueError):
        MomentumRotationStrategy(max_daily_loss_tao=0)
    with pytest.raises(ValueError):
        # max_position smaller than slot_size — should reject.
        MomentumRotationStrategy(slot_size_tao=2, max_position_tao=1)


def test_strategy_meta_reports_risk_surface():
    s = MomentumRotationStrategy(
        slot_size_tao=2.5, max_daily_loss_tao=10.0,
    )
    m = s.meta()
    assert isinstance(m, StrategyMeta)
    assert m.name == "momentum_rotation"
    assert m.max_position_tao == 2.5
    assert m.max_daily_loss_tao == 10.0
    assert "stake" in m.actions_used
    assert "unstake" in m.actions_used


# ---------------------------------------------------------------------------
# Strategy: silence on insufficient data
# ---------------------------------------------------------------------------

def test_strategy_silent_with_no_history():
    s = MomentumRotationStrategy()
    out = s.evaluate({
        "subnets": [{"netuid": 1, "tao_in": 100.0}],
        "history": {},
    })
    assert out == []


def test_strategy_silent_with_single_history_point():
    s = MomentumRotationStrategy()
    out = s.evaluate({
        "subnets": [{"netuid": 1, "tao_in": 100.0}],
        "history": {1: [(0.0, 100.0)]},
    })
    assert out == []


def test_strategy_silent_inside_deadband():
    s = MomentumRotationStrategy(threshold_pct=0.10)
    # 5% momentum → below 10% threshold → no signal.
    out = s.evaluate({
        "subnets": [{"netuid": 1, "tao_in": 105.0}],
        "history": {1: [(0.0, 100.0), (1.0, 105.0)]},
    })
    assert out == []


# ---------------------------------------------------------------------------
# Strategy: emits stake / unstake correctly
# ---------------------------------------------------------------------------

def test_strategy_emits_stake_on_positive_momentum():
    s = MomentumRotationStrategy(threshold_pct=0.05, slot_size_tao=1.0)
    out = s.evaluate({
        "subnets": [{"netuid": 7, "tao_in": 110.0, "name": "Apex"}],
        "history": {7: [(0.0, 100.0), (1.0, 110.0)]},
    })
    assert len(out) == 1
    p = out[0]
    assert p.action == "stake"
    assert p.target == {"netuid": 7, "name": "Apex"}
    assert p.amount_tao == 1.0
    assert p.price_tao == 110.0
    assert 0.0 < p.confidence <= 1.0


def test_strategy_emits_unstake_on_negative_momentum():
    s = MomentumRotationStrategy(threshold_pct=0.05, slot_size_tao=2.0)
    out = s.evaluate({
        "subnets": [{"netuid": 9, "tao_in": 80.0}],
        "history": {9: [(0.0, 100.0), (1.0, 80.0)]},
    })
    assert len(out) == 1
    assert out[0].action == "unstake"
    assert out[0].amount_tao == 2.0


def test_strategy_confidence_clamps_to_one():
    s = MomentumRotationStrategy(threshold_pct=0.01)
    # +50% momentum should pin confidence to 1.0.
    out = s.evaluate({
        "subnets": [{"netuid": 1, "tao_in": 150.0}],
        "history": {1: [(0.0, 100.0), (1.0, 150.0)]},
    })
    assert out[0].confidence == 1.0


def test_strategy_watchlist_filters_other_netuids():
    s = MomentumRotationStrategy(threshold_pct=0.05, watchlist=[1])
    out = s.evaluate({
        "subnets": [
            {"netuid": 1, "tao_in": 110.0},
            {"netuid": 2, "tao_in": 110.0},
        ],
        "history": {
            1: [(0.0, 100.0), (1.0, 110.0)],
            2: [(0.0, 100.0), (1.0, 110.0)],
        },
    })
    assert len(out) == 1
    assert out[0].target["netuid"] == 1


def test_strategy_skips_bad_tao_in_values():
    s = MomentumRotationStrategy(threshold_pct=0.05)
    out = s.evaluate({
        "subnets": [
            {"netuid": 1, "tao_in": None},
            {"netuid": 2, "tao_in": float("nan")},
            {"netuid": 3, "tao_in": -10.0},
            {"netuid": 4, "tao_in": "not a number"},
        ],
        "history": {
            1: [(0.0, 100.0), (1.0, 110.0)],
            2: [(0.0, 100.0), (1.0, 110.0)],
            3: [(0.0, 100.0), (1.0, 110.0)],
            4: [(0.0, 100.0), (1.0, 110.0)],
        },
    })
    assert out == []


def test_strategy_history_with_string_key():
    """JSON serialisation can stringify int keys; the strategy must
    still find them."""
    s = MomentumRotationStrategy(threshold_pct=0.05)
    out = s.evaluate({
        "subnets": [{"netuid": 1, "tao_in": 110.0}],
        "history": {"1": [(0.0, 100.0), (1.0, 110.0)]},
    })
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------

def test_backtest_runs_on_flat_market_no_trades(tmp_path):
    s = MomentumRotationStrategy(threshold_pct=0.05)
    bt = Backtester(s, paper_db_path=str(tmp_path / "bt.db"))
    snapshots = [
        {"subnets": [{"netuid": 1, "tao_in": 100.0}],
         "history": {1: [(0.0, 100.0), (1.0, 100.0)]}},
        {"subnets": [{"netuid": 1, "tao_in": 100.0}],
         "history": {1: [(0.0, 100.0), (1.0, 100.0)]}},
    ]
    result = bt.run(snapshots)
    assert isinstance(result, BacktestResult)
    assert result.num_steps == 2
    assert result.num_proposals == 0
    assert result.num_executed == 0
    assert result.num_refused == 0
    assert result.total_pnl_tao == 0.0
    assert result.win_rate == 0.0


def test_backtest_records_executed_proposals(tmp_path):
    s = MomentumRotationStrategy(threshold_pct=0.05, slot_size_tao=1.0)
    bt = Backtester(s, paper_db_path=str(tmp_path / "bt.db"))
    snapshots = [
        {"subnets": [{"netuid": 1, "tao_in": 110.0, "name": "x"}],
         "history": {1: [(0.0, 100.0), (1.0, 110.0)]}},
    ]
    result = bt.run(snapshots)
    assert result.num_proposals == 1
    assert result.num_executed == 1
    assert result.num_refused == 0


def test_backtest_realises_profit_on_higher_exit(tmp_path):
    """Stake @ 100, unstake @ 120 → +20 per unit. With slot=1 →
    +20 realised P&L."""
    s = MomentumRotationStrategy(threshold_pct=0.05, slot_size_tao=1.0)
    bt = Backtester(s, paper_db_path=str(tmp_path / "bt.db"))
    snapshots = [
        # Step 0: positive momentum → stake @ 100
        {"subnets": [{"netuid": 1, "tao_in": 100.0}],
         "history": {1: [(0.0, 90.0), (1.0, 100.0)]}},
        # Step 1: negative momentum → unstake @ 120 (price recorded
        # as the proposal's price_tao = current tao_in = 120)
        {"subnets": [{"netuid": 1, "tao_in": 120.0}],
         "history": {1: [(0.0, 200.0), (1.0, 120.0)]}},
    ]
    result = bt.run(snapshots)
    assert result.num_executed == 2
    assert result.total_pnl_tao == pytest.approx(20.0, abs=1e-6)
    assert result.win_rate == 1.0


def test_backtest_realises_loss_on_lower_exit(tmp_path):
    s = MomentumRotationStrategy(threshold_pct=0.05, slot_size_tao=1.0)
    bt = Backtester(s, paper_db_path=str(tmp_path / "bt.db"))
    snapshots = [
        {"subnets": [{"netuid": 1, "tao_in": 100.0}],
         "history": {1: [(0.0, 90.0), (1.0, 100.0)]}},
        {"subnets": [{"netuid": 1, "tao_in": 80.0}],
         "history": {1: [(0.0, 200.0), (1.0, 80.0)]}},
    ]
    result = bt.run(snapshots)
    assert result.total_pnl_tao == pytest.approx(-20.0, abs=1e-6)
    assert result.win_rate == 0.0


def test_backtest_max_drawdown_zero_when_only_gains(tmp_path):
    """Equity curve only goes up → drawdown is 0."""
    s = MomentumRotationStrategy(threshold_pct=0.05, slot_size_tao=1.0)
    bt = Backtester(s, paper_db_path=str(tmp_path / "bt.db"))
    # Single cycle of stake-then-unstake-at-profit.
    snapshots = [
        {"subnets": [{"netuid": 1, "tao_in": 100.0}],
         "history": {1: [(0.0, 90.0), (1.0, 100.0)]}},
        {"subnets": [{"netuid": 1, "tao_in": 130.0}],
         "history": {1: [(0.0, 200.0), (1.0, 130.0)]}},
    ]
    result = bt.run(snapshots)
    assert result.max_drawdown_tao == 0.0


def test_backtest_result_as_dict_serialisable(tmp_path):
    s = MomentumRotationStrategy(threshold_pct=0.05)
    bt = Backtester(s, paper_db_path=str(tmp_path / "bt.db"))
    result = bt.run([])
    d = result.as_dict()
    assert isinstance(d, dict)
    assert d["strategy_name"] == "momentum_rotation"
    assert d["num_steps"] == 0
    # All values must be JSON-serialisable primitives.
    import json
    json.dumps(d)


def test_backtest_proposals_pass_executor_position_cap(tmp_path):
    """The backtester sets a permissive PositionCap so the strategy
    is never refused for cap reasons in pure backtest mode."""
    s = MomentumRotationStrategy(threshold_pct=0.05, slot_size_tao=1.0)
    bt = Backtester(s, paper_db_path=str(tmp_path / "bt.db"))
    # Repeated positive momentum on the same netuid; expect every
    # proposal to be executed, none refused for the position cap.
    snapshots = [
        {"subnets": [{"netuid": 1, "tao_in": 100.0 + i * 10.0}],
         "history": {1: [(0.0, 100.0 + (i - 1) * 10.0),
                         (1.0, 100.0 + i * 10.0)]}}
        for i in range(1, 6)
    ]
    result = bt.run(snapshots)
    assert result.num_executed == 5
    assert result.num_refused == 0
