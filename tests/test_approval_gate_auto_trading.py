"""
Tests for ``ApprovalGate.auto_trading_status()`` — the gate's
"may we route a DANGER action to the executor?" check.

The method must return ``(True, "")`` only when ALL five
conditions hold; on the first failing check it must return
``(False, reason)``. Lock that contract in across every failure
path so a future refactor can't silently weaken it.

Position-cap check is deliberately deferred to
``Executor.execute()`` because the gate doesn't have the
``current_total_tao`` / ``amount_tao`` numbers at classification
time. Don't test for it here.
"""

from __future__ import annotations

import pytest

from tao_swarm.orchestrator.approval_gate import ApprovalGate
from tao_swarm.trading import (
    DailyLossLimit,
    Executor,
    KillSwitch,
    PaperLedger,
    PositionCap,
    TradeRecord,
    WalletMode,
)


def _build_executor(tmp_path, *, kill_tripped=False, daily_loss_breach=False):
    ledger = PaperLedger(tmp_path / "exec.db")
    if daily_loss_breach:
        # Pre-seed -25 TAO loss in the current UTC day; limit will be 20.
        import time
        ledger.record_trade(TradeRecord(
            strategy="seed", action="sell", target={}, amount_tao=10,
            price_tao=1.0, realised_pnl_tao=-25.0, paper=True,
            timestamp=time.time(),
        ))
    flag = tmp_path / "kill.flag"
    if kill_tripped:
        flag.write_text("test trip")
    kill = KillSwitch(flag_path=flag)
    cap = PositionCap(max_per_position_tao=10, max_total_tao=50)
    loss = DailyLossLimit(max_daily_loss_tao=20, ledger=ledger)
    return Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=kill,
        position_cap=cap,
        daily_loss_limit=loss,
        ledger=ledger,
    )


# ---------------------------------------------------------------------------
# Failing paths
# ---------------------------------------------------------------------------

def test_status_false_when_gate_mode_not_auto_trading(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    gate = ApprovalGate(wallet_mode="WATCH_ONLY")
    ex = _build_executor(tmp_path)
    ok, why = gate.auto_trading_status(ex)
    assert ok is False
    assert "WATCH_ONLY" in why
    assert "AUTO_TRADING" in why


def test_status_false_when_executor_missing(monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    gate = ApprovalGate(wallet_mode="AUTO_TRADING")
    ok, why = gate.auto_trading_status(None)
    assert ok is False
    assert "no auto-trading executor" in why


def test_status_false_when_executor_mode_not_auto_trading(tmp_path, monkeypatch):
    """If someone configures the gate as AUTO_TRADING but passes an
    executor that's actually WATCH_ONLY, refuse — the executor is
    the source of truth on its own mode."""
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ledger = PaperLedger(tmp_path / "exec.db")
    ex = Executor(
        mode=WalletMode.WATCH_ONLY,
        kill_switch=KillSwitch(flag_path=tmp_path / "kf"),
        position_cap=PositionCap(10, 50),
        daily_loss_limit=DailyLossLimit(20, ledger),
        ledger=ledger,
    )
    gate = ApprovalGate(wallet_mode="AUTO_TRADING")
    ok, why = gate.auto_trading_status(ex)
    assert ok is False
    assert "executor.mode" in why


def test_status_false_when_kill_switch_tripped_by_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ex = _build_executor(tmp_path, kill_tripped=True)
    gate = ApprovalGate(wallet_mode="AUTO_TRADING")
    ok, why = gate.auto_trading_status(ex)
    assert ok is False
    assert "kill switch" in why
    assert "test trip" in why


def test_status_false_when_kill_switch_tripped_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAO_KILL_SWITCH", "1")
    ex = _build_executor(tmp_path)
    gate = ApprovalGate(wallet_mode="AUTO_TRADING")
    ok, why = gate.auto_trading_status(ex)
    assert ok is False
    assert "kill switch" in why


def test_status_false_when_daily_loss_breached(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ex = _build_executor(tmp_path, daily_loss_breach=True)
    gate = ApprovalGate(wallet_mode="AUTO_TRADING")
    ok, why = gate.auto_trading_status(ex)
    assert ok is False
    assert "daily loss" in why


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_status_true_when_all_conditions_pass(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ex = _build_executor(tmp_path)
    gate = ApprovalGate(wallet_mode="AUTO_TRADING")
    ok, why = gate.auto_trading_status(ex)
    assert ok is True
    assert why == ""


# ---------------------------------------------------------------------------
# Mode-recognition: AUTO_TRADING is now a valid set_wallet_mode value
# ---------------------------------------------------------------------------

def test_set_wallet_mode_accepts_auto_trading():
    gate = ApprovalGate(wallet_mode="NO_WALLET")
    gate.set_wallet_mode("AUTO_TRADING")
    assert gate.wallet_mode == "AUTO_TRADING"


def test_set_wallet_mode_accepts_manual_signing_alias():
    gate = ApprovalGate(wallet_mode="NO_WALLET")
    gate.set_wallet_mode("MANUAL_SIGNING")
    assert gate.wallet_mode == "MANUAL_SIGNING"
    # Legacy alias still works.
    gate.set_wallet_mode("FULL")
    assert gate.wallet_mode == "FULL"


def test_set_wallet_mode_rejects_garbage():
    gate = ApprovalGate(wallet_mode="NO_WALLET")
    with pytest.raises(ValueError):
        gate.set_wallet_mode("FULL_AUTO")
    with pytest.raises(ValueError):
        gate.set_wallet_mode("auto trading")  # space, wrong


# ---------------------------------------------------------------------------
# Read-only-by-default: existing tests still pass
# ---------------------------------------------------------------------------

def test_default_mode_remains_no_wallet():
    """Backwards compat: the gate without args is still NO_WALLET."""
    gate = ApprovalGate()
    assert gate.wallet_mode == "NO_WALLET"
    ok, _ = gate.auto_trading_status(None)
    assert ok is False
