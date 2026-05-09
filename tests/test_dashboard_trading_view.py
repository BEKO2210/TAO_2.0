"""
Tests for the dashboard's Trading-panel helpers and the runner's
status-file dump that feeds them.

Coverage
========

trading_view module:
- ``load_runner_status`` returns ``None`` for missing / malformed
  files.
- ``load_runner_status`` parses a valid JSON dump.
- ``summarise_ledger`` aggregates paper / live / failed counts and
  realised P&L.
- ``trades_to_table_rows`` flattens TradeRecord into dashboard
  columns; tx_hash / hotkey are truncated.
- ``runner_health_label`` maps state → (label, semantic colour).

TradingRunner.dump_status:
- Writes a valid JSON file at the requested path.
- Round-trips through ``load_runner_status``.
- Atomic write (no leftover .tmp files).
- ``status_file=`` constructor argument auto-dumps each tick.
"""

from __future__ import annotations

import json

import pytest

from tao_swarm.dashboard.trading_view import (
    LedgerSummary,
    load_runner_status,
    runner_health_label,
    summarise_ledger,
    trades_to_table_rows,
)
from tao_swarm.trading import (
    DailyLossLimit,
    Executor,
    KillSwitch,
    PaperLedger,
    PositionCap,
    Strategy,
    StrategyMeta,
    TradeProposal,
    TradeRecord,
    TradingRunner,
    WalletMode,
)

# ---------------------------------------------------------------------------
# load_runner_status
# ---------------------------------------------------------------------------

def test_load_runner_status_missing_file_returns_none(tmp_path):
    assert load_runner_status(tmp_path / "nope.json") is None


def test_load_runner_status_malformed_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    assert load_runner_status(p) is None


def test_load_runner_status_non_dict_returns_none(tmp_path):
    p = tmp_path / "list.json"
    p.write_text(json.dumps([1, 2, 3]))
    assert load_runner_status(p) is None


def test_load_runner_status_round_trip(tmp_path):
    p = tmp_path / "ok.json"
    payload = {"state": "running", "ticks": 5, "open_positions": {}}
    p.write_text(json.dumps(payload))
    out = load_runner_status(p)
    assert out == payload


# ---------------------------------------------------------------------------
# summarise_ledger
# ---------------------------------------------------------------------------

def _seed_ledger(tmp_path):
    ledger = PaperLedger(str(tmp_path / "trades.db"))
    ledger.record_trade(TradeRecord(
        strategy="momentum_rotation", action="stake",
        target={"netuid": 1}, amount_tao=1.0, price_tao=100.0,
        realised_pnl_tao=0.0, paper=True,
    ))
    ledger.record_trade(TradeRecord(
        strategy="momentum_rotation", action="unstake_realised",
        target={"netuid": 1}, amount_tao=1.0, price_tao=110.0,
        realised_pnl_tao=10.0, paper=True,
    ))
    ledger.record_trade(TradeRecord(
        strategy="momentum_rotation", action="stake",
        target={"netuid": 2}, amount_tao=2.0, price_tao=200.0,
        realised_pnl_tao=0.0, paper=False, tx_hash="0xabcdef",
    ))
    ledger.record_trade(TradeRecord(
        strategy="momentum_rotation", action="stake_failed",
        target={"netuid": 3}, amount_tao=1.0, price_tao=300.0,
        realised_pnl_tao=0.0, paper=False, tx_hash=None,
    ))
    return ledger


def test_summarise_ledger_counts_paper_live_failed(tmp_path):
    ledger = _seed_ledger(tmp_path)
    summary = summarise_ledger(ledger)
    assert isinstance(summary, LedgerSummary)
    assert summary.total_trades == 4
    assert summary.paper_trades == 2
    assert summary.live_trades == 2
    assert summary.failed_trades == 1
    assert summary.realised_pnl_tao == pytest.approx(10.0)
    assert summary.distinct_strategies == ("momentum_rotation",)


def test_summarise_ledger_filters_by_strategy(tmp_path):
    ledger = _seed_ledger(tmp_path)
    ledger.record_trade(TradeRecord(
        strategy="other_strategy", action="stake",
        target={"netuid": 1}, amount_tao=1.0, price_tao=100.0,
        realised_pnl_tao=0.0, paper=True,
    ))
    summary = summarise_ledger(ledger, strategy="other_strategy")
    assert summary.total_trades == 1
    assert summary.distinct_strategies == ("other_strategy",)


def test_summarise_ledger_empty(tmp_path):
    ledger = PaperLedger(str(tmp_path / "empty.db"))
    summary = summarise_ledger(ledger)
    assert summary.total_trades == 0
    assert summary.paper_trades == 0
    assert summary.realised_pnl_tao == 0.0
    assert summary.last_trade_ts is None


def test_summarise_ledger_as_dict_is_json_serialisable(tmp_path):
    ledger = _seed_ledger(tmp_path)
    summary = summarise_ledger(ledger)
    d = summary.as_dict()
    json.dumps(d)
    assert d["total_trades"] == 4


