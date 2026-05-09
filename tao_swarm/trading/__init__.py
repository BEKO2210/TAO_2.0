"""
Trading module — opt-in ``AUTO_TRADING`` mode primitives.

This module is the audited execution path for the
``AUTO_TRADING`` operating mode introduced in PR #45. Nothing in
here signs or broadcasts a real transaction yet; PR 2A delivers
only the safety scaffolding (modes, guards, paper ledger,
strategy ABC, paper-default executor). The real signing path
lands later (PR 2E) once the keystore (PR 2C) is in place.

Always-on safety architecture (mirrors CLAUDE.md):

- Default mode is ``NO_WALLET``. ``AUTO_TRADING`` is opt-in.
- Every value-moving action passes the orchestrator's
  ``ApprovalGate`` first; in ``AUTO_TRADING`` mode the gate routes
  ``DANGER`` actions to the audited ``Executor`` only when ALL of
  these are satisfied:
    1. ``KillSwitch`` is off.
    2. Hot key is configured (PR 2C).
    3. ``PositionCap`` is set and the requested size fits.
    4. ``DailyLossLimit`` is set and not breached.
    5. The strategy explicitly opted in (declared its risk surface).
- Any one of those failing forces a "paper-only" output.
- The signing/broadcast path lives in its own module so the
  read-only swarm stays read-only by construction.

Public surface
--------------

- :class:`WalletMode` — the four operating modes.
- :class:`KillSwitch` — file/env flag, append-only reason log.
- :class:`PositionCap` — per-position and total-exposure cap.
- :class:`DailyLossLimit` — UTC-day P&L floor.
- :class:`PaperLedger` — SQLite-backed paper-trade book.
- :class:`Strategy` — abstract base class for strategy plug-ins.
- :class:`TradeProposal` — what a strategy emits.
- :class:`Executor` — routes a proposal through guards, paper-default.
"""

from __future__ import annotations

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
from tao_swarm.trading.ledger import PaperLedger, TradeRecord
from tao_swarm.trading.modes import WalletMode
from tao_swarm.trading.strategy_base import Strategy, TradeProposal

__all__ = [
    "DailyLossLimit",
    "ExecResult",
    "Executor",
    "KillSwitch",
    "Keystore",
    "KeystoreError",
    "KeystoreFormatError",
    "KeystoreInfo",
    "PaperLedger",
    "PositionCap",
    "SignerHandle",
    "Strategy",
    "TradeProposal",
    "TradeRecord",
    "WalletMode",
    "WrongPasswordError",
]
