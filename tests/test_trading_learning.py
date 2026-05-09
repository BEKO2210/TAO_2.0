"""
Tests for the learning layer added in PR 2M:

- ``PerformanceTracker.stats_for`` and ``all_stats``
- ``inverse_loss_weights`` and ``uniform_weights``
- ``EnsembleStrategy`` evaluate / meta / weight thresholding
- ``ConfidenceCalibrator`` bucketing
- ``tao-swarm trade learning-report`` CLI smoke test

These exercise the data-model layer; the integration with a live
TradingRunner is implicitly covered by the executor's existing
contract — the ensemble is a regular Strategy.
"""

from __future__ import annotations

import json
import time

import pytest
from click.testing import CliRunner

from tao_swarm.cli.tao_swarm import cli
from tao_swarm.trading import (
    CalibrationBucket,
    ConfidenceCalibrator,
    EnsembleStrategy,
    PaperLedger,
    PerformanceTracker,
    Strategy,
    StrategyMeta,
    StrategyPerformance,
    TradeProposal,
    TradeRecord,
    inverse_loss_weights,
    uniform_weights,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed(ledger: PaperLedger, strategy: str,
          rows: list[tuple[float, str, float]]) -> None:
    """rows = list of (ts, action, pnl)."""
    for ts, action, pnl in rows:
        ledger.record_trade(TradeRecord(
            strategy=strategy, action=action,
            target={"netuid": 1}, amount_tao=1.0, price_tao=100.0,
            realised_pnl_tao=pnl, paper=True, timestamp=ts,
        ))


def _scripted_strategy(name: str, proposals_per_call: list[list[TradeProposal]]):
    """Build a tiny stub strategy that emits a scripted sequence."""

    class _S(Strategy):
        STRATEGY_NAME = name

        def __init__(self) -> None:
            self._calls = 0

        def meta(self) -> StrategyMeta:
            return StrategyMeta(
                name=name, version="0.1",
                max_position_tao=2.0, max_daily_loss_tao=2.0,
                actions_used=("stake", "unstake"),
            )

        def evaluate(self, _ms):
            if self._calls < len(proposals_per_call):
                out = proposals_per_call[self._calls]
            else:
                out = []
            self._calls += 1
            return out

    return _S()


def _proposal(amount: float = 1.0, action: str = "stake",
              netuid: int = 1, confidence: float = 0.5) -> TradeProposal:
    return TradeProposal(
        action=action, target={"netuid": netuid},
        amount_tao=amount, price_tao=100.0,
        confidence=confidence, reasoning="t",
    )


# ---------------------------------------------------------------------------
# PerformanceTracker
# ---------------------------------------------------------------------------

def test_tracker_constructor_validates(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    with pytest.raises(ValueError):
        PerformanceTracker(ledger, min_trades=0)


def test_tracker_rejects_invalid_window(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    tracker = PerformanceTracker(ledger)
    with pytest.raises(ValueError):
        tracker.stats_for("x", window_days=0)
    with pytest.raises(ValueError):
        tracker.stats_for("x", window_trades=0)
    with pytest.raises(ValueError):
        tracker.stats_for("")


def test_tracker_empty_ledger_reports_insufficient(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    tracker = PerformanceTracker(ledger)
    perf = tracker.stats_for("nope")
    assert isinstance(perf, StrategyPerformance)
    assert perf.num_realised_closes == 0
    assert perf.insufficient_data is True


def test_tracker_computes_pnl_and_win_rate(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "alpha", [
        (base - 1000, "stake", 0.0),
        (base - 900, "unstake_realised", 5.0),
        (base - 800, "stake", 0.0),
        (base - 700, "unstake_realised", -2.0),
        (base - 600, "stake", 0.0),
        (base - 500, "unstake_realised", 3.0),
    ])
    tracker = PerformanceTracker(ledger, min_trades=2)
    perf = tracker.stats_for("alpha", window_days=1, window_trades=100)
    assert perf.num_realised_closes == 3
    assert perf.realised_pnl_tao == pytest.approx(6.0)
    assert perf.win_rate == pytest.approx(2 / 3, abs=1e-3)
    assert perf.insufficient_data is False


def test_tracker_excludes_failed_attempts(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "x", [
        (base - 100, "unstake_realised", 5.0),
        (base - 90, "stake_failed", 0.0),
        (base - 80, "unstake_realised", -1.0),
    ])
    tracker = PerformanceTracker(ledger, min_trades=1)
    perf = tracker.stats_for("x")
    assert perf.num_realised_closes == 2
    assert perf.num_failed == 1
    assert perf.realised_pnl_tao == pytest.approx(4.0)


def test_tracker_respects_window_days(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    now = time.time()
    very_old = now - 60 * 86400  # 60 days ago
    recent = now - 1 * 86400
    _seed(ledger, "x", [
        (very_old, "unstake_realised", 100.0),
        (recent, "unstake_realised", 1.0),
    ])
    tracker = PerformanceTracker(ledger, min_trades=1)
    perf = tracker.stats_for("x", window_days=7)
    # Only the 1-day-old trade should land in the window.
    assert perf.num_realised_closes == 1
    assert perf.realised_pnl_tao == pytest.approx(1.0)


def test_tracker_all_stats_lists_every_strategy(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "alpha", [(base, "unstake_realised", 1.0)])
    _seed(ledger, "beta", [(base, "unstake_realised", -1.0)])
    tracker = PerformanceTracker(ledger, min_trades=1)
    out = tracker.all_stats()
    assert set(out) == {"alpha", "beta"}


def test_tracker_sharpe_zero_on_constant_pnl(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "x", [(base + i, "unstake_realised", 5.0) for i in range(10)])
    tracker = PerformanceTracker(ledger, min_trades=1)
    perf = tracker.stats_for("x")
    # All trades are identical → variance is zero → sharpe is 0.
    assert perf.sharpe == 0.0


# ---------------------------------------------------------------------------
# Weight functions
# ---------------------------------------------------------------------------

def test_uniform_weights_distributes_equally():
    w = uniform_weights(["a", "b", "c"])
    assert w == {"a": 1/3, "b": 1/3, "c": 1/3}


def test_uniform_weights_empty_input():
    assert uniform_weights([]) == {}


def test_inverse_loss_weights_falls_back_to_uniform_with_no_tracker():
    w = inverse_loss_weights(["a", "b"], tracker=None)
    assert w == {"a": 0.5, "b": 0.5}


def test_inverse_loss_weights_favours_winner(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "winner", [
        (base + i, "unstake_realised", 5.0) for i in range(10)
    ])
    _seed(ledger, "loser", [
        (base + i, "unstake_realised", -3.0) for i in range(10)
    ])
    tracker = PerformanceTracker(ledger, min_trades=1)
    w = inverse_loss_weights(["winner", "loser"], tracker, window_days=30)
    # Winner gets more weight than loser.
    assert w["winner"] > w["loser"]
    # Both should still be > 0 because of the floor.
    assert w["loser"] > 0
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)


def test_inverse_loss_weights_uses_uniform_baseline_for_insufficient_data(tmp_path):
    """A strategy with no data should not pin the whole vector to
    zero — it gets the uniform baseline."""
    ledger = PaperLedger(str(tmp_path / "l.db"))
    tracker = PerformanceTracker(ledger, min_trades=5)
    # No rows for either strategy → both are insufficient.
    w = inverse_loss_weights(["a", "b"], tracker)
    assert w["a"] == pytest.approx(0.5)
    assert w["b"] == pytest.approx(0.5)


def test_inverse_loss_weights_handles_identical_pnl(tmp_path):
    """When both strategies have the same P&L, weights are uniform."""
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "a", [(base + i, "unstake_realised", 1.0) for i in range(10)])
    _seed(ledger, "b", [(base + i, "unstake_realised", 1.0) for i in range(10)])
    tracker = PerformanceTracker(ledger, min_trades=1)
    w = inverse_loss_weights(["a", "b"], tracker, window_days=30)
    assert w["a"] == pytest.approx(0.5, abs=1e-6)
    assert w["b"] == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# EnsembleStrategy
# ---------------------------------------------------------------------------

def test_ensemble_rejects_empty_bases():
    with pytest.raises(ValueError):
        EnsembleStrategy({})


def test_ensemble_rejects_invalid_min_weight():
    s = _scripted_strategy("a", [[]])
    with pytest.raises(ValueError):
        EnsembleStrategy({"a": s}, min_weight=-0.1)
    with pytest.raises(ValueError):
        EnsembleStrategy({"a": s}, min_weight=1.0)


def test_ensemble_meta_aggregates_risk_surface():
    a = _scripted_strategy("a", [[]])
    b = _scripted_strategy("b", [[]])
    e = EnsembleStrategy({"a": a, "b": b})
    m = e.meta()
    assert m.name == "ensemble"
    # Each base declares max_position_tao=2.0; SUM = 4.0
    assert m.max_position_tao == pytest.approx(4.0)
    assert "stake" in m.actions_used
    assert "unstake" in m.actions_used
    assert m.live_trading is False


def test_ensemble_evaluate_combines_proposals_uniformly():
    a = _scripted_strategy("a", [[_proposal(amount=2.0)]])
    b = _scripted_strategy("b", [[_proposal(amount=4.0)]])
    e = EnsembleStrategy({"a": a, "b": b}, weight_fn=uniform_weights)
    out = e.evaluate({})
    assert len(out) == 2
    # Uniform weights = 0.5 each. Amounts get scaled.
    amounts = sorted(p.amount_tao for p in out)
    assert amounts == pytest.approx([1.0, 2.0])


def test_ensemble_min_weight_skips_strategies(tmp_path):
    """A strategy below min_weight is skipped entirely (no dust trades)."""
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    # Make 'winner' dominate so 'loser' falls below min_weight=0.4.
    _seed(ledger, "winner", [(base + i, "unstake_realised", 100.0) for i in range(10)])
    _seed(ledger, "loser", [(base + i, "unstake_realised", -100.0) for i in range(10)])
    tracker = PerformanceTracker(ledger, min_trades=1)

    a = _scripted_strategy("winner", [[_proposal(amount=2.0)]])
    b = _scripted_strategy("loser", [[_proposal(amount=2.0)]])

    def fn(names, t):
        return inverse_loss_weights(names, t, window_days=30, floor=0.0)

    e = EnsembleStrategy(
        {"winner": a, "loser": b},
        weight_fn=fn, tracker=tracker, min_weight=0.4,
    )
    out = e.evaluate({})
    # Only the winner emitted (loser's weight ~ floor=0 → below 0.4).
    bases_seen = {p.reasoning.split(":")[1].split(" ")[0] for p in out}
    assert "winner" in bases_seen
    assert "loser" not in bases_seen


def test_ensemble_tags_reasoning_with_base_and_weight():
    a = _scripted_strategy("a", [[_proposal(amount=1.0)]])
    e = EnsembleStrategy({"a": a}, weight_fn=uniform_weights)
    out = e.evaluate({})
    assert out[0].reasoning.startswith("[ensemble:a w=")


def test_ensemble_isolates_base_failure():
    """If one base raises in evaluate, the others still run."""
    a = _scripted_strategy("a", [[_proposal(amount=1.0)]])

    class _Boom(Strategy):
        STRATEGY_NAME = "boom"
        def meta(self):
            return StrategyMeta(
                name="boom", version="0.1",
                max_position_tao=1.0, max_daily_loss_tao=1.0,
            )
        def evaluate(self, _ms):
            raise RuntimeError("base broken")

    e = EnsembleStrategy({"a": a, "boom": _Boom()}, weight_fn=uniform_weights)
    out = e.evaluate({})
    assert len(out) == 1
    assert "[ensemble:a" in out[0].reasoning


def test_ensemble_live_trading_requires_all_bases_opted_in():
    a = _scripted_strategy("a", [[]])  # paper-only by default
    with pytest.raises(ValueError):
        EnsembleStrategy({"a": a}, live_trading=True)


def test_ensemble_current_weights_returns_vector():
    a = _scripted_strategy("a", [[]])
    b = _scripted_strategy("b", [[]])
    e = EnsembleStrategy({"a": a, "b": b}, weight_fn=uniform_weights)
    w = e.current_weights()
    assert sum(w.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# ConfidenceCalibrator
# ---------------------------------------------------------------------------

def test_calibrator_rejects_invalid_args(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    with pytest.raises(ValueError):
        ConfidenceCalibrator(ledger, num_buckets=1)
    with pytest.raises(ValueError):
        ConfidenceCalibrator(ledger, min_samples_per_bucket=0)


def test_calibrator_buckets_explicit_pairs(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    c = ConfidenceCalibrator(ledger, num_buckets=4, min_samples_per_bucket=2)
    pairs = [
        # Low-confidence trades — half win
        (0.1, 1.0), (0.15, -1.0), (0.05, 1.0), (0.2, -1.0),
        # High-confidence trades — most win
        (0.85, 5.0), (0.9, 4.0), (0.95, 3.0), (0.99, -2.0),
    ]
    buckets = c.buckets_for("x", confidence_pairs=pairs)
    assert len(buckets) == 4
    assert all(isinstance(b, CalibrationBucket) for b in buckets)
    # The last (high-confidence) bucket should have a higher win rate
    # than the first (low-confidence) bucket.
    assert buckets[-1].realised_win_rate > buckets[0].realised_win_rate


def test_calibrator_flags_insufficient_data(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    c = ConfidenceCalibrator(ledger, num_buckets=4, min_samples_per_bucket=10)
    pairs = [(0.1, 1.0), (0.9, 1.0)]  # only 2 total samples
    buckets = c.buckets_for("x", confidence_pairs=pairs)
    assert all(b.insufficient_data for b in buckets)


def test_calibrator_excludes_out_of_range_confidence(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    c = ConfidenceCalibrator(ledger, num_buckets=2, min_samples_per_bucket=1)
    pairs = [
        (0.5, 1.0),       # in range
        (-0.5, 1.0),      # out of range — drop
        (1.5, 1.0),       # out of range — drop
        (0.99, 1.0),      # in range, in last bucket
    ]
    buckets = c.buckets_for("x", confidence_pairs=pairs)
    assert sum(b.num_samples for b in buckets) == 2


def test_calibrator_high_confidence_lands_in_last_bucket(tmp_path):
    """Confidence==1.0 must land somewhere — last bucket is closed
    on the right."""
    ledger = PaperLedger(str(tmp_path / "l.db"))
    c = ConfidenceCalibrator(ledger, num_buckets=5, min_samples_per_bucket=1)
    pairs = [(1.0, 5.0)]
    buckets = c.buckets_for("x", confidence_pairs=pairs)
    assert buckets[-1].num_samples == 1
    assert sum(b.num_samples for b in buckets) == 1


def test_calibrator_as_dict_serialisable(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    c = ConfidenceCalibrator(ledger)
    pairs = [(0.5, 1.0)]
    buckets = c.buckets_for("x", confidence_pairs=pairs)
    payload = [b.as_dict() for b in buckets]
    json.dumps(payload)


# ---------------------------------------------------------------------------
# CLI: tao-swarm trade learning-report
# ---------------------------------------------------------------------------

def test_cli_learning_report_runs_on_empty_ledger(tmp_path):
    ledger_path = tmp_path / "trades.db"
    PaperLedger(str(ledger_path))  # create empty
    runner = CliRunner()
    result = runner.invoke(
        cli, ["trade", "learning-report", "--ledger-db", str(ledger_path)],
    )
    assert result.exit_code == 0
    assert "no strategies" in result.output.lower()


def test_cli_learning_report_shows_strategy_stats(tmp_path):
    ledger_path = tmp_path / "trades.db"
    ledger = PaperLedger(str(ledger_path))
    base = time.time()
    _seed(ledger, "alpha", [
        (base - 100, "unstake_realised", 5.0),
        (base - 50, "unstake_realised", 3.0),
    ])
    runner = CliRunner()
    result = runner.invoke(
        cli, [
            "trade", "learning-report",
            "--ledger-db", str(ledger_path),
            "--min-trades", "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "alpha" in result.output


def test_cli_learning_report_json_mode(tmp_path):
    ledger_path = tmp_path / "trades.db"
    ledger = PaperLedger(str(ledger_path))
    _seed(ledger, "alpha", [(time.time() - 10, "unstake_realised", 1.0)])
    runner = CliRunner()
    result = runner.invoke(
        cli, [
            "trade", "learning-report",
            "--ledger-db", str(ledger_path),
            "--min-trades", "1",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "alpha" in payload
    assert "realised_pnl_tao" in payload["alpha"]


def test_cli_learning_report_shows_suggested_weights(tmp_path):
    ledger_path = tmp_path / "trades.db"
    ledger = PaperLedger(str(ledger_path))
    base = time.time()
    _seed(ledger, "winner", [(base - i, "unstake_realised", 5.0) for i in range(5)])
    _seed(ledger, "loser", [(base - i - 100, "unstake_realised", -3.0) for i in range(5)])
    runner = CliRunner()
    result = runner.invoke(
        cli, [
            "trade", "learning-report",
            "--ledger-db", str(ledger_path),
            "--min-trades", "1",
        ],
    )
    assert result.exit_code == 0
    assert "Suggested ensemble weights" in result.output
