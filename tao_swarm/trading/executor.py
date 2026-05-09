"""
Trade Executor — routes a :class:`~tao_swarm.trading.strategy_base.
TradeProposal` through the guards and into either the paper ledger
(default) or the live signing path (PR 2E).

The executor is the single point in the system that decides
"this proposal becomes a real action". Everything else feeds
into it. No agent, no plug-in, and no strategy may bypass it.

Decision matrix:

    mode != AUTO_TRADING             → paper-only, no matter what
    kill switch tripped              → refuse
    mode == AUTO_TRADING and ``paper=True``   → paper ledger record
    mode == AUTO_TRADING and ``paper=False``  → guard chain:
        position cap check → daily-loss check → live signing path

The live path itself runs a SECOND, separate three-step gate (env
var, signer factory, strategy opt-in) inside
:func:`tao_swarm.trading.signer.authorise_live_trade`. Both the
mode/cap/kill-switch chain AND the live-trade gate must pass before
a real extrinsic is broadcast.

If any guard refuses, the executor returns an :class:`ExecResult`
with ``status="refused"`` and a reason. It never raises on
business-logic refusal; raising is reserved for genuine errors
(database write failure, malformed proposal, etc.).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from tao_swarm.trading.modes import WalletMode
from tao_swarm.trading.strategy_base import StrategyMeta, TradeProposal

if TYPE_CHECKING:
    from tao_swarm.trading.guards import (
        DailyLossLimit,
        KillSwitch,
        PositionCap,
    )
    from tao_swarm.trading.ledger import PaperLedger
    from tao_swarm.trading.signer import BittensorSigner

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
        signer_factory: Callable[[], BittensorSigner] | None = None,
    ) -> None:
        self._mode = mode
        self._kill = kill_switch
        self._cap = position_cap
        self._loss = daily_loss_limit
        self._ledger = ledger
        self._signer_factory = signer_factory

    @property
    def mode(self) -> WalletMode:
        return self._mode

    @property
    def has_signer(self) -> bool:
        """True if a signer factory is wired up. Does NOT mean live
        trading is authorised — the env var and per-strategy opt-in
        still have to be in place."""
        return self._signer_factory is not None

    # ---- public ----

    def execute(
        self,
        proposal: TradeProposal,
        *,
        paper: bool = True,
        current_total_tao: float = 0.0,
        strategy_name: str = "unknown",
        strategy_meta: StrategyMeta | None = None,
        target_hotkey_ss58: str | None = None,
    ) -> ExecResult:
        """Run a proposal through the guards and record the outcome.

        Args:
            proposal: What the strategy wants to do.
            paper: If True (default), only the paper ledger is touched.
                Setting ``paper=False`` requests a live signed
                transaction. Live execution requires
                ``mode == AUTO_TRADING`` AND all guards pass AND the
                three-step live-trade gate (env / signer / strategy
                opt-in) passes inside ``_live_execute``.
            current_total_tao: Caller-supplied current open exposure
                across all positions, used for the position-cap
                check. The executor doesn't compute this itself
                because the strategy / orchestrator already tracks
                it.
            strategy_name: Recorded in the ledger for auditing.
            strategy_meta: Required for ``paper=False``; the
                live-trade gate refuses unless
                ``strategy_meta.live_trading is True``.
            target_hotkey_ss58: Optional override for the hotkey /
                destination ss58 forwarded to the signer. If
                ``None`` the value is taken from the proposal target.

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
        return self._live_execute(
            proposal, strategy_name,
            strategy_meta=strategy_meta,
            target_hotkey_ss58=target_hotkey_ss58,
        )

    # ---- internals ----

    def _refuse(
        self, proposal: TradeProposal, paper: bool, reason: str,
    ) -> ExecResult:
        logger.info("Executor refuse: %s", reason)
        return ExecResult(
            status="refused", paper=paper, reason=reason, proposal=proposal,
        )

    @staticmethod
    def _effective_strategy(proposal: TradeProposal, strategy_name: str) -> str:
        """Resolve the strategy name to write into the ledger row.

        When :class:`tao_swarm.trading.learning.EnsembleStrategy` emits
        a proposal it stamps ``_base_strategy`` into ``target``. The
        executor uses that as the ledger's ``strategy`` column so per-
        strategy panels report real per-base performance, while the
        full ``[ensemble:<base> w=…]`` provenance stays in the note.
        """
        base = proposal.target.get("_base_strategy") if isinstance(proposal.target, dict) else None
        if isinstance(base, str) and base:
            return base
        return strategy_name

    @staticmethod
    def _scrub_target(proposal: TradeProposal) -> dict:
        """Strip the ensemble-internal ``_*`` keys before persisting.

        The ledger row preserves business fields (netuid, hotkey, ...)
        but not the bookkeeping fields the EnsembleStrategy uses to
        signal the executor. The originating provenance lives in the
        ``note`` column already.
        """
        if not isinstance(proposal.target, dict):
            return {}
        return {
            k: v for k, v in proposal.target.items()
            if not (isinstance(k, str) and k.startswith("_"))
        }

    def _record_paper(
        self, proposal: TradeProposal, strategy_name: str,
    ) -> ExecResult:
        """Write a paper-trade entry. realised_pnl_tao is 0 here —
        strategies that compute MTM P&L on close fill it in via a
        separate ``record_trade`` call against the ledger."""
        from tao_swarm.trading.ledger import TradeRecord

        record = TradeRecord(
            strategy=self._effective_strategy(proposal, strategy_name),
            action=proposal.action,
            target=self._scrub_target(proposal),
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
        self,
        proposal: TradeProposal,
        strategy_name: str,
        *,
        strategy_meta: StrategyMeta | None,
        target_hotkey_ss58: str | None,
    ) -> ExecResult:
        """Sign and broadcast through the configured signer.

        Runs the second-level three-step gate (env / signer / strategy
        opt-in) before instantiating the signer. Records the result —
        success or failure — in the ledger as a non-paper trade so the
        audit trail is complete regardless of outcome.
        """
        from tao_swarm.trading.ledger import TradeRecord
        from tao_swarm.trading.signer import (
            BroadcastError,
            LiveSignerError,
            authorise_live_trade,
        )

        ok, reason = authorise_live_trade(
            strategy_meta=strategy_meta,
            signer_factory=self._signer_factory,
        )
        if not ok:
            return self._refuse(proposal, paper=False, reason=reason)

        # signer_factory is non-None here because authorise_live_trade
        # would have refused otherwise. Narrow the type for mypy.
        assert self._signer_factory is not None
        try:
            signer = self._signer_factory()
        except Exception as exc:
            return ExecResult(
                status="error", paper=False, proposal=proposal,
                reason=f"signer construction failed: {exc}",
            )

        try:
            with signer:
                receipt = signer.submit(
                    proposal,
                    target_hotkey_ss58=target_hotkey_ss58,
                )
        except LiveSignerError as exc:
            self._record_failed_live(proposal, strategy_name, str(exc))
            return ExecResult(
                status="refused" if isinstance(exc, BroadcastError) else "error",
                paper=False, proposal=proposal,
                reason=f"live signer error: {exc}",
            )
        except Exception as exc:
            self._record_failed_live(proposal, strategy_name, repr(exc))
            return ExecResult(
                status="error", paper=False, proposal=proposal,
                reason=f"unexpected signer error: {exc!r}",
            )

        verify_suffix = ""
        # If verification ran AND failed, append a clear audit suffix to
        # the action and the note. The broadcast itself succeeded —
        # we're only flagging that what we observed on-chain doesn't
        # match what the proposal expected.
        action = proposal.action
        if receipt.verified is False:
            action = f"{proposal.action}_verification_failed"
            verify_suffix = (
                f" | VERIFY-MISMATCH: {receipt.verify_message}"
            )
        elif receipt.verified is True and receipt.verify_message:
            verify_suffix = f" | verified: {receipt.verify_message}"

        record = TradeRecord(
            strategy=self._effective_strategy(proposal, strategy_name),
            action=action,
            target=self._scrub_target(proposal),
            amount_tao=proposal.amount_tao,
            price_tao=proposal.price_tao,
            realised_pnl_tao=0.0,
            paper=False,
            note=(
                f"{proposal.reasoning} | live: {receipt.message}{verify_suffix}"
                if proposal.reasoning
                else f"live: {receipt.message}{verify_suffix}"
            ),
            tx_hash=receipt.tx_hash,
        )
        self._ledger.record_trade(record)
        return ExecResult(
            status="executed", paper=False,
            reason=receipt.message,
            trade_id=record.id, proposal=proposal,
        )

    def _record_failed_live(
        self, proposal: TradeProposal, strategy_name: str, reason: str,
    ) -> None:
        """Persist a failed live attempt so the audit trail is intact.

        The ledger gets a non-paper row with ``tx_hash=None`` and the
        failure reason in the ``note``. Without this, a refused or
        errored live attempt would leave no on-disk evidence — bad
        for both forensic review and daily-loss accounting.
        """
        from tao_swarm.trading.ledger import TradeRecord

        try:
            self._ledger.record_trade(TradeRecord(
                strategy=self._effective_strategy(proposal, strategy_name),
                action=f"{proposal.action}_failed",
                target=self._scrub_target(proposal),
                amount_tao=proposal.amount_tao,
                price_tao=proposal.price_tao,
                realised_pnl_tao=0.0,
                paper=False,
                note=f"live attempt failed: {reason}",
                tx_hash=None,
            ))
        except Exception as exc:  # pragma: no cover - ledger noise
            logger.warning("failed to record failed-live attempt: %s", exc)