# ---------------------------------------------------------------------------
# trades_to_table_rows
# ---------------------------------------------------------------------------

def test_trades_to_table_rows_flattens_target(tmp_path):
    ledger = _seed_ledger(tmp_path)
    rows = trades_to_table_rows(ledger.list_trades(limit=10))
    assert len(rows) == 4
    # Every row has the expected dashboard columns.
    expected = {
        "time", "strategy", "action", "netuid", "hotkey",
        "amount_tao", "price_tao", "realised_pnl_tao", "paper", "tx_hash",
    }
    for row in rows:
        assert set(row.keys()) == expected


def test_trades_to_table_rows_truncates_tx_hash(tmp_path):
    ledger = _seed_ledger(tmp_path)
    rows = trades_to_table_rows(ledger.list_trades(limit=10))
    live_rows = [r for r in rows if not r["paper"] and r["tx_hash"]]
    assert live_rows
    for r in live_rows:
        # short ellipsis for display
        assert "…" in r["tx_hash"]


def test_trades_to_table_rows_empty_input():
    assert trades_to_table_rows([]) == []


# ---------------------------------------------------------------------------
# runner_health_label
# ---------------------------------------------------------------------------

def test_runner_health_label_offline_when_none():
    label, colour = runner_health_label(None)
    assert label == "offline"
    assert colour == "secondary"


def test_runner_health_label_states():
    assert runner_health_label({"state": "running"}) == ("running", "success")
    assert runner_health_label({"state": "halted"}) == ("halted", "danger")
    assert runner_health_label({"state": "error"}) == ("error", "warning")
    assert runner_health_label({"state": "idle"})[0] == "idle"


# ---------------------------------------------------------------------------
# TradingRunner.dump_status
# ---------------------------------------------------------------------------

class _NopStrategy(Strategy):
    def __init__(self):
        self._meta = StrategyMeta(
            name="nop", version="1.0",
            max_position_tao=10.0, max_daily_loss_tao=10.0,
        )

    def meta(self):
        return self._meta

    def evaluate(self, _ms):
        return []


def _build_executor(tmp_path):
    ledger = PaperLedger(str(tmp_path / "ledger.db"))
    return Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=KillSwitch(flag_path=str(tmp_path / "no_kill")),
        position_cap=PositionCap(max_per_position_tao=5.0, max_total_tao=20.0),
        daily_loss_limit=DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger),
        ledger=ledger,
    ), ledger


def test_dump_status_writes_json(tmp_path):
    ex, _ = _build_executor(tmp_path)
    runner = TradingRunner(
        strategy=_NopStrategy(), executor=ex, snapshot_fn=lambda: [],
    )
    out = tmp_path / "sub" / "status.json"
    runner.dump_status(out)
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["state"] == "idle"
    assert payload["strategy"] == "nop"


def test_dump_status_round_trips_with_loader(tmp_path):
    ex, _ = _build_executor(tmp_path)
    runner = TradingRunner(
        strategy=_NopStrategy(), executor=ex, snapshot_fn=lambda: [],
    )
    out = tmp_path / "status.json"
    runner.dump_status(out)
    loaded = load_runner_status(out)
    assert loaded == runner.status().as_dict()


def test_dump_status_atomic_no_tmp_leftover(tmp_path):
    ex, _ = _build_executor(tmp_path)
    runner = TradingRunner(
        strategy=_NopStrategy(), executor=ex, snapshot_fn=lambda: [],
    )
    out = tmp_path / "status.json"
    runner.dump_status(out)
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_runner_status_file_arg_auto_dumps_each_tick(tmp_path):
    ex, _ = _build_executor(tmp_path)
    out = tmp_path / "status.json"
    runner = TradingRunner(
        strategy=_NopStrategy(), executor=ex, snapshot_fn=lambda: [],
        status_file=out,
    )
    runner.tick()
    assert out.exists()
    loaded = load_runner_status(out)
    assert loaded["ticks"] == 1


class _OneShotStrategy(Strategy):
    def __init__(self):
        self._meta = StrategyMeta(
            name="oneshot", version="1.0",
            max_position_tao=10.0, max_daily_loss_tao=10.0,
        )
        self._fired = False

    def meta(self):
        return self._meta

    def evaluate(self, _ms):
        if self._fired:
            return []
        self._fired = True
        return [TradeProposal(
            action="stake", target={"netuid": 4},
            amount_tao=1.0, price_tao=100.0, confidence=0.5, reasoning="x",
        )]


def test_runner_dump_reflects_executed_proposal(tmp_path):
    ex, _ = _build_executor(tmp_path)
    out = tmp_path / "status.json"
    runner = TradingRunner(
        strategy=_OneShotStrategy(), executor=ex, snapshot_fn=lambda: [],
        status_file=out,
    )
    runner.tick()
    loaded = load_runner_status(out)
    assert loaded["executed"] == 1
    assert "4" in loaded["open_positions"]
