"""
Trade Executor — routes a :class:`~tao_swarm.trading.strategy_base.
TradeProposal` through the guards and into either the paper ledger
(default) or the live signing path (PR 2E, raises here for now).

The executor is the single point in the system that decides
"this proposal becomes a real action". Everything else feeds
into it. No agent, no plug-in, and no strategy may bypass it.

Decision matrix:

    mode != AUTO_TRADING             → paper-only, no matter what
    kill switch tripped              → refuse
    mode == AUTO_TRADING and ``paper=True``   → paper ledger record
    mode == AUTO_TRADING and ``paper=False``  → guard chain:
        position cap check → daily-loss check → live signing path

If any guard refuses, the executor returns an :class:`ExecResult`
with ``status="refused"`` and a reason. It never raises on
business-logic refusal; raising is reserved for genuine errors
(database write failure, malformed proposal, etc.).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tao_swarm.trading.modes import WalletMode
from tao_swarm.trading.strategy_base import TradeProposal

if TYPE_CHECKING:
    from tao_swarm.trading.guards import (
        DailyLossLimit,
        KillSwitch,
        PositionCap,
    )
    from tao_swarm.trading.ledger import PaperLedger

logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    """The outcome of a single ``Executor.execute()`` call."""

    status: str           # "executed" / "refused" / "error"
    paper: bool           # True if this was a paper trade (no real TX)
    reason: str = ""      # human-readable, audited
    trade_id: str | None = None
    proposal: TradeProposal | None = None
    timestamp: float = field(default_factory=time.time)

    def is_ok(self) -> bool:
        return self.status == "executed"


class Executor:
    """Composes the guards + ledger to decide and record trade actions."""

    def __init__(
        self,
        *,
        mode: WalletMode,
        kill_switch: KillSwitch,
        position_cap: PositionCap,
        daily_loss_limit: DailyLossLimit,
        ledger: PaperLedger,
    ) -> None:
        self._mode = mode
        self._kill = kill_switch
        self._cap = position_cap
        self._loss = daily_loss_limit
        self._ledger = ledger

    @property
    def mode(self) -> WalletMode:
        return self._mode

    # ---- public ----

    def execute(
        self,
        proposal: TradeProposal,
        *,
        paper: bool = True,
        current_total_tao: float = 0.0,
        strategy_name: str = "unknown",
    ) -> ExecResult:
        """Run a proposal through the guards and record the outcome.

        Args:
            proposal: What the strategy wants to do.
            paper: If True (default), only the paper ledger is touched.
                Setting ``paper=False`` requests a live signed
                transaction. Live execution requires
                ``mode == AUTO_TRADING`` AND all guards pass; this
                PR's executor raises ``NotImplementedError`` on the
                actual signing path because that lands in PR 2E.
            current_total_tao: Caller-supplied current open exposure
                across all positions, used for the position-cap
                check. The executor doesn't compute this itself
                because the strategy / orchestrator already tracks
                it.
            strategy_name: Recorded in the ledger for auditing.

        Returns:
            ExecResult describing what happened. Never raises on a
            business-rule refusal — those return ``status="refused"``.
        """
        if not isinstance(proposal, TradeProposal):
            return ExecResult(
                status="error", paper=paper,
                reason=f"not a TradeProposal: {type(proposal).__name__}",
                proposal=None,
            )

        # 1. Kill-switch is the first gate. Always.
        ks = self._kill.state()
        if ks.tripped:
            return self._refuse(
                proposal, paper,
                f"kill switch tripped ({ks.source}): {ks.reason}",
            )

        # 2. Mode gating. Anything below AUTO_TRADING forces paper.
        if not self._mode.can_send_value:
            if not paper:
                return self._refuse(
                    proposal, paper=True,
                    reason=(
                        f"live execution requested but wallet mode is "
                        f"{self._mode.value!r} — paper is the only "
                        "available path; no value can move from this "
                        "swarm in the current mode."
                    ),
                )
            return self._record_paper(proposal, strategy_name)

        # 3. Position-size cap.
        ok, why = self._cap.can_open(proposal.amount_tao, current_total_tao)
        if not ok:
            return self._refuse(proposal, paper, f"position cap: {why}")

        # 4. Daily-loss limit.
        if self._loss.is_breached():
            return self._refuse(
                proposal, paper,
                f"daily loss limit hit: {self._loss.daily_pnl():.4f} TAO "
                f"(limit -{self._loss.limit_tao} TAO); trading paused for "
                "the rest of the UTC day",
            )

        # 5. All guards passed. Branch paper vs live.
        if paper:
            return self._record_paper(proposal, strategy_name)
        return self._live_execute(proposal, strategy_name)

    # ---- internals ----

    def _refuse(
        self, proposal: TradeProposal, paper: bool, reason: str,
    ) -> ExecResult:
        logger.info("Executor refuse: %s", reason)
        return ExecResult(
            status="refused", paper=paper, reason=reason, proposal=proposal,
        )

    def _record_paper(
        self, proposal: TradeProposal, strategy_name: str,
    ) -> ExecResult:
        """Write a paper-trade entry. realised_pnl_tao is 0 here —
        strategies that compute MTM P&L on close fill it in via a
        separate ``record_trade`` call against the ledger."""
        from tao_swarm.trading.ledger import TradeRecord

        record = TradeRecord(
            strategy=strategy_name,
            action=proposal.action,
            target=dict(proposal.target),
            amount_tao=proposal.amount_tao,
            price_tao=proposal.price_tao,
            realised_pnl_tao=0.0,
            paper=True,
            note=proposal.reasoning,
            tx_hash=None,
        )
        self._ledger.record_trade(record)
        return ExecResult(
            status="executed", paper=True, reason="paper-trade recorded",
            trade_id=record.id, proposal=proposal,
        )

    def _live_execute(
        self, proposal: TradeProposal, strategy_name: str,
    ) -> ExecResult:
        """Sign and broadcast. Lands in PR 2E.

        Until then this is a hard wall. Calling it without the
        keystore wired up is exactly the kind of footgun that
        would put real money at risk; refusing here is the safe
        default."""
        raise NotImplementedError(
            "live signing path not yet wired up — keystore (PR 2C) and "
            "live executor (PR 2E) must land first; in the meantime use "
            "execute(..., paper=True)"
        )
