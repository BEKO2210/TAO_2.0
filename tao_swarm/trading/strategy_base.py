"""
Strategy abstract base class — the contract every plug-in strategy
implements.

A strategy is a pure function from market state to a list of
:class:`TradeProposal` objects. It does not sign, it does not
broadcast — that's the executor's job. It declares its risk
surface up front (``max_position_tao`` / ``max_daily_loss_tao``)
so the executor can refuse to wire it up if those numbers exceed
the operator's overall caps.

This is intentionally small. Strategies live mostly in their
``evaluate()`` method; the rest is identity + risk metadata so the
orchestrator can register and audit them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TradeProposal:
    """One unit of intent emitted by a strategy.

    The executor decides — based on guards — whether the proposal
    becomes a paper or live trade, or is rejected. The strategy
    only describes what it would *like* to happen.

    Slippage controls (PR 2H)
    -------------------------

    Bittensor staking uses an AMM-style alpha pool, so the realised
    price moves between proposal and broadcast. Two optional fields
    let the strategy bound that risk:

    - ``rate_tolerance``: maximum tolerated relative slippage as a
      fraction (e.g. ``0.005`` = 0.5%). When set, the live signer
      passes ``safe_staking=True`` (or ``safe_unstaking=True``) and
      ``rate_tolerance=…`` to the SDK. ``None`` (default) uses the
      SDK's safe-staking-off behaviour for backwards compatibility.
    - ``allow_partial``: if ``True`` and the chain only has enough
      liquidity for part of the order, accept the partial fill
      instead of failing the whole extrinsic. ``False`` (default)
      mirrors the SDK default — all-or-nothing.

    Both are advisory in paper mode and only consulted by the live
    signer when the executor decides to broadcast.
    """

    action: str               # "buy" / "sell" / "stake" / "unstake" / ...
    target: dict              # {"netuid": 1, "hotkey": "5G..."} etc.
    amount_tao: float
    price_tao: float          # the strategy's assumed price at proposal time
    confidence: float         # 0..1, advisory only
    reasoning: str            # human-readable, audited in the ledger note
    rate_tolerance: float | None = None
    allow_partial: bool = False

    def __post_init__(self) -> None:
        if self.amount_tao <= 0:
            raise ValueError(
                f"TradeProposal.amount_tao must be > 0, got {self.amount_tao}"
            )
        if self.price_tao < 0:
            raise ValueError(
                f"TradeProposal.price_tao cannot be negative, got {self.price_tao}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"TradeProposal.confidence must be in [0, 1], got {self.confidence}"
            )
        if not self.action:
            raise ValueError("TradeProposal.action cannot be empty")
        if self.rate_tolerance is not None and not 0.0 < self.rate_tolerance <= 1.0:
            raise ValueError(
                f"TradeProposal.rate_tolerance must be in (0, 1] when set, "
                f"got {self.rate_tolerance}"
            )


@dataclass(frozen=True)
class StrategyMeta:
    """The risk-surface declaration every strategy must publish.

    ``live_trading`` is the strategy-level half of the
    three-step authorisation that PR 2E's ``Executor`` requires
    before signing anything:

    1. Operator sets ``TAO_LIVE_TRADING=1`` in the environment.
    2. Operator wires a ``signer_factory`` into the ``Executor``.
    3. The strategy declares ``live_trading=True`` in its ``meta()``.

    All three must be true before a real transaction is broadcast.
    The default is ``False`` — strategies are paper-only unless the
    author explicitly opts in.
    """

    name: str
    version: str
    max_position_tao: float
    max_daily_loss_tao: float
    description: str = ""
    actions_used: tuple[str, ...] = field(default_factory=tuple)
    live_trading: bool = False


class Strategy(ABC):
    """Abstract base class for trading strategies.

    Subclasses MUST implement ``meta()`` and ``evaluate()``.
    Subclasses MUST NOT touch wallets, sign anything, or broadcast
    anything — those are explicitly the executor's responsibility.
    """

    @abstractmethod
    def meta(self) -> StrategyMeta:
        """Return the strategy's identity and risk surface.

        Called once at registration time. The orchestrator refuses
        to wire up a strategy whose declared limits exceed the
        operator's global caps (e.g. ``max_position_tao`` >
        ``PositionCap.max_per_position_tao``).
        """

    @abstractmethod
    def evaluate(self, market_state: dict[str, Any]) -> list[TradeProposal]:
        """Look at the current market state and produce zero or
        more trade proposals.

        ``market_state`` is whatever the orchestrator passes in —
        typically a dict assembled from collector outputs (chain
        snapshot, market price, recent emissions, …). The schema
        is defined per-strategy; the executor doesn't introspect it.
        """

    # Convenience — most strategies don't need to override these.

    def __repr__(self) -> str:
        try:
            m = self.meta()
            return f"<Strategy {m.name} v{m.version}>"
        except Exception:
            return f"<Strategy {type(self).__name__}>"
