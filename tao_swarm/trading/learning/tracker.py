"""
PerformanceTracker — rolling per-strategy statistics from the
audit ledger.

The Executor writes every trade — paper or live, executed or
failed — to :class:`tao_swarm.trading.ledger.PaperLedger`. This
module reads that ledger and computes the metrics the learning
layer needs to make routing decisions:

- realised P&L over a configurable window
- win rate (closed trades only)
- pseudo-Sharpe of per-trade P&L
- counts of paper / live / failed attempts
- timestamp of the last realised close (so we can detect "this
  strategy hasn't traded in a week")

Window semantics
================

We support both a time-based window (``window_days``) and a
count-based window (``window_trades``). For learning that needs
"recent behaviour" the time window is usually right; for
calibration that needs "the last N samples no matter how old"
the count window is right. They compose: pass both and the
intersection wins.

Performance is computed only over the strategy's own audit rows
— the tracker doesn't try to re-derive what the chain "really"
did. The ledger row is the source of truth.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyPerformance:
    """Point-in-time performance snapshot for one strategy.

    ``insufficient_data=True`` means the tracker had fewer than
    ``min_trades`` realised closes inside the window; downstream
    code should treat the numerical fields as "no opinion".
    """

    strategy: str
    window_days: float
    window_trades: int
    num_attempts: int
    num_executed: int
    num_failed: int
    num_realised_closes: int
    realised_pnl_tao: float
    win_rate: float
    sharpe: float
    last_trade_ts: float | None
    insufficient_data: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "window_days": self.window_days,
            "window_trades": self.window_trades,
            "num_attempts": self.num_attempts,
            "num_executed": self.num_executed,
            "num_failed": self.num_failed,
            "num_realised_closes": self.num_realised_closes,
            "realised_pnl_tao": self.realised_pnl_tao,
            "win_rate": self.win_rate,
            "sharpe": self.sharpe,
            "last_trade_ts": self.last_trade_ts,
            "insufficient_data": self.insufficient_data,
        }


class PerformanceTracker:
    """Reads :class:`PaperLedger` rows and derives per-strategy KPIs.

    The tracker is read-only; it neither writes to the ledger nor
    holds state between calls. Each call walks the most recent
    rows for the given strategy. For tight loops, cache the
    :class:`StrategyPerformance` you get back.

    Args:
        ledger: Anything that quacks like
            :class:`tao_swarm.trading.ledger.PaperLedger`. Must
            expose ``list_trades(strategy=, limit=)``.
        min_trades: Below this many realised closes the tracker
            sets ``insufficient_data=True``. Default 5 — small
            enough to start producing signal early, large enough
            to be honest about noise.
        clock: Injectable time source for tests.
    """

    DEFAULT_WINDOW_DAYS = 30.0
    DEFAULT_WINDOW_TRADES = 200

    def __init__(
        self,
        ledger: Any,
        *,
        min_trades: int = 5,
        clock: Any = time.time,
    ) -> None:
        if min_trades < 1:
            raise ValueError("min_trades must be >= 1")
        self._ledger = ledger
        self._min = int(min_trades)
        self._clock = clock

    # ---- public ----

    def stats_for(
        self,
        strategy: str,
        *,
        window_days: float = DEFAULT_WINDOW_DAYS,
        window_trades: int = DEFAULT_WINDOW_TRADES,
    ) -> StrategyPerformance:
        if not strategy:
            raise ValueError("strategy must be a non-empty string")
        if window_days <= 0:
            raise ValueError("window_days must be > 0")
        if window_trades <= 0:
            raise ValueError("window_trades must be > 0")

        now = float(self._clock())
        cutoff = now - (window_days * 86400.0)
        rows = list(self._ledger.list_trades(
            strategy=strategy, limit=window_trades * 4,
        ))
        # Filter to the time window AND truncate to window_trades by
        # most-recent-first.
        windowed = sorted(
            [r for r in rows if r.timestamp >= cutoff],
            key=lambda r: r.timestamp, reverse=True,
        )[:window_trades]

        attempts = len(windowed)
        executed = sum(1 for r in windowed if not r.action.endswith("_failed"))
        failed = sum(1 for r in windowed if r.action.endswith("_failed"))
        closes = [
            r for r in windowed
            if r.action.endswith("_realised") and not r.action.endswith("_failed")
        ]
        pnls = [float(r.realised_pnl_tao) for r in closes]
        total_pnl = sum(pnls)
        wins = sum(1 for p in pnls if p > 0)
        win_rate = (wins / len(pnls)) if pnls else 0.0
        sharpe = self._sharpe(pnls)
        last_ts = max((r.timestamp for r in windowed), default=None)
        insufficient = len(closes) < self._min

        return StrategyPerformance(
            strategy=strategy,
            window_days=float(window_days),
            window_trades=int(window_trades),
            num_attempts=attempts,
            num_executed=executed,
            num_failed=failed,
            num_realised_closes=len(closes),
            realised_pnl_tao=round(total_pnl, 6),
            win_rate=round(win_rate, 4),
            sharpe=round(sharpe, 4),
            last_trade_ts=last_ts,
            insufficient_data=bool(insufficient),
        )

    def all_stats(
        self,
        strategies: list[str] | None = None,
        *,
        window_days: float = DEFAULT_WINDOW_DAYS,
        window_trades: int = DEFAULT_WINDOW_TRADES,
    ) -> dict[str, StrategyPerformance]:
        """Compute stats for ``strategies`` or — if ``None`` — for
        every distinct strategy that appears in the ledger."""
        if strategies is None:
            # Lazy-discover strategies from the ledger. We use a
            # generous limit so newly-quiet strategies still show up.
            seen: set[str] = set()
            for row in self._ledger.list_trades(strategy=None, limit=5000):
                if row.strategy:
                    seen.add(row.strategy)
            strategies = sorted(seen)
        return {
            s: self.stats_for(
                s, window_days=window_days, window_trades=window_trades,
            )
            for s in strategies
        }

    # ---- internals ----

    @staticmethod
    def _sharpe(pnls: list[float]) -> float:
        """Pseudo-Sharpe of the per-trade P&L sequence.

        Not annualised (the tracker doesn't know the trade
        cadence); useful only for relative comparison between
        strategies on the same window. Returns 0 on insufficient
        data or zero variance.
        """
        n = len(pnls)
        if n < 2:
            return 0.0
        mean = sum(pnls) / n
        var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
        if var <= 0:
            return 0.0
        return mean / math.sqrt(var)
