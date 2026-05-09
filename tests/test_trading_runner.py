"""
Tests for ``TradingRunner`` and ``MarketStateBuilder``.

Coverage
========

MarketStateBuilder:
- Initial empty state.
- Appends per-netuid samples; same netuid grows its series.
- Window cap evicts oldest samples.
- Skips entries with missing netuid / tao_in / non-numeric values.
- Returns a fresh dict each call (mutating the result doesn't leak
  back into the builder).

TradingRunner:
- Constructor validates inputs (tick_interval_s, max_consecutive_errors).
- ``status()`` reports idle when no ticks have run.
- ``tick()`` runs strategy + executor and counts proposals.
- ``tick()`` updates position book on stake/unstake.
- ``tick()`` reports executed/refused/error counters.
- Position-cap arithmetic: a second stake sees current_total updated.
- Snapshot fetch raising → recorded as runner error, no halt yet.
- Strategy.evaluate raising → recorded as error.
- Circuit breaker: max_consecutive_errors reached → halted, refuses
  to tick.
- Clean tick clears the consecutive-error counter (cumulative
  preserved).
- ``reset()`` clears halted state and consecutive counter.
- ``run_forever()`` honours ``max_ticks``.
- ``stop()`` interrupts ``run_forever`` promptly.
- Runner respects executor.execute returning an ExecResult error
  (status='error') and trips the breaker.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from tao_swarm.trading import (
    DailyLossLimit,
    Executor,
    KillSwitch,
    MarketStateBuilder,
    PaperLedger,
    PositionCap,
    Strategy,
    StrategyMeta,
    TradeProposal,
    TradingRunner,
    WalletMode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ScriptedStrategy(Strategy):
    """Returns whatever proposals were queued on construction."""

    def __init__(
        self,
        proposals_per_tick: list[list[TradeProposal]] | None = None,
        *,
        raise_on_tick: int | None = None,
        meta: StrategyMeta | None = None,
    ) -> None:
        self._queue = list(proposals_per_tick or [])
        self._raise_at = raise_on_tick
        self._tick = 0
        self._meta = meta or StrategyMeta(
            name="scripted", version="1.0.0",
            max_position_tao=10.0, max_daily_loss_tao=10.0,
            actions_used=("stake", "unstake"),
        )

    def meta(self) -> StrategyMeta:
        return self._meta

    def evaluate(self, market_state: dict[str, Any]) -> list[TradeProposal]:
        if self._raise_at is not None and self._tick == self._raise_at:
            self._tick += 1
            raise RuntimeError("scripted strategy crash")
        if self._tick < len(self._queue):
            out = self._queue[self._tick]
        else:
            out = []
        self._tick += 1
        return out


def _proposal(action: str = "stake", netuid: int = 1, amount: float = 1.0,
              price: float = 100.0) -> TradeProposal:
    return TradeProposal(
        action=action,
        target={"netuid": netuid, "name": f"sn{netuid}"},
        amount_tao=amount,
        price_tao=price,
        confidence=0.5,
        reasoning="t",
    )


def _build_executor(tmp_path):
    ledger = PaperLedger(str(tmp_path / "ledger.db"))
    kill = KillSwitch(flag_path=str(tmp_path / "no_such_kill"))
    cap = PositionCap(max_per_position_tao=5.0, max_total_tao=20.0)
    loss = DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger)
    return Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=kill,
        position_cap=cap,
        daily_loss_limit=loss,
        ledger=ledger,
    ), ledger


# ---------------------------------------------------------------------------
# MarketStateBuilder
# ---------------------------------------------------------------------------

def test_market_state_builder_rejects_invalid_window():
    with pytest.raises(ValueError):
        MarketStateBuilder(history_window=1)


def test_market_state_builder_appends_samples():
    b = MarketStateBuilder(history_window=4)
    state = b.update([{"netuid": 1, "tao_in": 100.0}], now=10.0)
    assert state["history"][1] == [(10.0, 100.0)]
    state = b.update([{"netuid": 1, "tao_in": 110.0}], now=20.0)
    assert state["history"][1] == [(10.0, 100.0), (20.0, 110.0)]


def test_market_state_builder_windows_old_samples():
    b = MarketStateBuilder(history_window=3)
    for i in range(5):
        b.update([{"netuid": 1, "tao_in": float(100 + i)}], now=float(i))
    state = b.update([{"netuid": 1, "tao_in": 200.0}], now=10.0)
    series = state["history"][1]
    # window=3, last update is the 6th, so we keep the last 3.
    assert len(series) == 3
    assert series[-1] == (10.0, 200.0)


def test_market_state_builder_skips_bad_entries():
    b = MarketStateBuilder()
    state = b.update([
        {"netuid": None, "tao_in": 1.0},
        {"netuid": 1, "tao_in": None},
        {"netuid": 2, "tao_in": "not a number"},
        {"netuid": 3, "tao_in": 7.5},
    ], now=1.0)
    assert list(state["history"].keys()) == [3]


def test_market_state_builder_returns_fresh_dict():
    b = MarketStateBuilder()
    s1 = b.update([{"netuid": 1, "tao_in": 1.0}], now=1.0)
    s1["history"][1].append(("garbage",))  # type: ignore[arg-type]
    s2 = b.update([{"netuid": 1, "tao_in": 2.0}], now=2.0)
    # The mutation in s1 must not have leaked back.
    assert s2["history"][1] == [(1.0, 1.0), (2.0, 2.0)]


# ---------------------------------------------------------------------------
# TradingRunner — constructor + status
# ---------------------------------------------------------------------------

def test_runner_rejects_bad_constructor_args(tmp_path):
    ex, _ = _build_executor(tmp_path)
    s = _ScriptedStrategy()
    with pytest.raises(ValueError):
        TradingRunner(
            strategy=s, executor=ex, snapshot_fn=lambda: [],
            tick_interval_s=0,
        )
    with pytest.raises(ValueError):
        TradingRunner(
            strategy=s, executor=ex, snapshot_fn=lambda: [],
            max_consecutive_errors=0,
        )


def test_runner_status_idle_initially(tmp_path):
    ex, _ = _build_executor(tmp_path)
    runner = TradingRunner(
        strategy=_ScriptedStrategy(),
        executor=ex, snapshot_fn=lambda: [],
    )
    s = runner.status()
    assert s.state == "idle"
    assert s.ticks == 0
    assert s.executed == 0


# ---------------------------------------------------------------------------
# TradingRunner — single-tick behaviour
# ---------------------------------------------------------------------------

def test_runner_executes_proposal_and_updates_book(tmp_path):
    ex, ledger = _build_executor(tmp_path)
    strat = _ScriptedStrategy([
        [_proposal(action="stake", netuid=4, amount=2.0)],
    ])
    runner = TradingRunner(
        strategy=strat, executor=ex, snapshot_fn=lambda: [],
    )
    results = runner.tick()
    assert len(results) == 1
    assert results[0].status == "executed"
    s = runner.status()
    assert s.ticks == 1
    assert s.proposals == 1
    assert s.executed == 1
    assert s.open_positions[4]["size"] == pytest.approx(2.0)
    # Paper trade was recorded.
    assert len(ledger.list_trades(strategy="scripted")) == 1


def test_runner_unstake_reduces_position(tmp_path):
    ex, _ = _build_executor(tmp_path)
    strat = _ScriptedStrategy([
        [_proposal(action="stake", netuid=4, amount=3.0)],
        [_proposal(action="unstake", netuid=4, amount=1.0)],
    ])
    runner = TradingRunner(
        strategy=strat, executor=ex, snapshot_fn=lambda: [],
    )
    runner.tick()
    runner.tick()
    s = runner.status()
    assert s.open_positions[4]["size"] == pytest.approx(2.0)


def test_runner_unstake_to_zero_drops_position(tmp_path):
    ex, _ = _build_executor(tmp_path)
    strat = _ScriptedStrategy([
        [_proposal(action="stake", netuid=4, amount=2.0)],
        [_proposal(action="unstake", netuid=4, amount=2.0)],
    ])
    runner = TradingRunner(
        strategy=strat, executor=ex, snapshot_fn=lambda: [],
    )
    runner.tick()
    runner.tick()
    s = runner.status()
    assert 4 not in s.open_positions


def test_runner_position_cap_refuses_overflow(tmp_path):
    """The runner passes ``current_total_tao`` so the total cap fires
    on the second proposal once the open book fills it up."""
    # Tighter caps so we can hit them with small proposals.
    ledger = PaperLedger(str(tmp_path / "ledger.db"))
    ex = Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=KillSwitch(flag_path=str(tmp_path / "no_kill")),
        position_cap=PositionCap(max_per_position_tao=4.0, max_total_tao=4.0),
        daily_loss_limit=DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger),
        ledger=ledger,
    )
    strat = _ScriptedStrategy([
        [_proposal(action="stake", netuid=1, amount=4.0)],
        # Second proposal: per-position OK (req=1 < 4) but total
        # would be 4 + 1 = 5 > 4 → refuse.
        [_proposal(action="stake", netuid=2, amount=1.0)],
    ])
    runner = TradingRunner(
        strategy=strat, executor=ex, snapshot_fn=lambda: [],
    )
    runner.tick()
    runner.tick()
    s = runner.status()
    assert s.executed == 1
    assert s.refused == 1
    assert s.open_positions[1]["size"] == pytest.approx(4.0)
    assert 2 not in s.open_positions


# ---------------------------------------------------------------------------
# TradingRunner — error paths and circuit breaker
# ---------------------------------------------------------------------------

def test_runner_records_snapshot_failure(tmp_path):
    ex, _ = _build_executor(tmp_path)

    def bad_snapshot():
        raise OSError("collector exploded")

    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=bad_snapshot, max_consecutive_errors=10,
    )
    results = runner.tick()
    assert results == []
    s = runner.status()
    assert s.errors == 1
    assert "collector exploded" in (s.last_error or "")


def test_runner_records_strategy_failure(tmp_path):
    ex, _ = _build_executor(tmp_path)
    strat = _ScriptedStrategy(raise_on_tick=0)
    runner = TradingRunner(
        strategy=strat, executor=ex, snapshot_fn=lambda: [],
        max_consecutive_errors=10,
    )
    runner.tick()
    s = runner.status()
    assert s.errors == 1
    assert "scripted strategy crash" in (s.last_error or "")


def test_runner_circuit_breaker_halts(tmp_path):
    ex, _ = _build_executor(tmp_path)

    def bad_snapshot():
        raise RuntimeError("nope")

    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=bad_snapshot, max_consecutive_errors=2,
    )
    runner.tick()
    runner.tick()
    assert runner.is_halted
    s = runner.status()
    assert s.state == "halted"
    assert "circuit breaker" in (s.halted_reason or "")
    # Further ticks no-op.
    runner.tick()
    assert runner.status().errors == 2  # unchanged, no third error recorded


def test_runner_reset_clears_halt(tmp_path):
    ex, _ = _build_executor(tmp_path)

    def bad_snapshot():
        raise RuntimeError("nope")

    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=bad_snapshot, max_consecutive_errors=1,
    )
    runner.tick()
    assert runner.is_halted
    runner.reset()
    assert not runner.is_halted
    s = runner.status()
    assert s.consecutive_errors == 0
    # Cumulative errors preserved (forensic record).
    assert s.errors == 1


def test_runner_clean_tick_clears_consecutive_counter(tmp_path):
    ex, _ = _build_executor(tmp_path)

    snapshots = [iter([
        OSError("blip"),  # tick 0: snapshot raises
        [],               # tick 1: clean
    ])]

    def maybe_failing_snapshot():
        nxt = next(snapshots[0])
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=maybe_failing_snapshot, max_consecutive_errors=3,
    )
    runner.tick()  # error
    runner.tick()  # clean
    s = runner.status()
    assert s.errors == 1
    assert s.consecutive_errors == 0
    assert s.last_error is None  # cleared by the clean tick


# ---------------------------------------------------------------------------
# run_forever / stop
# ---------------------------------------------------------------------------

def test_run_forever_respects_max_ticks(tmp_path):
    ex, _ = _build_executor(tmp_path)
    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [], tick_interval_s=0.01,
        sleep=lambda _s: None,
    )
    runner.run_forever(max_ticks=3)
    assert runner.status().ticks == 3


def test_stop_interrupts_run_forever(tmp_path):
    ex, _ = _build_executor(tmp_path)
    sleeps: list[float] = []

    def fake_sleep(t: float) -> None:
        sleeps.append(t)
        # After one slice of sleep, signal stop.
        runner.stop()

    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [], tick_interval_s=10.0,
        sleep=fake_sleep,
    )
    start = time.monotonic()
    runner.run_forever(max_ticks=1000)
    elapsed = time.monotonic() - start
    # We should NOT actually have slept 10 seconds; the fake sleep
    # plus stop signal exits within milliseconds.
    assert elapsed < 1.0
    # We tick at least once, then sleep, then stop.
    assert runner.status().ticks >= 1


def test_runner_run_forever_stops_when_halted(tmp_path):
    ex, _ = _build_executor(tmp_path)

    def bad_snapshot():
        raise RuntimeError("blow up")

    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=bad_snapshot, max_consecutive_errors=1,
        tick_interval_s=0.01,
        sleep=lambda _s: None,
    )
    runner.run_forever(max_ticks=100)
    # Halts after the very first error tick — runs are bounded.
    assert runner.is_halted
    assert runner.status().ticks <= 2


# ---------------------------------------------------------------------------
# Runner respects executor "error" status
# ---------------------------------------------------------------------------

def test_runner_treats_executor_error_status_as_runner_error(tmp_path):
    """If the executor returns ``status='error'`` (e.g. malformed
    proposal), the runner counts it toward the consecutive-error
    counter. Three in a row trips the breaker."""
    ex, _ = _build_executor(tmp_path)

    class _ErrorOnExecuteStrategy(Strategy):
        def __init__(self) -> None:
            self.calls = 0
            self._meta = StrategyMeta(
                name="err", version="1.0",
                max_position_tao=10.0, max_daily_loss_tao=10.0,
            )

        def meta(self) -> StrategyMeta:
            return self._meta

        def evaluate(self, _ms):
            self.calls += 1
            return ["not a TradeProposal"]  # type: ignore[list-item]

    runner = TradingRunner(
        strategy=_ErrorOnExecuteStrategy(), executor=ex,
        snapshot_fn=lambda: [], max_consecutive_errors=2,
    )
    runner.tick()
    assert runner.status().errors == 1
    runner.tick()
    assert runner.is_halted


def test_runner_status_serialisable(tmp_path):
    ex, _ = _build_executor(tmp_path)
    runner = TradingRunner(
        strategy=_ScriptedStrategy([
            [_proposal(action="stake", netuid=1)],
        ]),
        executor=ex, snapshot_fn=lambda: [],
    )
    runner.tick()
    import json
    d = runner.status().as_dict()
    json.dumps(d)
    assert d["strategy"] == "scripted"
    assert d["ticks"] == 1
