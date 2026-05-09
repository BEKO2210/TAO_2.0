"""
EnsembleStrategy — combine multiple base strategies with adaptive
weights derived from recent realised performance.

Why
===

A single strategy is brittle: momentum thrives in trending
regimes and bleeds in choppy ones; mean-reversion is the inverse.
An ensemble that runs both and lets the recently-better-performing
one drive more capital is the standard professional answer. The
weights come from an injectable callable so operators can choose
inverse-loss, win-rate, sharpe-ratio, or anything else they
believe in.

Design
======

- :class:`EnsembleStrategy` is itself a :class:`Strategy`. It
  composes a list of base strategies; on each ``evaluate`` it
  calls every base, scales each base's amounts by a per-strategy
  weight, and merges the results.
- Weight functions are pure — they take the list of strategy
  names plus a :class:`PerformanceTracker` and return a
  ``dict[str, float]`` of normalised weights summing to 1.0.
  Out-of-the-box: :func:`uniform_weights`, :func:`inverse_loss_weights`.
- Weights below a configurable ``min_weight`` floor zero out a
  strategy entirely for that tick (avoiding tiny dust trades).
- The ensemble's ``meta()`` uses the OR of base ``actions_used``
  and the SUM of base ``max_position_tao`` — the operator's
  ``PositionCap`` is still the binding constraint.

Honest caveats
==============

1. **Not bypassing the executor.** Ensemble proposals still go
   through the same Executor + guards. Weights only scale
   amounts; they don't change actions or skip risk checks.
2. **No look-ahead.** The weight function reads tracker stats
   computed BEFORE the current tick — never the trade about to
   be placed.
3. **Insufficient-data fallback.** If the tracker reports
   ``insufficient_data=True`` for a strategy, the default
   weight function falls back to uniform — better to give every
   strategy an equal chance than to let one outlier early win
   skew everything.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Callable

from tao_swarm.trading.strategy_base import (
    Strategy,
    StrategyMeta,
    TradeProposal,
)

logger = logging.getLogger(__name__)


WeightFn = Callable[[list[str], Any], dict[str, float]]


# ---------------------------------------------------------------------------
# Built-in weight functions
# ---------------------------------------------------------------------------

def uniform_weights(
    strategy_names: list[str],
    tracker: Any | None = None,
) -> dict[str, float]:
    """Equal weight across all base strategies.

    Tracker arg is ignored; included so the signature matches
    :data:`WeightFn`.
    """
    n = len(strategy_names)
    if n == 0:
        return {}
    return {name: 1.0 / n for name in strategy_names}


def inverse_loss_weights(
    strategy_names: list[str],
    tracker: Any,
    *,
    window_days: float = 7.0,
    floor: float = 0.05,
) -> dict[str, float]:
    """Weight by recent realised P&L. Losers get throttled, but
    never to zero — every strategy keeps at least ``floor`` of
    the budget so we don't lock ourselves out of a regime change.

    Algorithm
    ---------

    1. For each strategy, fetch its
       :class:`StrategyPerformance` over the last ``window_days``.
    2. Strategies with insufficient data (or a window-old
       last_trade) get the uniform baseline — we won't penalise a
       strategy that hasn't traded.
    3. For the rest, transform realised_pnl_tao to a non-negative
       score: ``score = max(0, pnl) + floor * abs(min_pnl)`` so
       the worst loser still gets a small slice.
    4. Normalise to sum 1.0.
    """
    if not strategy_names:
        return {}
    if tracker is None:
        return uniform_weights(strategy_names)

    raw_scores: dict[str, float] = {}
    insufficient: set[str] = set()
    for name in strategy_names:
        try:
            perf = tracker.stats_for(name, window_days=window_days)
        except Exception as exc:
            logger.warning("tracker.stats_for(%s) failed: %s", name, exc)
            insufficient.add(name)
            continue
        if perf.insufficient_data:
            insufficient.add(name)
            continue
        raw_scores[name] = float(perf.realised_pnl_tao)

    # Strategies with insufficient data get the uniform baseline.
    if insufficient and not raw_scores:
        return uniform_weights(strategy_names)

    # Shift so the worst strategy is at exactly ``floor`` * max.
    if raw_scores:
        min_score = min(raw_scores.values())
        max_score = max(raw_scores.values())
        # If everyone is identical (zero pnl), fall back to uniform.
        if max_score == min_score:
            scored_uniform = uniform_weights(list(raw_scores))
            base_weight_for_insuff = 1.0 / len(strategy_names) if strategy_names else 0.0
        else:
            shifted = {
                k: (v - min_score) + floor * (max_score - min_score)
                for k, v in raw_scores.items()
            }
            total_shifted = sum(shifted.values())
            scored_uniform = {k: v / total_shifted for k, v in shifted.items()}
            base_weight_for_insuff = 1.0 / len(strategy_names)
    else:
        scored_uniform = {}
        base_weight_for_insuff = 1.0 / len(strategy_names)

    # Combine: tracked strategies use their score-based weight,
    # insufficient-data strategies get the uniform baseline. Then
    # re-normalise so the whole vector sums to 1.0.
    raw: dict[str, float] = {}
    for name in strategy_names:
        if name in scored_uniform:
            raw[name] = scored_uniform[name]
        else:
            raw[name] = base_weight_for_insuff
    total = sum(raw.values())
    if total <= 0:
        return uniform_weights(strategy_names)
    return {k: v / total for k, v in raw.items()}


# ---------------------------------------------------------------------------
# EnsembleStrategy
# ---------------------------------------------------------------------------

class EnsembleStrategy(Strategy):
    """Composite strategy that runs N base strategies and combines
    their proposals weighted by performance.

    Args:
        bases: Mapping of name → :class:`Strategy` instance.
        weight_fn: Pure function returning per-name weights summing
            to 1.0. Defaults to :func:`uniform_weights`.
        tracker: :class:`PerformanceTracker` passed to the weight
            function. Required for non-uniform weighting.
        name: Reported in :class:`StrategyMeta`. Defaults to
            ``"ensemble"``.
        version: Reported in :class:`StrategyMeta`.
        min_weight: Strategies whose weight falls below this floor
            are skipped this tick (avoids dust trades).
        live_trading: Per-strategy opt-in for live execution.
            Defaults to ``False``. If set to ``True``, every base
            strategy must also have ``meta().live_trading=True``
            — the ensemble does NOT escalate trust on its own.
    """

    STRATEGY_NAME = "ensemble"
    AGENT_NAME = "ensemble"
    AGENT_VERSION = "1.0.0"

    def __init__(
        self,
        bases: dict[str, Strategy],
        *,
        weight_fn: WeightFn = uniform_weights,
        tracker: Any | None = None,
        name: str = "ensemble",
        version: str = AGENT_VERSION,
        min_weight: float = 0.01,
        live_trading: bool = False,
    ) -> None:
        if not bases:
            raise ValueError("EnsembleStrategy requires at least one base strategy")
        if min_weight < 0 or min_weight >= 1.0:
            raise ValueError("min_weight must be in [0, 1)")
        if live_trading:
            for nm, s in bases.items():
                if not s.meta().live_trading:
                    raise ValueError(
                        f"ensemble live_trading=True but base strategy {nm!r} "
                        "is paper-only; opt in on every base before enabling "
                        "the ensemble"
                    )
        self._bases = dict(bases)
        self._weight_fn = weight_fn
        self._tracker = tracker
        self._name = str(name)
        self._version = str(version)
        self._min_weight = float(min_weight)
        self._live = bool(live_trading)

    # ---- introspection ----

    @property
    def base_names(self) -> tuple[str, ...]:
        return tuple(self._bases)

    def current_weights(self) -> dict[str, float]:
        """Compute the latest weight vector without running the
        underlying strategies. Useful for the dashboard."""
        return self._weight_fn(list(self._bases), self._tracker)

    # ---- Strategy contract ----

    def meta(self) -> StrategyMeta:
        # Aggregate the base strategies' risk surface conservatively:
        # max_position_tao is the SUM (so the operator's PositionCap
        # gates correctly across the combined book); max_daily_loss
        # is the SUM too (each base contributes its tolerance).
        actions: set[str] = set()
        max_pos = 0.0
        max_loss = 0.0
        for s in self._bases.values():
            m = s.meta()
            actions.update(m.actions_used)
            max_pos += float(m.max_position_tao)
            max_loss += float(m.max_daily_loss_tao)
        return StrategyMeta(
            name=self._name,
            version=self._version,
            max_position_tao=max_pos,
            max_daily_loss_tao=max_loss,
            description=(
                f"Ensemble of {len(self._bases)} base strategies "
                f"({', '.join(sorted(self._bases))}); weights from "
                f"{self._weight_fn.__name__}"
            ),
            actions_used=tuple(sorted(actions)),
            live_trading=self._live,
        )

    def evaluate(self, market_state: dict[str, Any]) -> list[TradeProposal]:
        weights = self._weight_fn(list(self._bases), self._tracker)
        out: list[TradeProposal] = []
        for name, base in self._bases.items():
            w = float(weights.get(name, 0.0))
            if w < self._min_weight:
                continue
            try:
                base_proposals = base.evaluate(market_state)
            except Exception as exc:
                logger.warning(
                    "EnsembleStrategy: base %r raised in evaluate (%s) — "
                    "skipping this tick for that base only",
                    name, exc,
                )
                continue
            for prop in base_proposals:
                scaled = w * float(prop.amount_tao)
                # Skip dust amounts entirely — better to not trade
                # than to spam the cap with tiny orders.
                if scaled <= 0:
                    continue
                tagged = self._tag_reasoning(prop, name, w)
                out.append(replace(
                    tagged,
                    amount_tao=round(scaled, 9),
                ))
        return out

    # ---- internals ----

    @staticmethod
    def _tag_reasoning(prop: TradeProposal, base_name: str, weight: float) -> TradeProposal:
        """Annotate the proposal so the audit trail shows which
        base produced it and at what ensemble weight."""
        prefix = f"[ensemble:{base_name} w={weight:.3f}] "
        return replace(prop, reasoning=prefix + prop.reasoning)
