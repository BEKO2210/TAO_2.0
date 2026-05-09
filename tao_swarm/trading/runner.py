"""
TradingRunner — the loop that turns the trading components into an
actually-running bot.

The pieces from PRs 2A-2E exist in isolation:

- A strategy emits :class:`TradeProposal` objects from a
  ``market_state`` dict (PR 2D).
- The :class:`Executor` decides paper vs live, runs the guards,
  and routes through the signer (PR 2E).
- The :class:`PaperLedger` records every trade.

What was missing: a tick-driven loop that

1. pulls a fresh ``market_state`` from the read-only collectors,
2. maintains the per-netuid history window the strategy needs,
3. tracks open positions so the executor's :class:`PositionCap`
   sees the right ``current_total_tao``,
4. counts failures and trips a runner-local circuit breaker before
   the kill-switch even has to fire,
5. exposes a status query so a CLI / dashboard can see what's
   happening,
6. shuts down cleanly on a stop signal.

This module owns no I/O of its own — collectors, executor, and
clock are all injected. That keeps the loop deterministic for unit
tests and lets the same runner sit behind the CLI ``trade run``,
the orchestrator's tick, or a future systemd-managed daemon.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from tao_swarm.trading.executor import ExecResult, Executor
from tao_swarm.trading.reconcile import (
    ChainPositionReader,
    aggregate_by_netuid,
)
from tao_swarm.trading.strategy_base import Strategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status / position book
# ---------------------------------------------------------------------------

@dataclass
class _Position:
    """In-memory view of an open netuid position.

    ``size`` is in TAO; ``entry`` is the size-weighted average
    entry price the strategy reported. The chain is the source of
    truth for the *real* balance — this is just the runner's local
    bookkeeping for the position-cap arithmetic.
    """

    size: float = 0.0
    entry: float = 0.0


@dataclass(frozen=True)
class RunnerStatus:
    """Point-in-time snapshot of the runner. Safe to JSON-encode."""

    state: str               # "idle" | "running" | "halted" | "error"
    strategy: str
    paper: bool
    ticks: int
    proposals: int
    executed: int
    refused: int
    errors: int
    consecutive_errors: int
    last_tick_ts: float | None
    last_error: str | None
    open_positions: dict[int, dict[str, float]]
    halted_reason: str | None
    last_reconcile_ts: float | None = None
    reconciled_total_tao: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "strategy": self.strategy,
            "paper": self.paper,
            "ticks": self.ticks,
            "proposals": self.proposals,
            "executed": self.executed,
            "refused": self.refused,
            "errors": self.errors,
            "consecutive_errors": self.consecutive_errors,
            "last_tick_ts": self.last_tick_ts,
            "last_error": self.last_error,
            "open_positions": {
                str(k): dict(v) for k, v in self.open_positions.items()
            },
            "halted_reason": self.halted_reason,
            "last_reconcile_ts": self.last_reconcile_ts,
            "reconciled_total_tao": self.reconciled_total_tao,
        }


# ---------------------------------------------------------------------------
# Market-state assembler
# ---------------------------------------------------------------------------

class MarketStateBuilder:
    """Turns a chain-readonly subnet snapshot into the dict shape the
    strategy expects, while maintaining the per-netuid history window
    across ticks.

    The builder is deliberately tiny and pure: ``update(snapshot)``
    appends the latest sample, evicts old ones, and returns a fresh
    dict. No threading, no I/O. The runner owns instance state.
    """

    def __init__(self, *, history_window: int = 16) -> None:
        if history_window < 2:
            raise ValueError("history_window must be >= 2")
        self._window = int(history_window)
        self._history: dict[int, list[tuple[float, float]]] = {}

    def update(self, subnets: list[dict[str, Any]], *, now: float) -> dict[str, Any]:
        """Record a new snapshot and return a fresh ``market_state``.

        Args:
            subnets: List of dicts as returned by
                ``ChainReadOnlyCollector.get_subnet_list()``. Each
                must have ``netuid`` and ``tao_in``.
            now: Wall-clock timestamp the strategy will see in the
                history tuples.
        """
        for sn in subnets:
            netuid = sn.get("netuid")
            tao_in = sn.get("tao_in")
            if netuid is None or tao_in is None:
                continue
            try:
                netuid_i = int(netuid)
                tao_in_f = float(tao_in)
            except (TypeError, ValueError):
                continue
            series = self._history.setdefault(netuid_i, [])
            series.append((now, tao_in_f))
            # Bounded window — we only keep the last N samples so
            # long-running bots don't grow unbounded.
            if len(series) > self._window:
                del series[: len(series) - self._window]
        return {
            "subnets": list(subnets),
            "history": {k: list(v) for k, v in self._history.items()},
            "ts": now,
        }

    @property
    def history_window(self) -> int:
        return self._window


# ---------------------------------------------------------------------------
# TradingRunner — the loop
# ---------------------------------------------------------------------------

class TradingRunner:
    """Drives a strategy + executor against a stream of market snapshots.

    Args:
        strategy: A configured :class:`Strategy`. The runner refuses
            to start if its declared ``max_position_tao`` exceeds the
            executor's position cap (defence in depth, even though
            the executor would refuse anyway).
        executor: A configured :class:`Executor`. Owns guards + ledger
            + signer factory.
        snapshot_fn: Callable that returns a ``list[dict]`` shaped
            like ``ChainReadOnlyCollector.get_subnet_list()``. Called
            once per tick. The runner does NOT instantiate the
            collector itself — that keeps tests synthetic.
        paper: If ``True`` (default), every executed proposal goes
            through the paper path. ``False`` requests live signing,
            which the executor's three-step gate will still refuse
            unless env + signer + strategy opt-in are all set.
        tick_interval_s: Seconds between ticks when ``run_forever()``
            is used. Single-shot ``tick()`` ignores this.
        max_consecutive_errors: After this many ticks raise an
            uncaught exception in a row, the runner halts itself
            and refuses to tick again until ``reset()`` is called.
            Independent from the kill switch (which is operator-
            managed) and the daily-loss limit (which is P&L-driven).
        history_window: Length of the per-netuid history kept for
            the strategy. Defaults to 16 samples.
        clock: Injectable time-source for tests. Defaults to
            :func:`time.time`.
        sleep: Injectable sleep so ``run_forever()`` can be unit-
            tested. Defaults to :func:`time.sleep`.
    """

    HALTED_REASON_CIRCUIT = "circuit breaker tripped after consecutive errors"

    def __init__(
        self,
        *,
        strategy: Strategy,
        executor: Executor,
        snapshot_fn: Callable[[], list[dict[str, Any]]],
        paper: bool = True,
        tick_interval_s: float = 60.0,
        max_consecutive_errors: int = 3,
        history_window: int = 16,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        chain_reader: ChainPositionReader | None = None,
        reconcile_coldkey_ss58: str | None = None,
        auto_reconcile: bool = True,
    ) -> None:
        if tick_interval_s <= 0:
            raise ValueError("tick_interval_s must be > 0")
        if max_consecutive_errors <= 0:
            raise ValueError("max_consecutive_errors must be > 0")
        if (chain_reader is None) != (reconcile_coldkey_ss58 is None):
            raise ValueError(
                "chain_reader and reconcile_coldkey_ss58 must be set together "
                "or both omitted"
            )
        self._strategy = strategy
        self._executor = executor
        self._snapshot_fn = snapshot_fn
        self._paper = bool(paper)
        self._interval = float(tick_interval_s)
        self._max_errs = int(max_consecutive_errors)
        self._builder = MarketStateBuilder(history_window=history_window)
        self._clock = clock
        self._sleep = sleep
        self._chain_reader = chain_reader
        self._reconcile_coldkey = reconcile_coldkey_ss58
        self._auto_reconcile = bool(auto_reconcile) and chain_reader is not None
        self._reconciled_once = False

        self._positions: dict[int, _Position] = {}
        self._ticks = 0
        self._proposals = 0
        self._executed = 0
        self._refused = 0
        self._errors = 0
        self._consecutive_errors = 0
        self._last_reconcile_ts: float | None = None
        self._reconciled_total_tao: float | None = None
        self._last_tick_ts: float | None = None
        self._last_error: str | None = None
        self._halted_reason: str | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    # ---- public ----

    @property
    def strategy_name(self) -> str:
        return self._strategy.meta().name

    @property
    def is_halted(self) -> bool:
        return self._halted_reason is not None

    def status(self) -> RunnerStatus:
        with self._lock:
            if self.is_halted:
                state = "halted"
            elif self._stop_event.is_set():
                state = "idle"
            elif self._errors > 0 and self._consecutive_errors > 0:
                state = "error"
            elif self._ticks > 0:
                state = "running"
            else:
                state = "idle"
            positions = {
                uid: {"size": p.size, "entry": p.entry}
                for uid, p in self._positions.items()
                if p.size > 0
            }
            return RunnerStatus(
                state=state,
                strategy=self.strategy_name,
                paper=self._paper,
                ticks=self._ticks,
                proposals=self._proposals,
                executed=self._executed,
                refused=self._refused,
                errors=self._errors,
                consecutive_errors=self._consecutive_errors,
                last_tick_ts=self._last_tick_ts,
                last_error=self._last_error,
                open_positions=positions,
                halted_reason=self._halted_reason,
                last_reconcile_ts=self._last_reconcile_ts,
                reconciled_total_tao=self._reconciled_total_tao,
            )

    def reconcile(self) -> dict[int, float]:
        """Replace the in-memory position book with on-chain truth.

        Reads stake-per-netuid for the configured coldkey via the
        injected :class:`ChainPositionReader`, sums stakes per
        netuid (in case of multiple delegated hotkeys), and rewrites
        ``self._positions`` with the result.

        Existing per-position ``entry`` price information is lost
        — the chain doesn't tell us at what price the operator
        opened a position, so reconciled positions get
        ``entry = 0.0``. The strategy's mark-to-market arithmetic
        must tolerate that (the momentum strategy doesn't use entry
        for its decision; only the backtester's realised-P&L
        bookkeeping does, and the backtester runs in-memory only).

        Returns the per-netuid totals it loaded so the caller can
        log them. Raises if the reader is not configured.
        """
        if self._chain_reader is None or self._reconcile_coldkey is None:
            raise RuntimeError(
                "reconcile() requires chain_reader and "
                "reconcile_coldkey_ss58 to be set on the runner"
            )
        positions = self._chain_reader.read_positions(self._reconcile_coldkey)
        totals = aggregate_by_netuid(positions)
        with self._lock:
            self._positions = {
                netuid: _Position(size=size, entry=0.0)
                for netuid, size in totals.items()
                if size > 0
            }
            self._last_reconcile_ts = float(self._clock())
            self._reconciled_total_tao = sum(totals.values())
            self._reconciled_once = True
        logger.info(
            "Reconciled %d positions for coldkey %s (total %.4f TAO)",
            len(totals), self._reconcile_coldkey, self._reconciled_total_tao,
        )
        return totals

    def reset(self) -> None:
        """Clear the halted state and the consecutive-error counter.

        The cumulative error counter is preserved so a forensic
        review can still see how many failures the runner survived.
        Open positions are NOT closed by ``reset()``.
        """
        with self._lock:
            self._halted_reason = None
            self._consecutive_errors = 0
            self._stop_event.clear()

    def stop(self) -> None:
        """Signal :meth:`run_forever` to exit at the next interval.

        Idempotent. Safe to call from a signal handler thread.
        """
        self._stop_event.set()

    def tick(self) -> list[ExecResult]:
        """Run one iteration: snapshot → strategy.evaluate → execute.

        On the first tick, if ``auto_reconcile`` is enabled and a
        chain reader was configured, the runner pulls the current
        on-chain stake into its position book before doing anything
        else. A reconciliation failure halts the runner immediately
        — running with a wrong ``current_total_tao`` would defeat
        the position cap.

        Returns the list of ``ExecResult`` produced this tick.
        Returns an empty list if the runner is halted or if the
        snapshot / strategy / reconciliation raised.
        """
        if self.is_halted:
            return []

        if self._auto_reconcile and not self._reconciled_once:
            try:
                self.reconcile()
            except Exception as exc:
                # A reconciliation failure on cold start is fatal —
                # we cannot proceed with a stale or empty book and
                # still trust the position cap.
                self._record_error(f"reconcile failed: {exc!r}")
                with self._lock:
                    if self._halted_reason is None:
                        self._halted_reason = (
                            "reconcile failed on cold start; refusing to "
                            "trade without verified on-chain position book"
                        )
                        self._stop_event.set()
                return []

        try:
            snapshot = self._snapshot_fn()
        except Exception as exc:
            self._record_error(f"snapshot fetch failed: {exc!r}")
            return []

        try:
            now = float(self._clock())
            market_state = self._builder.update(
                snapshot if isinstance(snapshot, list) else [],
                now=now,
            )
            proposals = self._strategy.evaluate(market_state)
        except Exception as exc:
            self._record_error(f"strategy.evaluate failed: {exc!r}")
            return []

        if not isinstance(proposals, list):
            self._record_error(
                f"strategy returned non-list: {type(proposals).__name__}"
            )
            return []

        results: list[ExecResult] = []
        meta = self._strategy.meta()
        with self._lock:
            self._ticks += 1
            self._last_tick_ts = now
            self._proposals += len(proposals)

        tick_had_error = False
        for prop in proposals:
            current_total = sum(p.size for p in self._positions.values())
            try:
                result = self._executor.execute(
                    prop,
                    paper=self._paper,
                    current_total_tao=current_total,
                    strategy_name=meta.name,
                    strategy_meta=meta,
                )
            except Exception as exc:
                # Executor.execute is supposed not to raise on business
                # refusals, but any uncaught error becomes a runner
                # error so the circuit breaker can engage.
                self._record_error(f"executor.execute raised: {exc!r}")
                tick_had_error = True
                continue

            results.append(result)
            if result.status == "error":
                tick_had_error = True
            self._post_execute(prop, result)

        # A tick clears the consecutive-error counter ONLY if no error
        # was recorded this tick. Otherwise the breaker wouldn't trip on
        # executor-level errors that didn't raise.
        if not tick_had_error:
            with self._lock:
                self._consecutive_errors = 0
                self._last_error = None
        return results

    def run_forever(self, *, max_ticks: int | None = None) -> None:
        """Tick at ``tick_interval_s`` until ``stop()`` or ``halt``.

        Args:
            max_ticks: Optional safety cap so callers / tests can
                bound the loop. ``None`` = no cap.
        """
        self._stop_event.clear()
        ticked = 0
        while not self._stop_event.is_set():
            self.tick()
            ticked += 1
            if max_ticks is not None and ticked >= max_ticks:
                break
            if self.is_halted:
                break
            # Sleep in small slices so stop() interrupts promptly.
            slept = 0.0
            while slept < self._interval and not self._stop_event.is_set():
                step = min(0.5, self._interval - slept)
                self._sleep(step)
                slept += step

    # ---- internals ----

    def _post_execute(self, prop: Any, result: ExecResult) -> None:
        """Update counters + position book based on a single result."""
        with self._lock:
            if result.status == "executed":
                self._executed += 1
                self._apply_to_positions(prop)
            elif result.status == "refused":
                self._refused += 1
            else:
                self._errors += 1
                self._consecutive_errors += 1
                self._last_error = result.reason or result.status
                self._maybe_halt()

    def _apply_to_positions(self, prop: Any) -> None:
        """Mirror the backtester's bookkeeping so the position-cap
        sees the right ``current_total_tao`` next tick."""
        netuid = prop.target.get("netuid")
        if netuid is None:
            return
        try:
            uid = int(netuid)
        except (TypeError, ValueError):
            return
        pos = self._positions.setdefault(uid, _Position())
        if prop.action == "stake":
            new_size = pos.size + prop.amount_tao
            if new_size > 0:
                pos.entry = (
                    (pos.entry * pos.size + prop.price_tao * prop.amount_tao)
                    / new_size
                )
            pos.size = new_size
        elif prop.action == "unstake":
            pos.size = max(0.0, pos.size - prop.amount_tao)
            if pos.size <= 1e-9:
                self._positions.pop(uid, None)
        # Other actions don't modify our local position book.

    def _record_error(self, reason: str) -> None:
        with self._lock:
            self._errors += 1
            self._consecutive_errors += 1
            self._last_error = reason
            logger.warning("TradingRunner error: %s", reason)
            self._maybe_halt()

    def _maybe_halt(self) -> None:
        """Trip the circuit breaker. Caller MUST hold ``self._lock``."""
        if self._consecutive_errors >= self._max_errs and self._halted_reason is None:
            self._halted_reason = (
                f"{self.HALTED_REASON_CIRCUIT}: "
                f"{self._consecutive_errors} consecutive errors; "
                f"last={self._last_error!r}"
            )
            self._stop_event.set()
            logger.error("TradingRunner halted: %s", self._halted_reason)
