"""
Integration tests for ``TradingRunner`` + ``TradingCouncil``.

Coverage
========

- Constructing a runner with ``council=None`` keeps the default behaviour
  (no extra status fields populated, status reports council_enabled=False).
- A council that returns ``halt`` causes ``tick()`` to short-circuit:
  no snapshot fetch, no strategy.evaluate, no executor dispatch — and
  the skipped tick is recorded under ``council_skipped_ticks`` and
  ``last_council_decision`` is exposed via :meth:`status`.
- The runner is NOT permanently halted by a council halt — once the
  council clears, the next tick proceeds normally.
- A council that returns ``bullish`` / ``neutral`` / ``bearish`` does
  not block the tick (only ``halt`` short-circuits).
- A council whose ``aggregate()`` raises is treated as advisory: the
  tick proceeds, the exception is recorded as a runner error, but the
  runner does not halt on the council's behalf.
"""

from __future__ import annotations

from typing import Any

from tao_swarm.trading import (
    DailyLossLimit,
    Executor,
    KillSwitch,
    PaperLedger,
    PositionCap,
    Strategy,
    StrategyMeta,
    TradeProposal,
    TradingRunner,
    WalletMode,
)
from tao_swarm.trading.council import CouncilDecision

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _CountingStrategy(Strategy):
    """Counts evaluate() calls; emits one stake proposal per call."""

    def __init__(self) -> None:
        self.calls = 0
        self._meta = StrategyMeta(
            name="counting", version="1.0.0",
            max_position_tao=5.0, max_daily_loss_tao=5.0,
            actions_used=("stake",),
        )

    def meta(self) -> StrategyMeta:
        return self._meta

    def evaluate(self, market_state: dict[str, Any]) -> list[TradeProposal]:
        self.calls += 1
        return [TradeProposal(
            action="stake",
            target={"netuid": 1, "name": "sn1"},
            amount_tao=0.1, price_tao=100.0,
            confidence=0.6, reasoning="t",
        )]


class _ScriptedCouncil:
    """Stand-in for ``TradingCouncil`` whose aggregate() output is
    operator-controlled per call."""

    def __init__(self, decisions: list[CouncilDecision]) -> None:
        self._decisions = list(decisions)
        self._idx = 0
        self.aggregate_calls = 0

    def aggregate(self) -> CouncilDecision:
        self.aggregate_calls += 1
        d = self._decisions[min(self._idx, len(self._decisions) - 1)]
        self._idx += 1
        return d


class _RaisingCouncil:
    def __init__(self) -> None:
        self.aggregate_calls = 0

    def aggregate(self) -> CouncilDecision:
        self.aggregate_calls += 1
        raise RuntimeError("simulated council crash")


def _build_executor(tmp_path):
    ledger = PaperLedger(str(tmp_path / "ledger.db"))
    kill = KillSwitch(flag_path=str(tmp_path / "no_such_kill"))
    cap = PositionCap(max_per_position_tao=5.0, max_total_tao=20.0)
    loss = DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger)
    executor = Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=kill,
        position_cap=cap,
        daily_loss_limit=loss,
        ledger=ledger,
    )
    return executor, ledger


def _snapshot_one_subnet():
    return [{"netuid": 1, "tao_in": 1000.0}]


# ---------------------------------------------------------------------------
# Status defaults
# ---------------------------------------------------------------------------

def test_runner_without_council_reports_council_disabled(tmp_path):
    executor, _ = _build_executor(tmp_path)
    runner = TradingRunner(
        strategy=_CountingStrategy(), executor=executor,
        snapshot_fn=_snapshot_one_subnet,
    )
    s = runner.status()
    assert s.council_enabled is False
    assert s.council_skipped_ticks == 0
    assert s.last_council_decision is None
    assert s.last_council_skip_ts is None


def test_runner_with_council_reports_council_enabled(tmp_path):
    executor, _ = _build_executor(tmp_path)
    council = _ScriptedCouncil([
        CouncilDecision(decision="neutral", score=0.5, reason="seed"),
    ])
    runner = TradingRunner(
        strategy=_CountingStrategy(), executor=executor,
        snapshot_fn=_snapshot_one_subnet,
        council=council,
    )
    s = runner.status()
    assert s.council_enabled is True
    assert s.council_skipped_ticks == 0


# ---------------------------------------------------------------------------
# Halt path
# ---------------------------------------------------------------------------

def test_runner_council_halt_skips_tick(tmp_path):
    executor, ledger = _build_executor(tmp_path)
    strategy = _CountingStrategy()
    council = _ScriptedCouncil([
        CouncilDecision(
            decision="halt", score=None,
            reason="VETO from risk_security_agent: DANGER text detected",
        ),
    ])
    snapshots = []

    def _snap():
        snapshots.append(1)
        return _snapshot_one_subnet()

    runner = TradingRunner(
        strategy=strategy, executor=executor, snapshot_fn=_snap,
        council=council,
    )

    results = runner.tick()
    assert results == []
    # Strategy never asked, snapshot never fetched.
    assert strategy.calls == 0
    assert snapshots == []
    # Status reflects the skip.
    s = runner.status()
    assert s.council_skipped_ticks == 1
    assert s.last_council_decision is not None
    assert s.last_council_decision["decision"] == "halt"
    assert s.last_council_skip_ts is not None
    assert s.ticks == 1  # the skipped tick still counts as a tick
    # Runner is NOT permanently halted — only the tick was skipped.
    assert runner.is_halted is False
    # No trades made it to the ledger.
    assert ledger.total_count() == 0


