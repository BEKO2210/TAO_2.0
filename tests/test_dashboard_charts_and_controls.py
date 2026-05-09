"""
Tests for the PR 2L additions to ``tao_swarm.dashboard.trading_view``:

- ``equity_curve`` over a sequence of TradeRecord rows.
- ``outcome_distribution`` win/loss/breakeven counters.
- ``halt_runner_via_killswitch`` writes the kill-switch file the
  runner watches.

These exercise the helper layer the Streamlit panel calls — the
panel itself is hard to unit-test, but the data model is pure and
can be locked in.
"""

from __future__ import annotations

import time

import pytest

from tao_swarm.dashboard.trading_view import (
    EquityPoint,
    OutcomeDistribution,
    equity_curve,
    halt_runner_via_killswitch,
    outcome_distribution,
)
from tao_swarm.trading import KillSwitch, PaperLedger, TradeRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _record(
    pnl: float = 0.0, action: str = "stake", paper: bool = True,
    ts: float | None = None,
) -> TradeRecord:
    return TradeRecord(
        strategy="t",
        action=action,
        target={"netuid": 1},
        amount_tao=1.0,
        price_tao=100.0,
        realised_pnl_tao=pnl,
        paper=paper,
        timestamp=ts if ts is not None else time.time(),
    )


def _seed_ledger(tmp_path) -> PaperLedger:
    ledger = PaperLedger(str(tmp_path / "ledger.db"))
    base = 1_700_000_000.0
    ledger.record_trade(_record(pnl=0.0, action="stake", ts=base))
    ledger.record_trade(_record(pnl=10.0, action="unstake_realised", ts=base + 60))
    ledger.record_trade(_record(pnl=-3.0, action="unstake_realised", ts=base + 120))
    ledger.record_trade(_record(pnl=5.0, action="unstake_realised", ts=base + 180))
    ledger.record_trade(_record(
        pnl=0.0, action="stake_failed", paper=False, ts=base + 200,
    ))
    return ledger


# ---------------------------------------------------------------------------
# equity_curve
# ---------------------------------------------------------------------------

def test_equity_curve_empty_input_yields_empty_curve():
    assert equity_curve([]) == []


def test_equity_curve_accumulates_realised_pnl(tmp_path):
    ledger = _seed_ledger(tmp_path)
    curve = equity_curve(ledger.list_trades(limit=10))
    # 4 non-failed rows in chronological order: 0, +10, -3, +5.
    assert [round(p.cumulative_pnl_tao, 4) for p in curve] == [0.0, 10.0, 7.0, 12.0]
    assert [round(p.timestamp, 0) for p in curve] == sorted(
        [p.timestamp for p in curve]
    )


def test_equity_curve_sorts_chronologically(tmp_path):
    """Even if the caller passes trades desc, equity curve is asc."""
    ledger = _seed_ledger(tmp_path)
    desc = sorted(
        ledger.list_trades(limit=10),
        key=lambda r: r.timestamp, reverse=True,
    )
    curve = equity_curve(desc)
    assert [round(p.cumulative_pnl_tao, 4) for p in curve] == [0.0, 10.0, 7.0, 12.0]


def test_equity_curve_excludes_failed_attempts(tmp_path):
    """Failed-live audit rows must not enter the realised-P&L sum."""
    ledger = _seed_ledger(tmp_path)
    curve = equity_curve(ledger.list_trades(limit=10))
    # One stake_failed row in the seeded ledger; should be excluded.
    assert len(curve) == 4


def test_equity_curve_returns_equity_points():
    rec = _record(pnl=2.5, action="unstake_realised", ts=1.0)
    curve = equity_curve([rec])
    assert len(curve) == 1
    assert isinstance(curve[0], EquityPoint)
    assert curve[0].cumulative_pnl_tao == 2.5


# ---------------------------------------------------------------------------
# outcome_distribution
# ---------------------------------------------------------------------------

