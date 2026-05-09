"""
Tests for ``tao_swarm.trading`` — modes, guards, ledger, strategy
ABC, executor.

Coverage goals (per the PR 2A scope in CLAUDE.md):

- WalletMode: parsing, capability flags, safe default on garbage.
- KillSwitch: file flag tripped, env var tripped, neither, both,
  reason captured, audit log appends.
- PositionCap: under cap, exact cap, over per-position, over total,
  validation rejects nonsense.
- DailyLossLimit: not breached, exactly at limit, beyond, day-roll
  reset via injected clock.
- PaperLedger: insert/list/sum, idempotent on id, P&L window
  filters, schema migrates on first open.
- Strategy ABC: can't instantiate without overrides, TradeProposal
  rejects negative / NaN amounts.
- Executor: kill-switch refuses first, mode forces paper, position
  cap refuses, daily loss refuses, paper-default succeeds, live
  raises NotImplementedError until PR 2E.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from tao_swarm.trading import (
    DailyLossLimit,
    Executor,
    KillSwitch,
    PaperLedger,
    PositionCap,
    Strategy,
    TradeProposal,
    TradeRecord,
    WalletMode,
)
from tao_swarm.trading.strategy_base import StrategyMeta

# ---------------------------------------------------------------------------
# WalletMode
# ---------------------------------------------------------------------------

def test_wallet_mode_default_is_no_wallet():
    assert WalletMode.from_str(None) is WalletMode.NO_WALLET
    assert WalletMode.from_str("") is WalletMode.NO_WALLET


def test_wallet_mode_parse_known_values():
    assert WalletMode.from_str("WATCH_ONLY") is WalletMode.WATCH_ONLY
    assert WalletMode.from_str("manual_signing") is WalletMode.MANUAL_SIGNING
    assert WalletMode.from_str("  AUTO_TRADING  ") is WalletMode.AUTO_TRADING


def test_wallet_mode_garbage_falls_back_to_no_wallet():
    """A typo in an env var must NEVER silently grant more authority."""
    assert WalletMode.from_str("auto trading") is WalletMode.NO_WALLET
    assert WalletMode.from_str("FULL_AUTO") is WalletMode.NO_WALLET


def test_wallet_mode_capability_flags():
    assert WalletMode.NO_WALLET.can_send_value is False
    assert WalletMode.WATCH_ONLY.can_send_value is False
    assert WalletMode.MANUAL_SIGNING.can_send_value is False
    assert WalletMode.AUTO_TRADING.can_send_value is True
    # Only AUTO_TRADING can sign on its own.
    assert WalletMode.AUTO_TRADING.can_sign is True
    assert WalletMode.MANUAL_SIGNING.can_sign is False
    assert WalletMode.AUTO_TRADING.needs_keystore is True


# ---------------------------------------------------------------------------
# KillSwitch
# ---------------------------------------------------------------------------

def test_killswitch_neither_tripped(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ks = KillSwitch(flag_path=tmp_path / "kill.flag")
    assert ks.is_tripped() is False
    s = ks.state()
    assert s.source == "none"
    assert s.reason is None


def test_killswitch_file_trips(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    flag = tmp_path / "kill.flag"
    flag.write_text("market crash, manual halt")
    ks = KillSwitch(flag_path=flag)
    assert ks.is_tripped() is True
    s = ks.state()
    assert s.source == "file"
    assert "market crash" in s.reason


def test_killswitch_env_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("TAO_KILL_SWITCH", "1")
    ks = KillSwitch(flag_path=tmp_path / "kill.flag")
    assert ks.is_tripped() is True
    assert ks.state().source == "env"


def test_killswitch_env_truthy_variants(tmp_path, monkeypatch):
    for v in ("1", "true", "TRUE", "Yes", "on"):
        monkeypatch.setenv("TAO_KILL_SWITCH", v)
        ks = KillSwitch(flag_path=tmp_path / "kill.flag")
        assert ks.is_tripped() is True, f"value {v!r} should trip"


def test_killswitch_env_falsy_does_not_trip(tmp_path, monkeypatch):
    for v in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("TAO_KILL_SWITCH", v)
        ks = KillSwitch(flag_path=tmp_path / "kill.flag")
        assert ks.is_tripped() is False, f"value {v!r} should NOT trip"


def test_killswitch_audit_log_appends_on_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("TAO_KILL_SWITCH", "1")
    log = tmp_path / "audit.log"
    ks = KillSwitch(flag_path=tmp_path / "kill.flag", log_path=log)
    ks.is_tripped()
    ks.is_tripped()
    text = log.read_text()
    # Two checks, two log lines.
    assert text.count("\n") == 2
    assert "source=env" in text


def test_killswitch_no_reset_method():
    """The bot must NOT have a programmatic way to clear the switch.
    Lock that in by asserting the method does not exist."""
    assert not hasattr(KillSwitch, "reset")
    assert not hasattr(KillSwitch, "untrip")
    assert not hasattr(KillSwitch, "clear")


# ---------------------------------------------------------------------------
# PositionCap
# ---------------------------------------------------------------------------

def test_position_cap_validates_inputs():
    with pytest.raises(ValueError):
        PositionCap(max_per_position_tao=0, max_total_tao=100)
    with pytest.raises(ValueError):
        PositionCap(max_per_position_tao=10, max_total_tao=0)
    with pytest.raises(ValueError):
        PositionCap(max_per_position_tao=200, max_total_tao=100)


def test_position_cap_under_cap_ok():
    cap = PositionCap(max_per_position_tao=10, max_total_tao=50)
    ok, why = cap.can_open(requested_tao=5, current_total_tao=20)
    assert ok is True
    assert why == ""


def test_position_cap_per_position_exceeded():
    cap = PositionCap(max_per_position_tao=10, max_total_tao=50)
    ok, why = cap.can_open(requested_tao=15, current_total_tao=0)
    assert ok is False
    assert "per-position cap" in why


def test_position_cap_total_exceeded():
    cap = PositionCap(max_per_position_tao=10, max_total_tao=50)
    ok, why = cap.can_open(requested_tao=10, current_total_tao=45)
    assert ok is False
    assert "total exposure cap" in why


def test_position_cap_zero_or_negative_request_rejected():
    cap = PositionCap(max_per_position_tao=10, max_total_tao=50)
    ok, why = cap.can_open(requested_tao=0, current_total_tao=0)
    assert ok is False
    ok, why = cap.can_open(requested_tao=-1, current_total_tao=0)
    assert ok is False


# ---------------------------------------------------------------------------
# DailyLossLimit
# ---------------------------------------------------------------------------

def _utc_ts(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()


def test_daily_loss_limit_validates_input(tmp_path):
    ledger = PaperLedger(tmp_path / "ledger.db")
    with pytest.raises(ValueError):
        DailyLossLimit(max_daily_loss_tao=0, ledger=ledger)
    with pytest.raises(ValueError):
        DailyLossLimit(max_daily_loss_tao=-5, ledger=ledger)


def test_daily_loss_limit_not_breached_when_no_trades(tmp_path):
    ledger = PaperLedger(tmp_path / "ledger.db")
    limit = DailyLossLimit(max_daily_loss_tao=10, ledger=ledger)
    assert limit.is_breached() is False
    assert limit.remaining_budget() == 10.0


def test_daily_loss_limit_breaches_at_threshold(tmp_path):
    ledger = PaperLedger(tmp_path / "ledger.db")
    # Pin "now" to 2026-05-09 12:00 UTC so the day starts at 00:00.
    fixed_now = _utc_ts(2026, 5, 9, hour=12)
    limit = DailyLossLimit(
        max_daily_loss_tao=10, ledger=ledger,
        clock=lambda: fixed_now,
    )

    # Record a 6 TAO loss at 10:00 UTC (same day) → not breached.
    ledger.record_trade(TradeRecord(
        strategy="test", action="sell", target={}, amount_tao=10,
        price_tao=1.0, realised_pnl_tao=-6.0, paper=True,
        timestamp=_utc_ts(2026, 5, 9, hour=10),
    ))
    assert limit.daily_pnl() == pytest.approx(-6.0)
    assert limit.is_breached() is False
    assert limit.remaining_budget() == pytest.approx(4.0)

    # Add a further -4 → exactly at the limit → breached.
    ledger.record_trade(TradeRecord(
        strategy="test", action="sell", target={}, amount_tao=4,
        price_tao=1.0, realised_pnl_tao=-4.0, paper=True,
        timestamp=_utc_ts(2026, 5, 9, hour=11),
    ))
    assert limit.is_breached() is True


def test_daily_loss_limit_resets_at_utc_midnight(tmp_path):
    ledger = PaperLedger(tmp_path / "ledger.db")

    # Yesterday's loss should not count toward today's limit.
    yesterday = _utc_ts(2026, 5, 8, hour=23)
    ledger.record_trade(TradeRecord(
        strategy="test", action="sell", target={}, amount_tao=20,
        price_tao=1.0, realised_pnl_tao=-20.0, paper=True,
        timestamp=yesterday,
    ))

    today_noon = _utc_ts(2026, 5, 9, hour=12)
    limit = DailyLossLimit(
        max_daily_loss_tao=10, ledger=ledger,
        clock=lambda: today_noon,
    )
    assert limit.daily_pnl() == pytest.approx(0.0)
    assert limit.is_breached() is False


# ---------------------------------------------------------------------------
# PaperLedger
# ---------------------------------------------------------------------------

def _trade(**kw):
    base = dict(
        strategy="test", action="buy", target={"netuid": 1},
        amount_tao=1.0, price_tao=300.0, realised_pnl_tao=0.0,
        paper=True,
    )
    base.update(kw)
    return TradeRecord(**base)


def test_ledger_record_and_list(tmp_path):
    ledger = PaperLedger(tmp_path / "l.db")
    ledger.record_trade(_trade(amount_tao=1, realised_pnl_tao=2))
    ledger.record_trade(_trade(amount_tao=2, realised_pnl_tao=-1))
    out = ledger.list_trades()
    assert len(out) == 2
    assert ledger.total_count() == 2


def test_ledger_idempotent_on_id(tmp_path):
    ledger = PaperLedger(tmp_path / "l.db")
    t = _trade()
    ledger.record_trade(t)
    ledger.record_trade(t)  # Same id → REPLACE, not duplicate.
    assert ledger.total_count() == 1


def test_ledger_realised_pnl_window(tmp_path):
    ledger = PaperLedger(tmp_path / "l.db")
    base = _utc_ts(2026, 5, 9, hour=12)
    ledger.record_trade(_trade(realised_pnl_tao=10, timestamp=base - 3600))
    ledger.record_trade(_trade(realised_pnl_tao=-3, timestamp=base))
    ledger.record_trade(_trade(realised_pnl_tao=2, timestamp=base + 3600))

    assert ledger.realised_pnl() == pytest.approx(9.0)
    assert ledger.realised_pnl(since=base) == pytest.approx(-1.0)
    assert ledger.realised_pnl(until=base) == pytest.approx(10.0)
    assert ledger.realised_pnl(since=base, until=base + 100) == pytest.approx(-3.0)


def test_ledger_strategy_filter(tmp_path):
    ledger = PaperLedger(tmp_path / "l.db")
    ledger.record_trade(_trade(strategy="alpha", realised_pnl_tao=5))
    ledger.record_trade(_trade(strategy="beta", realised_pnl_tao=-2))
    assert ledger.realised_pnl(strategy="alpha") == 5
    assert ledger.realised_pnl(strategy="beta") == -2


def test_trade_record_round_trip(tmp_path):
    ledger = PaperLedger(tmp_path / "l.db")
    t = _trade(target={"netuid": 7, "hotkey": "5G..."}, note="weight rotation")
    ledger.record_trade(t)
    fetched = ledger.list_trades()
    assert len(fetched) == 1
    assert fetched[0].id == t.id
    assert fetched[0].target == t.target
    assert fetched[0].note == "weight rotation"


# ---------------------------------------------------------------------------
# Strategy ABC + TradeProposal
# ---------------------------------------------------------------------------

def test_strategy_is_abstract():
    with pytest.raises(TypeError):
        Strategy()  # type: ignore[abstract]


def test_strategy_concrete_subclass_works():
    class Demo(Strategy):
        def meta(self):
            return StrategyMeta(
                name="demo", version="1.0",
                max_position_tao=10, max_daily_loss_tao=5,
            )

        def evaluate(self, market_state):
            return []

    d = Demo()
    assert d.meta().name == "demo"
    assert d.evaluate({}) == []


def test_trade_proposal_validates():
    with pytest.raises(ValueError):
        TradeProposal(action="buy", target={}, amount_tao=0,
                      price_tao=1, confidence=0.5, reasoning="x")
    with pytest.raises(ValueError):
        TradeProposal(action="buy", target={}, amount_tao=-1,
                      price_tao=1, confidence=0.5, reasoning="x")
    with pytest.raises(ValueError):
        TradeProposal(action="buy", target={}, amount_tao=1,
                      price_tao=-1, confidence=0.5, reasoning="x")
    with pytest.raises(ValueError):
        TradeProposal(action="buy", target={}, amount_tao=1,
                      price_tao=1, confidence=1.5, reasoning="x")
    with pytest.raises(ValueError):
        TradeProposal(action="", target={}, amount_tao=1,
                      price_tao=1, confidence=0.5, reasoning="x")


def test_trade_proposal_valid_construction():
    p = TradeProposal(
        action="buy", target={"netuid": 1}, amount_tao=2.5,
        price_tao=300.0, confidence=0.7, reasoning="momentum",
    )
    assert p.amount_tao == 2.5


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def _build_executor(tmp_path, mode=WalletMode.AUTO_TRADING, **overrides):
    ledger = PaperLedger(tmp_path / "exec.db")
    kill = KillSwitch(flag_path=tmp_path / "kill.flag")
    cap = PositionCap(max_per_position_tao=10, max_total_tao=50)
    loss = DailyLossLimit(max_daily_loss_tao=20, ledger=ledger)
    kw = dict(
        mode=mode, kill_switch=kill, position_cap=cap,
        daily_loss_limit=loss, ledger=ledger,
    )
    kw.update(overrides)
    return Executor(**kw), ledger, kill


def _proposal(amount=2.0):
    return TradeProposal(
        action="buy", target={"netuid": 1}, amount_tao=amount,
        price_tao=300.0, confidence=0.8, reasoning="test",
    )


def test_executor_kill_switch_refuses_first(tmp_path, monkeypatch):
    monkeypatch.setenv("TAO_KILL_SWITCH", "1")
    ex, ledger, _ = _build_executor(tmp_path)
    r = ex.execute(_proposal(), paper=True)
    assert r.status == "refused"
    assert "kill switch" in r.reason
    # Nothing should have been recorded.
    assert ledger.total_count() == 0


def test_executor_non_auto_mode_forces_paper(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ex, ledger, _ = _build_executor(tmp_path, mode=WalletMode.WATCH_ONLY)
    r = ex.execute(_proposal(), paper=True)
    assert r.status == "executed"
    assert r.paper is True
    assert ledger.total_count() == 1


def test_executor_non_auto_mode_refuses_live(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ex, ledger, _ = _build_executor(tmp_path, mode=WalletMode.MANUAL_SIGNING)
    r = ex.execute(_proposal(), paper=False)
    assert r.status == "refused"
    assert "MANUAL_SIGNING" in r.reason or "paper" in r.reason.lower()
    assert ledger.total_count() == 0


def test_executor_position_cap_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ex, ledger, _ = _build_executor(tmp_path)
    # 100 TAO request > 10 per-position cap, in auto-trading mode.
    r = ex.execute(_proposal(amount=100), paper=False, current_total_tao=0)
    assert r.status == "refused"
    assert "position cap" in r.reason
    assert ledger.total_count() == 0


def test_executor_daily_loss_breach_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    # Pre-seed a -25 TAO loss today; limit is 20. Limit is breached.
    ledger = PaperLedger(tmp_path / "exec.db")
    ledger.record_trade(_trade(realised_pnl_tao=-25, timestamp=time.time()))
    kill = KillSwitch(flag_path=tmp_path / "kill.flag")
    cap = PositionCap(max_per_position_tao=10, max_total_tao=50)
    loss = DailyLossLimit(max_daily_loss_tao=20, ledger=ledger)
    ex = Executor(
        mode=WalletMode.AUTO_TRADING, kill_switch=kill,
        position_cap=cap, daily_loss_limit=loss, ledger=ledger,
    )
    r = ex.execute(_proposal(amount=2), paper=False, current_total_tao=0)
    assert r.status == "refused"
    assert "daily loss" in r.reason


def test_executor_paper_default_records_to_ledger(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ex, ledger, _ = _build_executor(tmp_path)
    r = ex.execute(_proposal(amount=2), paper=True, current_total_tao=0,
                   strategy_name="alpha")
    assert r.is_ok()
    assert r.paper is True
    rows = ledger.list_trades()
    assert len(rows) == 1
    assert rows[0].strategy == "alpha"
    assert rows[0].paper is True


def test_executor_live_path_refuses_without_signer_factory(tmp_path, monkeypatch):
    """With PR 2E in place the live path no longer raises
    NotImplementedError — it returns a clean refusal because no
    ``signer_factory`` was wired into the Executor. The point of the
    test is to lock in that the live path REFUSES (not raises and not
    silently succeeds) when authorisation prerequisites aren't met.

    The companion test in ``tests/test_trading_signer.py`` covers the
    end-to-end success path with a stubbed signer."""
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    monkeypatch.delenv("TAO_LIVE_TRADING", raising=False)
    ex, ledger, _ = _build_executor(tmp_path)
    res = ex.execute(_proposal(amount=2), paper=False, current_total_tao=0)
    assert res.status == "refused"
    assert "TAO_LIVE_TRADING" in res.reason or "signer_factory" in res.reason
    # No successful trade row written.
    assert ledger.total_count() == 0


def test_executor_rejects_non_proposal(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_KILL_SWITCH", raising=False)
    ex, ledger, _ = _build_executor(tmp_path)
    r = ex.execute("not a proposal", paper=True)  # type: ignore[arg-type]
    assert r.status == "error"
    assert ledger.total_count() == 0
