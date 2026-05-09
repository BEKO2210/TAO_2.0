"""
Tests for PR 2N — ensemble runner integration:

- CLI ``_load_strategy`` accepts ``ensemble:all`` and
  ``ensemble:A,B`` and returns a wired :class:`EnsembleStrategy`.
- Unknown bases produce a clear ClickException.
- ``_resolve_ensemble_bases`` parses correctly.
- Dashboard helpers ``per_strategy_snapshot`` and
  ``per_strategy_equity_curves`` produce expected shapes.
"""

from __future__ import annotations

import time

import pytest
from click import ClickException

from tao_swarm.cli.tao_swarm import (
    _build_registry,
    _build_weight_fn,
    _load_strategy,
    _resolve_ensemble_bases,
)
from tao_swarm.dashboard.trading_view import (
    StrategySnapshot,
    per_strategy_equity_curves,
    per_strategy_snapshot,
)
from tao_swarm.trading import (
    EnsembleStrategy,
    PaperLedger,
    PerformanceTracker,
    TradeRecord,
    inverse_loss_weights,
    uniform_weights,
)

# ---------------------------------------------------------------------------
# CLI ensemble parsing
# ---------------------------------------------------------------------------

def test_resolve_ensemble_bases_all():
    reg = _build_registry()
    bases = _resolve_ensemble_bases("all", reg)
    assert "momentum_rotation" in bases
    assert "mean_reversion" in bases


def test_resolve_ensemble_bases_subset():
    reg = _build_registry()
    bases = _resolve_ensemble_bases("momentum_rotation", reg)
    assert bases == ["momentum_rotation"]


def test_resolve_ensemble_bases_comma_separated():
    reg = _build_registry()
    bases = _resolve_ensemble_bases(
        "momentum_rotation, mean_reversion", reg,
    )
    assert bases == ["momentum_rotation", "mean_reversion"]


def test_resolve_ensemble_bases_rejects_unknown():
    reg = _build_registry()
    with pytest.raises(ClickException):
        _resolve_ensemble_bases("does_not_exist", reg)


def test_resolve_ensemble_bases_rejects_empty_spec():
    reg = _build_registry()
    with pytest.raises(ClickException):
        _resolve_ensemble_bases("   , ,  ", reg)


def test_build_weight_fn_recognised():
    assert _build_weight_fn("uniform") is uniform_weights
    assert _build_weight_fn("inverse_loss") is inverse_loss_weights


def test_build_weight_fn_unknown_raises():
    with pytest.raises(ClickException):
        _build_weight_fn("bogus")


# ---------------------------------------------------------------------------
# CLI _load_strategy with ensemble syntax
# ---------------------------------------------------------------------------

def test_load_strategy_builds_ensemble_all(tmp_path):
    s = _load_strategy(
        "ensemble:all",
        ledger_db=tmp_path / "trades.db",
        weight_fn_name="inverse_loss",
        threshold_pct=0.05, slot_size_tao=1.0,
    )
    assert isinstance(s, EnsembleStrategy)
    bases = s.base_names
    assert "momentum_rotation" in bases
    assert "mean_reversion" in bases


def test_load_strategy_builds_ensemble_subset(tmp_path):
    s = _load_strategy(
        "ensemble:momentum_rotation",
        ledger_db=tmp_path / "trades.db",
        threshold_pct=0.05, slot_size_tao=1.0,
    )
    assert isinstance(s, EnsembleStrategy)
    assert s.base_names == ("momentum_rotation",)


def test_load_strategy_ensemble_picks_uniform_weight_fn(tmp_path):
    s = _load_strategy(
        "ensemble:all",
        ledger_db=tmp_path / "trades.db",
        weight_fn_name="uniform",
        threshold_pct=0.05, slot_size_tao=1.0,
    )
    weights = s.current_weights()
    # Uniform on the two built-ins → 0.5 each.
    assert weights == pytest.approx({"momentum_rotation": 0.5, "mean_reversion": 0.5})


def test_load_strategy_ensemble_unknown_base_raises(tmp_path):
    with pytest.raises(ClickException):
        _load_strategy(
            "ensemble:nope",
            ledger_db=tmp_path / "trades.db",
            threshold_pct=0.05, slot_size_tao=1.0,
        )


