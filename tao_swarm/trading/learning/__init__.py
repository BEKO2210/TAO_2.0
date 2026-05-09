"""
Learning layer — feedback from realised trades to strategy decisions.

This package adds three independent capabilities on top of the
2A-2L pipeline:

- :class:`PerformanceTracker` reads the SQLite ledger and reports
  per-strategy P&L / win-rate / sharpe over a configurable rolling
  window.
- :class:`EnsembleStrategy` runs multiple base strategies in
  parallel and combines their proposals with a pluggable weight
  function. Default weights come from the tracker's recent-P&L
  signal so the strategy that's actually working gets more
  capital allocated to it.
- :class:`ConfidenceCalibrator` buckets historical proposals by
  emitted ``confidence`` and reports the realised win-rate per
  bucket — so an over-confident strategy gets corrected toward
  reality.

Honest caveats baked into the design:

1. **Learning needs data.** Every helper here returns "insufficient
   data" sentinels until enough realised trades have accumulated.
   The defaults err on the side of "no opinion" rather than acting
   on noise.

2. **No bypass of the safety architecture.** The learning layer
   produces *proposals*; the same Executor / KillSwitch /
   PositionCap / DailyLossLimit gate them. Learning never gets
   to override risk guardrails.

3. **Out-of-sample first.** Anything that suggests parameter
   changes (e.g. the future tuner module) MUST validate on
   walk-forward windows before being used in production.
"""

from __future__ import annotations

from tao_swarm.trading.learning.calibration import (
    CalibrationBucket,
    ConfidenceCalibrator,
)
from tao_swarm.trading.learning.ensemble import (
    EnsembleStrategy,
    inverse_loss_weights,
    uniform_weights,
)
from tao_swarm.trading.learning.tracker import (
    PerformanceTracker,
    StrategyPerformance,
)

__all__ = [
    "CalibrationBucket",
    "ConfidenceCalibrator",
    "EnsembleStrategy",
    "PerformanceTracker",
    "StrategyPerformance",
    "inverse_loss_weights",
    "uniform_weights",
]
