"""
Mean-reversion strategy: counter-trade short-term ``tao_in`` swings.

Hypothesis: when subnet ``tao_in`` rises sharply, the move is more
often noise than persistent flow — operators have rotated capital
and will rotate it back. Symmetrically, sharp drops in ``tao_in``
are usually reversals: the next window is more likely to recover
than to keep falling.

This is the *inverse* of
:class:`tao_swarm.trading.strategies.momentum_rotation.MomentumRotationStrategy`:

- Momentum strategy: positive momentum → ``stake``, negative → ``unstake``.
- Mean-reversion strategy: positive momentum → ``unstake`` (price too high,
  will revert), negative momentum → ``stake`` (oversold, will recover).

Same input shape, same risk-surface contract; the two are useful
together as a pair where each hedges the other's bias.

Inputs
------

The strategy expects a ``market_state`` dict shaped like::

    {
      "subnets": [{"netuid": 1, "tao_in": 28580.0, "name": "Apex"}, ...],
      "history": {1: [(t-3600, 28000.0), (t, 28580.0)], ...},
    }

Outputs
-------

A list of :class:`TradeProposal` with action ``"stake"`` /
``"unstake"`` on netuid targets. Per-call sizing is bounded by
``slot_size_tao``; the executor's :class:`PositionCap` is the final
arbiter.
"""

from __future__ import annotations

import logging
from typing import Any

from tao_swarm.trading.strategy_base import (
    Strategy,
    StrategyMeta,
    TradeProposal,
)

logger = logging.getLogger(__name__)


class MeanReversionStrategy(Strategy):
    """Counter-trade short-term ``tao_in`` swings.

    Args:
        threshold_pct: Required percent change in ``tao_in`` over the
            last window before the strategy reacts. Positive number;
            +threshold = unstake (revert from high), -threshold =
            stake (buy the dip).
        slot_size_tao: TAO to stake / unstake per signalled subnet.
        max_daily_loss_tao: Declared as part of the strategy's
            risk surface.
        watchlist: Optional list of netuids the strategy is allowed
            to trade. ``None`` = all subnets present in
            ``market_state``.
        max_position_tao: Hard ceiling per single proposal. Defaults
            to ``slot_size_tao``.
        live_trading: Per-strategy opt-in for live execution.
            Default ``False`` (paper-only) — the executor's three-
            stage gate also enforces this.
    """

    STRATEGY_NAME = "mean_reversion"
    AGENT_NAME = "mean_reversion"
    AGENT_VERSION = "1.0.0"

    def __init__(
        self,
        *,
        threshold_pct: float = 0.05,
        slot_size_tao: float = 1.0,
        max_daily_loss_tao: float = 5.0,
        watchlist: list[int] | None = None,
        max_position_tao: float | None = None,
        live_trading: bool = False,
    ) -> None:
        if threshold_pct <= 0:
            raise ValueError(f"threshold_pct must be > 0, got {threshold_pct}")
        if slot_size_tao <= 0:
            raise ValueError(f"slot_size_tao must be > 0, got {slot_size_tao}")
        if max_daily_loss_tao <= 0:
            raise ValueError(
                f"max_daily_loss_tao must be > 0, got {max_daily_loss_tao}"
            )
        cap = max_position_tao if max_position_tao is not None else slot_size_tao
        if cap < slot_size_tao:
            raise ValueError(
                f"max_position_tao ({cap}) cannot be smaller than "
                f"slot_size_tao ({slot_size_tao})"
            )
        self._threshold = float(threshold_pct)
        self._slot = float(slot_size_tao)
        self._max_loss = float(max_daily_loss_tao)
        self._watch = (
            None if watchlist is None
            else frozenset(int(n) for n in watchlist)
        )
        self._max_position = float(cap)
        self._live = bool(live_trading)

    # ------------------------------------------------------------------
    # Strategy contract
    # ------------------------------------------------------------------

    def meta(self) -> StrategyMeta:
        return StrategyMeta(
            name=self.STRATEGY_NAME,
            version=self.AGENT_VERSION,
            max_position_tao=self._max_position,
            max_daily_loss_tao=self._max_loss,
            description=(
                "Counter-trade short-term tao_in swings: unstake when "
                f"tao_in rose by ≥{self._threshold * 100:.1f}%, stake "
                f"when it fell by ≥{self._threshold * 100:.1f}%."
            ),
            actions_used=("stake", "unstake"),
            live_trading=self._live,
        )

    def evaluate(self, market_state: dict[str, Any]) -> list[TradeProposal]:
        subnets = market_state.get("subnets") or []
        history = market_state.get("history") or {}

        proposals: list[TradeProposal] = []
        for subnet in subnets:
            netuid = subnet.get("netuid")
            if netuid is None:
                continue
            netuid = int(netuid)
            if self._watch is not None and netuid not in self._watch:
                continue

            current = self._safe_float(subnet.get("tao_in"))
            if current is None or current <= 0:
                continue

            previous = self._previous_tao_in(history, netuid)
            if previous is None or previous <= 0:
                continue

            momentum = (current - previous) / previous
            # Mean-reversion: invert the momentum signal.
            action: str | None = None
            if momentum >= self._threshold:
                action = "unstake"
            elif momentum <= -self._threshold:
                action = "stake"
            else:
                continue

            confidence = min(1.0, abs(momentum) / (self._threshold * 4))
            reasoning = (
                f"netuid {netuid} tao_in moved {momentum * 100:+.2f}% over "
                f"last window ({previous:,.0f} → {current:,.0f}); "
                f"mean-reversion threshold ±{self._threshold * 100:.1f}%"
            )
            proposals.append(TradeProposal(
                action=action,
                target={"netuid": netuid, "name": subnet.get("name", "")},
                amount_tao=self._slot,
                price_tao=current,
                confidence=confidence,
                reasoning=reasoning,
            ))
        return proposals

    # ------------------------------------------------------------------
    # Internals (mirror MomentumRotationStrategy for shared robustness)
    # ------------------------------------------------------------------

    @staticmethod
    def _previous_tao_in(
        history: dict[Any, list[tuple[float, float]]],
        netuid: int,
    ) -> float | None:
        series = history.get(netuid) or history.get(str(netuid))
        if not series or len(series) < 2:
            return None
        try:
            return float(series[-2][1])
        except (TypeError, ValueError, IndexError):
            return None

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            f = float(value)
        except (TypeError, ValueError):
            return None
        if f != f:  # NaN
            return None
        return f