def test_runner_council_halt_then_clear_resumes(tmp_path):
    """A transient veto skips one tick; once the council clears, the
    next tick proceeds normally without operator reset()."""
    executor, _ = _build_executor(tmp_path)
    strategy = _CountingStrategy()
    council = _ScriptedCouncil([
        CouncilDecision(
            decision="halt", score=None, reason="transient VETO",
        ),
        CouncilDecision(
            decision="bullish", score=0.7, reason="all clear",
        ),
    ])

    runner = TradingRunner(
        strategy=strategy, executor=executor,
        snapshot_fn=_snapshot_one_subnet,
        council=council,
    )

    # First tick: halt → skipped.
    runner.tick()
    assert strategy.calls == 0
    assert runner.status().council_skipped_ticks == 1

    # Second tick: clear → strategy runs.
    runner.tick()
    assert strategy.calls == 1
    s = runner.status()
    assert s.council_skipped_ticks == 1  # unchanged
    assert s.last_council_decision["decision"] == "bullish"
    assert s.proposals == 1


def test_runner_council_bullish_does_not_block(tmp_path):
    executor, _ = _build_executor(tmp_path)
    strategy = _CountingStrategy()
    council = _ScriptedCouncil([
        CouncilDecision(decision="bullish", score=0.8, reason="strong"),
    ])
    runner = TradingRunner(
        strategy=strategy, executor=executor,
        snapshot_fn=_snapshot_one_subnet,
        council=council,
    )
    runner.tick()
    assert strategy.calls == 1
    assert runner.status().council_skipped_ticks == 0


def test_runner_council_neutral_does_not_block(tmp_path):
    executor, _ = _build_executor(tmp_path)
    strategy = _CountingStrategy()
    council = _ScriptedCouncil([
        CouncilDecision(decision="neutral", score=0.5, reason="meh"),
    ])
    runner = TradingRunner(
        strategy=strategy, executor=executor,
        snapshot_fn=_snapshot_one_subnet,
        council=council,
    )
    runner.tick()
    assert strategy.calls == 1
    assert runner.status().council_skipped_ticks == 0


def test_runner_council_bearish_does_not_block(tmp_path):
    """A bearish recommendation is advisory — the strategy + executor
    are the canonical decision-makers. Only an explicit 'halt' (veto)
    short-circuits the tick."""
    executor, _ = _build_executor(tmp_path)
    strategy = _CountingStrategy()
    council = _ScriptedCouncil([
        CouncilDecision(decision="bearish", score=0.2, reason="weak"),
    ])
    runner = TradingRunner(
        strategy=strategy, executor=executor,
        snapshot_fn=_snapshot_one_subnet,
        council=council,
    )
    runner.tick()
    assert strategy.calls == 1
    assert runner.status().council_skipped_ticks == 0


# ---------------------------------------------------------------------------
# Defensive: a crashing council must not break the runner loop.
# ---------------------------------------------------------------------------

def test_runner_council_aggregate_exception_does_not_halt_runner(tmp_path):
    executor, _ = _build_executor(tmp_path)
    strategy = _CountingStrategy()
    council = _RaisingCouncil()
    runner = TradingRunner(
        strategy=strategy, executor=executor,
        snapshot_fn=_snapshot_one_subnet,
        council=council,
    )
    runner.tick()
    # Strategy still ran — the council failure is advisory, not fatal.
    assert strategy.calls == 1
    s = runner.status()
    # Cumulative error counter went up. (``last_error`` is cleared by
    # the same tick's successful executor pass — see TradingRunner.tick
    # — which mirrors how strategy-side errors get cleared. The
    # cumulative counter is the durable signal the operator audits.)
    assert s.errors >= 1
    # But the runner is not halted by a single advisory failure.
    assert runner.is_halted is False
    # Council got asked exactly once before falling through.
    assert council.aggregate_calls == 1


# ---------------------------------------------------------------------------
# Status serialisation round-trip with council fields.
# ---------------------------------------------------------------------------

def test_runner_status_as_dict_round_trips_council_fields(tmp_path):
    import json

    executor, _ = _build_executor(tmp_path)
    council = _ScriptedCouncil([
        CouncilDecision(
            decision="halt", score=None, reason="for the audit trail",
        ),
    ])
    runner = TradingRunner(
        strategy=_CountingStrategy(), executor=executor,
        snapshot_fn=_snapshot_one_subnet,
        council=council,
    )
    runner.tick()
    payload = runner.status().as_dict()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["council_enabled"] is True
    assert decoded["council_skipped_ticks"] == 1
    assert decoded["last_council_decision"]["decision"] == "halt"
    assert decoded["last_council_skip_ts"] is not None