def test_outcome_distribution_empty():
    d = outcome_distribution([])
    assert isinstance(d, OutcomeDistribution)
    assert d.wins == 0
    assert d.losses == 0
    assert d.win_rate == 0.0
    assert d.total_realised_pnl_tao == 0.0


def test_outcome_distribution_counts_wins_and_losses(tmp_path):
    ledger = _seed_ledger(tmp_path)
    d = outcome_distribution(ledger.list_trades(limit=10))
    # Realised: +10, -3, +5 (the stake row has 0 P&L; failed row excluded)
    assert d.wins == 2
    assert d.losses == 1
    assert d.total_realised_pnl_tao == pytest.approx(12.0)
    assert d.largest_win_tao == pytest.approx(10.0)
    assert d.largest_loss_tao == pytest.approx(-3.0)
    assert d.win_rate == pytest.approx(2 / 3, abs=1e-3)


def test_outcome_distribution_excludes_failed_attempts():
    rows = [
        _record(pnl=10.0, action="unstake_realised"),
        _record(pnl=0.0, action="stake_failed"),
        _record(pnl=-5.0, action="unstake_failed"),  # also failed
    ]
    d = outcome_distribution(rows)
    assert d.wins == 1
    assert d.losses == 0


def test_outcome_distribution_breakeven_realised_close():
    """A realised close with 0 P&L is a break-even, not a win or loss."""
    rows = [
        _record(pnl=0.0, action="unstake_realised"),
        _record(pnl=10.0, action="unstake_realised"),
    ]
    d = outcome_distribution(rows)
    assert d.wins == 1
    assert d.losses == 0
    assert d.breakevens == 1


def test_outcome_distribution_as_dict_json_serialisable():
    import json
    rows = [_record(pnl=10.0, action="unstake_realised")]
    d = outcome_distribution(rows)
    payload = d.as_dict()
    json.dumps(payload)
    assert payload["wins"] == 1


def test_outcome_distribution_no_realised_when_only_opens():
    """If no rows have non-zero realised P&L (e.g. only opening
    stakes), wins/losses are all zero."""
    rows = [
        _record(pnl=0.0, action="stake"),
        _record(pnl=0.0, action="stake"),
    ]
    d = outcome_distribution(rows)
    assert d.wins == 0
    assert d.losses == 0
    assert d.win_rate == 0.0


# ---------------------------------------------------------------------------
# halt_runner_via_killswitch
# ---------------------------------------------------------------------------

def test_halt_writes_kill_switch_file(tmp_path):
    kill = tmp_path / "subdir" / ".kill"
    halt_runner_via_killswitch(kill, reason="test halt")
    assert kill.exists()
    contents = kill.read_text(encoding="utf-8")
    assert "test halt" in contents


def test_halt_appends_rather_than_overwriting(tmp_path):
    """Multiple halts must stack as an audit log, not clobber."""
    kill = tmp_path / ".kill"
    halt_runner_via_killswitch(kill, reason="first")
    halt_runner_via_killswitch(kill, reason="second")
    contents = kill.read_text(encoding="utf-8")
    assert "first" in contents
    assert "second" in contents


def test_halt_creates_parent_directories(tmp_path):
    kill = tmp_path / "deeply" / "nested" / "kill_path" / ".kill"
    assert not kill.parent.exists()
    halt_runner_via_killswitch(kill, reason="x")
    assert kill.exists()


def test_halt_trips_kill_switch_observed_by_runner(tmp_path):
    """End-to-end with the real KillSwitch class: after halt, the
    KillSwitch reports tripped=True for that path."""
    kill = tmp_path / ".kill"
    ks_before = KillSwitch(flag_path=str(kill)).state()
    assert ks_before.tripped is False

    halt_runner_via_killswitch(kill, reason="dashboard test")

    ks_after = KillSwitch(flag_path=str(kill)).state()
    assert ks_after.tripped is True
    assert ks_after.source == "file"


def test_halt_default_reason_is_used(tmp_path):
    kill = tmp_path / ".kill"
    halt_runner_via_killswitch(kill)  # no reason kwarg
    assert kill.exists()
    assert "dashboard halt" in kill.read_text()
