"""
Trading module — opt-in ``AUTO_TRADING`` mode primitives.

The audited execution path for the ``AUTO_TRADING`` operating mode
introduced in PR #45. With PR 2E in place this module CAN now sign
and broadcast real Bittensor extrinsics — but only when every guard
in the multi-stage authorisation chain consents.

Always-on safety architecture (mirrors CLAUDE.md):

- Default mode is ``NO_WALLET``. ``AUTO_TRADING`` is opt-in.
- Every value-moving action passes the orchestrator's
  ``ApprovalGate`` first; in ``AUTO_TRADING`` mode the gate routes
  ``DANGER`` actions to the audited ``Executor`` only when ALL of
  these are satisfied:
    1. ``KillSwitch`` is off.
    2. Keystore is configured and unlocked (PR 2C).
    3. ``PositionCap`` is set and the requested size fits.
    4. ``DailyLossLimit`` is set and not breached.
    5. The strategy explicitly opted in (``StrategyMeta.live_trading``).
- Any one of those failing forces a "paper-only" output.
- The live path runs a SECOND three-step gate
  (:func:`authorise_live_trade`) before signing: env var
  ``TAO_LIVE_TRADING=1`` + signer factory wired up + strategy
  meta opt-in. All three must hold.

Public surface
--------------

- :class:`WalletMode` — the four operating modes.
- :class:`KillSwitch` / :class:`PositionCap` /
  :class:`DailyLossLimit` — guards.
- :class:`PaperLedger` — SQLite-backed paper + live trade book.
- :class:`Keystore` / :class:`SignerHandle` — encrypted hot-key
  storage with one-shot seed access.
- :class:`Strategy` / :class:`StrategyMeta` / :class:`TradeProposal`
  — strategy ABC and value types.
- :class:`Executor` — routes a proposal through guards.
- :class:`BittensorSigner` / :func:`authorise_live_trade` /
  :class:`SubmitReceipt` — live signing path (PR 2E).
- :class:`Backtester` / :class:`BacktestResult` — deterministic
  paper-only harness over historical snapshots.
"""

from __future__ import annotations

from tao_swarm.trading.backtest import Backtester, BacktestResult
from tao_swarm.trading.brain import (
    DEFAULT_WEIGHTS as BRAIN_DEFAULT_WEIGHTS,
)
from tao_swarm.trading.brain import (
    AgentSignal,
    BrainDecision,
    TradingBrain,
)
from tao_swarm.trading.executor import ExecResult, Executor
from tao_swarm.trading.guards import (
    DailyLossLimit,
    KillSwitch,
    PositionCap,
)
from tao_swarm.trading.keystore import (
    Keystore,
    KeystoreError,
    KeystoreFormatError,
    KeystoreInfo,
    SignerHandle,
    WrongPasswordError,
)
from tao_swarm.trading.learning import (
    CalibrationBucket,
    ConfidenceCalibrator,
    EnsembleStrategy,
    PerformanceTracker,
    StrategyPerformance,
    inverse_loss_weights,
    uniform_weights,
)
from tao_swarm.trading.ledger import PaperLedger, TradeRecord
from tao_swarm.trading.modes import WalletMode
from tao_swarm.trading.reconcile import (
    BittensorChainPositionReader,
    ChainPositionReader,
    ReconciledPosition,
    aggregate_by_netuid,
)
from tao_swarm.trading.runner import (
    MarketStateBuilder,
    RunnerStatus,
    TradingRunner,
)
from tao_swarm.trading.signer import (
    LIVE_TRADING_ENV,
    LIVE_TRADING_MAGIC_VALUE,
    SUPPORTED_ACTIONS,
    AuthorizationError,
    BittensorSigner,
    BroadcastError,
    LiveSignerError,
    SignerConfigError,
    SubmitReceipt,
    authorise_live_trade,
)
from tao_swarm.trading.strategy_base import Strategy, StrategyMeta, TradeProposal
from tao_swarm.trading.strategy_loader import (
    StrategyLoadSummary,
    StrategyRegistry,
    load_strategy_plugins,
)

__all__ = [
    "LIVE_TRADING_ENV",
    "LIVE_TRADING_MAGIC_VALUE",
    "SUPPORTED_ACTIONS",
    "AuthorizationError",
    "AgentSignal",
    "BRAIN_DEFAULT_WEIGHTS",
    "BacktestResult",
    "Backtester",
    "BrainDecision",
    "TradingBrain",
    "BittensorChainPositionReader",
    "BittensorSigner",
    "BroadcastError",
    "CalibrationBucket",
    "ChainPositionReader",
    "ConfidenceCalibrator",
    "DailyLossLimit",
    "EnsembleStrategy",
    "ExecResult",
    "Executor",
    "KillSwitch",
    "Keystore",
    "KeystoreError",
    "KeystoreFormatError",
    "KeystoreInfo",
    "LiveSignerError",
    "MarketStateBuilder",
    "PaperLedger",
    "PerformanceTracker",
    "PositionCap",
    "ReconciledPosition",
    "RunnerStatus",
    "SignerConfigError",
    "SignerHandle",
    "Strategy",
    "StrategyLoadSummary",
    "StrategyMeta",
    "StrategyPerformance",
    "StrategyRegistry",
    "SubmitReceipt",
    "TradeProposal",
    "TradeRecord",
    "TradingRunner",
    "WalletMode",
    "WrongPasswordError",
    "aggregate_by_netuid",
    "authorise_live_trade",
    "inverse_loss_weights",
    "load_strategy_plugins",
    "uniform_weights",
]
