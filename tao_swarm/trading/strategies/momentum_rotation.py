"""
Momentum-rotation strategy: re-stake into subnets whose ``tao_in``
pool depth rose sharply, unstake from subnets whose pool fell
sharply.

Hypothesis: short-term ``tao_in`` flow is a noisy proxy for
operator confidence in a subnet. Sustained inflow → people are
willing to lock more TAO → emissions / fee streams worth chasing.
Sustained outflow → confidence is leaving → exposure should
decrease. The strategy is intentionally simple so we can backtest
it deterministically and lock in its risk surface.

Inputs

The strategy expects a ``market_state`` dict shaped like::

    {
      "subnets": [
        {"netuid": 1, "tao_in": 28580.0, "name": "Apex"},
        {"netuid": 4, "tao_in": 133782.0, "name": "Targon"},
        ...
      ],
      "history": {
        # Per-netuid time series of recent (timestamp, tao_in) pairs.
        # The strategy only needs the immediately-previous value to
        # compute momentum; longer windows are kept in case future
        # variants want them.
        1: [(t-3600, 28000.0), (t-1800, 28300.0), (t, 28580.0)],
        4: ...,
      },
    }

Outputs

A list of :class:`TradeProposal` with action ``"stake"`` /
``"unstake"`` on netuid targets. The strategy never proposes
anything bigger than ``self._slot_size_tao`` and never proposes
both directions for the same netuid in the same evaluation.
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


class MomentumRotationStrategy(Strategy):
    """Stake into subnets with positive ``tao_in`` momentum, unstake
    from subnets with negative momentum.

    Args:
        threshold_pct: Required percent change in ``tao_in`` over the
            last window before the strategy reacts. Positive number;
            +threshold = stake, -threshold = unstake. ``0.05`` =
            ``±5%``. Smaller = more trades + more noise; larger =
            fewer trades + less responsiveness.
        slot_size_tao: TAO to stake / unstake per signalled subnet.
            Per-call cap. The executor's ``PositionCap`` re-checks
            this against the operator's overall caps.
        max_daily_loss_tao: Declared as part of the strategy's
            risk surface. The executor's ``DailyLossLimit`` enforces
            it across all strategies; declaring it here lets the
            orchestrator refuse to wire up the strategy if the
            global limit is smaller.
        watchlist: Optional list of netuids the strategy is allowed
            to trade. ``None`` = all subnets present in
            ``market_state``. Tightening the watchlist is the main
            way an operator scopes the strategy to subnets they
            understand.
        max_position_tao: Hard ceiling per single proposal. Defaults
            to ``slot_size_tao``; raise only when intentionally
            allowing larger jumps.
    """

    AGENT_NAME = "momentum_rotation"
    AGENT_VERSION = "1.0.0"

    def __init__(
        self,
        *,
        threshold_pct: float = 0.05,
        slot_size_tao: float = 1.0,
        max_daily_loss_tao: float = 5.0,
        watchlist: list[int] | None = None,
        max_position_tao: float | None = None,
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

    # ------------------------------------------------------------------
    # Strategy contract
    # ------------------------------------------------------------------

    def meta(self) -> StrategyMeta:
        return StrategyMeta(
            name=self.AGENT_NAME,
            version=self.AGENT_VERSION,
            max_position_tao=self._max_position,
            max_daily_loss_tao=self._max_loss,
            description=(
                "Stake into / out of subnets based on short-term "
                f"tao_in momentum (±{self._threshold * 100:.1f}% threshold)."
            ),
            actions_used=("stake", "unstake"),
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
            action: str | None = None
            if momentum >= self._threshold:
                action = "stake"
            elif momentum <= -self._threshold:
                action = "unstake"
            else:
                continue

            confidence = min(1.0, abs(momentum) / (self._threshold * 4))
            reasoning = (
                f"netuid {netuid} tao_in momentum "
                f"{momentum * 100:+.2f}% over last window "
                f"({previous:,.0f} → {current:,.0f}); threshold "
                f"±{self._threshold * 100:.1f}%"
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
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _previous_tao_in(
        history: dict[Any, list[tuple[float, float]]],
        netuid: int,
    ) -> float | None:
        """Pick the ``tao_in`` value immediately before the current
        sample. Tolerates int / str keys."""
        series = history.get(netuid) or history.get(str(netuid))
        if not series or len(series) < 2:
            return None
        # The current sample is the last tuple; the previous is index -2.
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
        if f != f:  # NaN check
            return None
        return f