def test_load_strategy_plain_name_still_works():
    """Backwards compatibility: a plain strategy name continues to
    return that strategy directly (not wrapped in an ensemble)."""
    from tao_swarm.trading.strategies.momentum_rotation import (
        MomentumRotationStrategy,
    )

    s = _load_strategy(
        "momentum_rotation",
        threshold_pct=0.05, slot_size_tao=1.0,
    )
    assert isinstance(s, MomentumRotationStrategy)


def test_load_strategy_ensemble_without_colon_defaults_to_all(tmp_path):
    """``--strategy ensemble`` (no colon) is shorthand for ``ensemble:all``."""
    s = _load_strategy(
        "ensemble",
        ledger_db=tmp_path / "trades.db",
        threshold_pct=0.05, slot_size_tao=1.0,
    )
    assert isinstance(s, EnsembleStrategy)


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def _seed(ledger: PaperLedger, strategy: str, rows: list[tuple[float, str, float]]):
    for ts, action, pnl in rows:
        ledger.record_trade(TradeRecord(
            strategy=strategy, action=action,
            target={"netuid": 1}, amount_tao=1.0, price_tao=100.0,
            realised_pnl_tao=pnl, paper=True, timestamp=ts,
        ))


def test_per_strategy_snapshot_returns_sorted_rows(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "alpha", [(base + i, "unstake_realised", 5.0) for i in range(5)])
    _seed(ledger, "beta", [(base + i, "unstake_realised", -2.0) for i in range(5)])
    tracker = PerformanceTracker(ledger, min_trades=1)
    rows = per_strategy_snapshot(tracker, ["alpha", "beta"], window_days=30)
    assert len(rows) == 2
    # Sorted descending by P&L → alpha (winner) comes first.
    assert rows[0].strategy == "alpha"
    assert rows[1].strategy == "beta"
    assert all(isinstance(r, StrategySnapshot) for r in rows)


def test_per_strategy_snapshot_inserts_weight(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    _seed(ledger, "alpha", [(time.time(), "unstake_realised", 1.0)])
    tracker = PerformanceTracker(ledger, min_trades=1)
    rows = per_strategy_snapshot(
        tracker, ["alpha"],
        weights={"alpha": 0.7, "ghost": 0.3},
    )
    assert rows[0].ensemble_weight == 0.7


def test_per_strategy_snapshot_insufficient_pushed_to_bottom(tmp_path):
    """Insufficient-data strategies sort below those with data."""
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "alpha", [(base + i, "unstake_realised", 5.0) for i in range(5)])
    _seed(ledger, "weak", [(base, "unstake_realised", 99.0)])  # only 1 close
    tracker = PerformanceTracker(ledger, min_trades=5)
    rows = per_strategy_snapshot(tracker, ["alpha", "weak"], window_days=30)
    # 'weak' has higher P&L but is insufficient → ranks below 'alpha'.
    assert rows[0].strategy == "alpha"
    assert rows[1].strategy == "weak"
    assert rows[1].insufficient_data is True


def test_per_strategy_snapshot_as_dict_serialisable(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    _seed(ledger, "alpha", [(time.time(), "unstake_realised", 1.0)])
    tracker = PerformanceTracker(ledger, min_trades=1)
    rows = per_strategy_snapshot(tracker, ["alpha"])
    import json
    json.dumps(rows[0].as_dict())


def test_per_strategy_equity_curves_keyed_by_strategy(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    base = time.time()
    _seed(ledger, "alpha", [(base + i, "unstake_realised", 1.0) for i in range(3)])
    _seed(ledger, "beta", [(base + i, "unstake_realised", -1.0) for i in range(3)])
    out = per_strategy_equity_curves(ledger, ["alpha", "beta"])
    assert set(out) == {"alpha", "beta"}
    # alpha curve cumulates to +3, beta to -3.
    assert out["alpha"][-1].cumulative_pnl_tao == pytest.approx(3.0)
    assert out["beta"][-1].cumulative_pnl_tao == pytest.approx(-3.0)


def test_per_strategy_equity_curves_empty_strategy(tmp_path):
    ledger = PaperLedger(str(tmp_path / "l.db"))
    out = per_strategy_equity_curves(ledger, ["never_traded"])
    assert out == {"never_traded": []}
