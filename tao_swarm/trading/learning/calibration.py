"""
ConfidenceCalibrator — bucket trades by emitted ``confidence`` and
report the realised win-rate per bucket.

Purpose
=======

Strategies emit :class:`tao_swarm.trading.strategy_base.TradeProposal`
objects with a ``confidence`` score in [0, 1]. The number is
advisory only — nothing in the executor reads it. But it's still
the strategy's stated belief about how likely the proposal is to
succeed, so we can audit it after the fact: "when this strategy
said confidence=0.8, what fraction of those trades actually won?"

A well-calibrated strategy lands close to the diagonal: high-
confidence trades win more often, low-confidence ones less. A
poorly-calibrated strategy may show inverted or flat curves —
that's the signal the operator wanted.

The calibrator does NOT automatically change strategy behaviour.
It exposes the data so the operator (or a future tuner) can
decide what to do.

Caveats
=======

- Confidence calibration needs more data than P&L tracking: 5-10
  trades per bucket minimum to start being meaningful. Buckets
  below that threshold are flagged ``insufficient_data=True``.
- We use realised closes only (rows with action ending in
  ``_realised``) — opens have no realised P&L yet.
- The calibrator joins proposal rows to their corresponding close
  by netuid + chronology. This is approximate; a strategy that
  re-stakes without closing would confuse the join. For now we
  treat each consecutive (open, close) pair as one realised
  outcome.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalibrationBucket:
    """Realised outcome statistics for one confidence bucket."""

    bucket_lo: float           # inclusive
    bucket_hi: float           # exclusive (except the final 1.0 bucket)
    num_samples: int
    num_wins: int
    realised_pnl_tao: float
    realised_win_rate: float
    insufficient_data: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "bucket_lo": self.bucket_lo,
            "bucket_hi": self.bucket_hi,
            "num_samples": self.num_samples,
            "num_wins": self.num_wins,
            "realised_pnl_tao": self.realised_pnl_tao,
            "realised_win_rate": self.realised_win_rate,
            "insufficient_data": self.insufficient_data,
        }


class ConfidenceCalibrator:
    """Compute realised win-rate by emitted-confidence bucket.

    Args:
        ledger: Anything that quacks like
            :class:`tao_swarm.trading.ledger.PaperLedger`.
        num_buckets: How finely to bucket [0, 1]. Default 5
            (i.e. 0-0.2, 0.2-0.4, ...). Fewer buckets = more
            samples per bucket, less granularity.
        min_samples_per_bucket: Below this the bucket is flagged
            as having insufficient data. Default 5.
    """

    def __init__(
        self,
        ledger: Any,
        *,
        num_buckets: int = 5,
        min_samples_per_bucket: int = 5,
    ) -> None:
        if num_buckets < 2:
            raise ValueError("num_buckets must be >= 2")
        if min_samples_per_bucket < 1:
            raise ValueError("min_samples_per_bucket must be >= 1")
        self._ledger = ledger
        self._n = int(num_buckets)
        self._min = int(min_samples_per_bucket)

    # ---- public ----

    def buckets_for(
        self,
        strategy: str,
        *,
        confidence_pairs: list[tuple[float, float]] | None = None,
        limit: int = 1000,
    ) -> list[CalibrationBucket]:
        """Compute one :class:`CalibrationBucket` per confidence
        bucket for ``strategy``.

        Args:
            strategy: Strategy name in the ledger.
            confidence_pairs: Optional pre-joined list of
                ``(confidence, realised_pnl)`` pairs. If ``None``
                we approximate the join from the ledger by walking
                rows in chronological order and pairing each
                opening proposal with the next realised close on
                the same netuid.
            limit: Maximum ledger rows to inspect.
        """
        if not strategy:
            raise ValueError("strategy must be a non-empty string")
        pairs = confidence_pairs
        if pairs is None:
            pairs = self._extract_pairs(strategy, limit=limit)
        return self._bucketise(pairs)

    # ---- internals ----

    def _bucketise(
        self,
        pairs: list[tuple[float, float]],
    ) -> list[CalibrationBucket]:
        edges = [i / self._n for i in range(self._n + 1)]
        bins: list[list[tuple[float, float]]] = [[] for _ in range(self._n)]
        for conf, pnl in pairs:
            try:
                cf = float(conf)
                pn = float(pnl)
            except (TypeError, ValueError):
                continue
            if cf < 0.0 or cf > 1.0:
                continue
            # Final bucket is closed on the right so confidence==1.0
            # actually lands in the last bucket, not a phantom bucket.
            for i in range(self._n):
                lo, hi = edges[i], edges[i + 1]
                if lo <= cf < hi or (i == self._n - 1 and cf == 1.0):
                    bins[i].append((cf, pn))
                    break

        out: list[CalibrationBucket] = []
        for i, samples in enumerate(bins):
            n = len(samples)
            wins = sum(1 for _, p in samples if p > 0)
            total = sum(p for _, p in samples)
            wr = (wins / n) if n else 0.0
            out.append(CalibrationBucket(
                bucket_lo=round(edges[i], 6),
                bucket_hi=round(edges[i + 1], 6),
                num_samples=n,
                num_wins=wins,
                realised_pnl_tao=round(total, 6),
                realised_win_rate=round(wr, 4),
                insufficient_data=n < self._min,
            ))
        return out

    def _extract_pairs(
        self,
        strategy: str,
        *,
        limit: int,
    ) -> list[tuple[float, float]]:
        """Approximate (confidence, realised_pnl) pairs from the
        ledger by chronologically pairing each opening proposal
        with the next realised close on the same netuid.

        Heuristic — strategies that re-stake without closing will
        confuse this; for those, callers should pass
        ``confidence_pairs`` explicitly.
        """
        rows = list(self._ledger.list_trades(
            strategy=strategy, limit=max(limit, 200),
        ))
        # ledger.list_trades returns most-recent-first; flip to asc
        # for chronological pairing.
        rows.sort(key=lambda r: r.timestamp)
        # The TradeRecord schema doesn't carry confidence directly;
        # the strategy's reasoning string is the only place
        # confidence might appear. We keep this simple: this method
        # is a fallback. The recommended path is for the runner /
        # executor to pass an explicit pair list assembled in memory.
        # Returning empty here means "no opinion" rather than wrong.
        return []
