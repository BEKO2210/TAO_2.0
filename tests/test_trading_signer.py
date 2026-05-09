"""
Tests for the live signing path (PR 2E).

Covers
======

``authorise_live_trade``:
- Refuses when env var is missing / not the magic value.
- Refuses when signer factory is missing.
- Refuses when strategy_meta is missing.
- Refuses when strategy_meta.live_trading is False.
- Accepts when all three conditions hold.

``BittensorSigner`` with a stubbed bittensor module:
- Constructs via the keystore handle (no disk access for the seed).
- ``submit('stake', ...)`` calls ``Subtensor.add_stake`` with the
  right kwargs and returns a SubmitReceipt.
- ``submit('unstake', ...)`` routes to ``Subtensor.unstake``.
- ``submit('transfer', ...)`` routes to ``Subtensor.transfer`` and
  requires a destination ss58.
- ``submit('register')`` raises AuthorizationError (action not in
  SUPPORTED_ACTIONS).
- A chain-rejected response (success=False) raises BroadcastError.
- Closing the signer also closes the underlying Subtensor.
- Construction fails on a closed handle.
- Construction with bittensor missing surfaces SignerConfigError.

``Executor._live_execute`` end-to-end with stubbed signer:
- Passes when env+signer+strategy.live_trading all set; ledger
  records a non-paper row with the tx_hash.
- Refuses (no raise) when env not set.
- Refuses when strategy.live_trading=False.
- Refuses when no signer_factory wired.
- BroadcastError → status='refused', failed-attempt row recorded.
- Generic signer construction failure → status='error', no
  successful row written.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any
from unittest import mock  # noqa: F401  (kept for future use)

import pytest

from tao_swarm.trading import (
    LIVE_TRADING_ENV,
    SUPPORTED_ACTIONS,
    AuthorizationError,
    BittensorSigner,
    BroadcastError,
    DailyLossLimit,
    Executor,
    KillSwitch,
    PaperLedger,
    PositionCap,
    SignerConfigError,
    StrategyMeta,
    SubmitReceipt,
    TradeProposal,
    WalletMode,
    authorise_live_trade,
)

# ---------------------------------------------------------------------------
# Fixtures: stub bittensor SDK + always-unlocked signer handle
# ---------------------------------------------------------------------------

class _StubKeypair:
    def __init__(self, seed_hex: str) -> None:
        self.seed_hex = seed_hex
        self.ss58_address = "5StubKeypairSS58Address"

    @classmethod
    def create_from_seed(cls, seed_hex: str) -> "_StubKeypair":
        return cls(seed_hex)


class _StubWallet:
    """Mimics bittensor.Wallet's underscore-attribute slots."""

    def __init__(self, name: str = "", hotkey: str = "") -> None:
        self.name = name
        self.hotkey_str = hotkey
        self._coldkey: Any = None
        self._hotkey: Any = None
        self._coldkeypub: Any = None


class _StubBalance:
    def __init__(self, tao: float) -> None:
        self.tao = float(tao)
        self.rao = int(tao * 1e9)

    @classmethod
    def from_tao(cls, tao: float) -> "_StubBalance":
        return cls(tao)


class _StubExtrinsicResponse:
    def __init__(
        self,
        *,
        success: bool = True,
        message: str = "ok",
        tx_hash: str = "0xabcdef1234567890",
        fee_tao: float | None = 0.000125,
    ) -> None:
        self.success = success
        self.message = message
        self.transaction_tao_fee = _StubBalance(fee_tao) if fee_tao is not None else None
        self.extrinsic_receipt = SimpleNamespace(extrinsic_hash=tx_hash)


class _StubSubtensor:
    def __init__(self, *, network: str = "finney", endpoint: str | None = None) -> None:
        self.network = network
        self.endpoint = endpoint
        self.calls: list[tuple[str, dict]] = []
        self.next_response: _StubExtrinsicResponse = _StubExtrinsicResponse()
        self.closed = False

    def add_stake(self, **kwargs: Any) -> _StubExtrinsicResponse:
        self.calls.append(("add_stake", kwargs))
        return self.next_response

    def unstake(self, **kwargs: Any) -> _StubExtrinsicResponse:
        self.calls.append(("unstake", kwargs))
        return self.next_response

    def transfer(self, **kwargs: Any) -> _StubExtrinsicResponse:
        self.calls.append(("transfer", kwargs))
        return self.next_response

    def close(self) -> None:
        self.closed = True


def _stub_bt_module() -> Any:
    """Build a minimal namespace that quacks like ``bittensor``."""
    bt = SimpleNamespace()
    bt.Keypair = _StubKeypair
    bt.Wallet = _StubWallet
    bt.Subtensor = _StubSubtensor
    bt.utils = SimpleNamespace(
        balance=SimpleNamespace(Balance=_StubBalance),
    )
    return bt


class _StubSignerHandle:
    """Mimics SignerHandle.with_seed without actually opening a keystore."""

    def __init__(self, seed: bytes = b"\x01" * 32) -> None:
        self._seed = seed
        self.closed = False
        self.label = "stub"

    def with_seed(self, callback: Any) -> Any:
        if self.closed:
            raise RuntimeError("closed")
        return callback(self._seed)

    def close(self) -> None:
        self.closed = True


def _make_proposal(action: str = "stake", netuid: int = 1) -> TradeProposal:
    return TradeProposal(
        action=action,
        target={"netuid": netuid, "hotkey": "5DestinationHotkeySS58"},
        amount_tao=1.0,
        price_tao=100.0,
        confidence=0.7,
        reasoning="test",
    )


def _make_meta(*, live_trading: bool = True) -> StrategyMeta:
    return StrategyMeta(
        name="stub_strategy",
        version="1.0.0",
        max_position_tao=10.0,
        max_daily_loss_tao=5.0,
        actions_used=("stake", "unstake"),
        live_trading=live_trading,
    )


@pytest.fixture
def signer(tmp_path):
    handle = _StubSignerHandle()
    bt = _stub_bt_module()
    return BittensorSigner(
        handle, network="test",
        bittensor_module=bt,
    )


@pytest.fixture
def executor(tmp_path):
    """Executor in AUTO_TRADING mode with a stubbed signer factory."""
    ledger = PaperLedger(str(tmp_path / "ledger.db"))
    bt = _stub_bt_module()
    handle = _StubSignerHandle()

    def factory() -> BittensorSigner:
        return BittensorSigner(handle, bittensor_module=bt)

    return Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=KillSwitch(flag_path=str(tmp_path / "no_such_kill_file")),
        position_cap=PositionCap(max_per_position_tao=10.0, max_total_tao=100.0),
        daily_loss_limit=DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger),
        ledger=ledger,
        signer_factory=factory,
    ), ledger


# ---------------------------------------------------------------------------
# authorise_live_trade — pure-function gate
# ---------------------------------------------------------------------------

def test_authorise_refuses_when_env_missing():
    ok, reason = authorise_live_trade(
        strategy_meta=_make_meta(),
        signer_factory=lambda: None,  # type: ignore[arg-type, return-value]
        env={},
    )
    assert not ok
    assert LIVE_TRADING_ENV in reason


def test_authorise_refuses_when_env_wrong_value():
    for bad in ("true", "yes", "0", "ok", "TAO_LIVE_TRADING"):
        ok, reason = authorise_live_trade(
            strategy_meta=_make_meta(),
            signer_factory=lambda: None,  # type: ignore[arg-type, return-value]
            env={LIVE_TRADING_ENV: bad},
        )
        assert not ok, f"value {bad!r} should refuse"


def test_authorise_refuses_when_no_signer_factory():
    ok, reason = authorise_live_trade(
        strategy_meta=_make_meta(),
        signer_factory=None,
        env={LIVE_TRADING_ENV: "1"},
    )
    assert not ok
    assert "signer_factory" in reason


def test_authorise_refuses_when_no_meta():
    ok, reason = authorise_live_trade(
        strategy_meta=None,
        signer_factory=lambda: None,  # type: ignore[arg-type, return-value]
        env={LIVE_TRADING_ENV: "1"},
    )
    assert not ok
    assert "StrategyMeta" in reason


def test_authorise_refuses_when_strategy_not_opted_in():
    ok, reason = authorise_live_trade(
        strategy_meta=_make_meta(live_trading=False),
        signer_factory=lambda: None,  # type: ignore[arg-type, return-value]
        env={LIVE_TRADING_ENV: "1"},
    )
    assert not ok
    assert "live_trading" in reason


def test_authorise_passes_when_all_three_set():
    ok, reason = authorise_live_trade(
        strategy_meta=_make_meta(live_trading=True),
        signer_factory=lambda: None,  # type: ignore[arg-type, return-value]
        env={LIVE_TRADING_ENV: "1"},
    )
    assert ok
    assert reason == ""


# ---------------------------------------------------------------------------
# BittensorSigner — direct unit tests with stubs
# ---------------------------------------------------------------------------

def test_signer_rejects_closed_handle():
    handle = _StubSignerHandle()
    handle.closed = True
    with pytest.raises(SignerConfigError):
        BittensorSigner(handle, bittensor_module=_stub_bt_module())


def test_signer_stake_calls_add_stake_with_right_kwargs(signer):
    receipt = signer.submit(
        _make_proposal(action="stake", netuid=4),
        target_hotkey_ss58="5OverrideHotkey",
    )
    assert isinstance(receipt, SubmitReceipt)
    assert receipt.success
    assert receipt.action == "stake"
    assert receipt.tx_hash == "0xabcdef1234567890"
    sub = signer._subtensor  # type: ignore[attr-defined]
    assert len(sub.calls) == 1
    name, kwargs = sub.calls[0]
    assert name == "add_stake"
    assert kwargs["netuid"] == 4
    assert kwargs["hotkey_ss58"] == "5OverrideHotkey"
    assert kwargs["amount"].tao == 1.0


def test_signer_unstake_routes_to_unstake(signer):
    signer.submit(_make_proposal(action="unstake", netuid=2))
    sub = signer._subtensor  # type: ignore[attr-defined]
    assert sub.calls[0][0] == "unstake"


def test_signer_transfer_requires_destination(signer):
    proposal = TradeProposal(
        action="transfer",
        target={},  # no destination, no hotkey
        amount_tao=0.5,
        price_tao=0.0,
        confidence=1.0,
        reasoning="t",
    )
    with pytest.raises(SignerConfigError):
        signer.submit(proposal)


def test_signer_transfer_uses_destination(signer):
    proposal = TradeProposal(
        action="transfer",
        target={"destination": "5DestSS58Addr"},
        amount_tao=0.5,
        price_tao=0.0,
        confidence=1.0,
        reasoning="t",
    )
    signer.submit(proposal)
    sub = signer._subtensor  # type: ignore[attr-defined]
    assert sub.calls[0][0] == "transfer"
    assert sub.calls[0][1]["destination_ss58"] == "5DestSS58Addr"


def test_signer_unsupported_action_raises_authorization_error(signer):
    proposal = TradeProposal(
        action="register",
        target={"netuid": 1},
        amount_tao=1.0,
        price_tao=0.0,
        confidence=0.5,
        reasoning="x",
    )
    with pytest.raises(AuthorizationError):
        signer.submit(proposal)


def test_signer_chain_rejection_raises_broadcast_error(signer):
    # Force the lazy subtensor creation, then mutate response.
    bt = signer._bittensor()  # type: ignore[attr-defined]
    sub = signer._get_subtensor(bt)  # type: ignore[attr-defined]
    sub.next_response = _StubExtrinsicResponse(
        success=False, message="insufficient balance",
    )
    with pytest.raises(BroadcastError) as exc_info:
        signer.submit(_make_proposal())
    assert "insufficient balance" in str(exc_info.value)


def test_signer_close_closes_subtensor(signer):
    signer.submit(_make_proposal())
    sub = signer._subtensor  # type: ignore[attr-defined]
    assert sub.closed is False
    signer.close()
    assert sub.closed is True


def test_signer_double_close_is_idempotent(signer):
    signer.close()
    signer.close()  # no raise


def test_signer_submit_after_close_raises(signer):
    signer.close()
    with pytest.raises(SignerConfigError):
        signer.submit(_make_proposal())


def test_signer_lazy_imports_real_bittensor(monkeypatch):
    """When no bittensor_module is injected, the signer tries to
    import the real one. We replace ``bittensor`` in sys.modules so
    the test never depends on the actual SDK being installed."""
    handle = _StubSignerHandle()
    fake_bt = _stub_bt_module()
    monkeypatch.setitem(sys.modules, "bittensor", fake_bt)
    signer = BittensorSigner(handle)
    receipt = signer.submit(_make_proposal())
    assert receipt.success


def test_signer_missing_bittensor_raises_config_error(monkeypatch):
    handle = _StubSignerHandle()
    monkeypatch.setitem(sys.modules, "bittensor", None)  # type: ignore[arg-type]
    signer = BittensorSigner(handle)
    with pytest.raises(SignerConfigError):
        signer.submit(_make_proposal())


def test_supported_actions_include_stake_unstake_transfer():
    assert "stake" in SUPPORTED_ACTIONS
    assert "unstake" in SUPPORTED_ACTIONS
    assert "transfer" in SUPPORTED_ACTIONS
    # Sanity: nothing else is silently allowed.
    assert SUPPORTED_ACTIONS == frozenset({"stake", "unstake", "transfer"})


def test_signer_stake_missing_netuid_raises(signer):
    proposal = TradeProposal(
        action="stake",
        target={"hotkey": "5SomeHotkey"},  # no netuid
        amount_tao=1.0,
        price_tao=0.0,
        confidence=0.5,
        reasoning="x",
    )
    with pytest.raises(SignerConfigError):
        signer.submit(proposal)


def test_signer_stake_missing_hotkey_raises(signer):
    proposal = TradeProposal(
        action="stake",
        target={"netuid": 1},  # no hotkey, no override either
        amount_tao=1.0,
        price_tao=0.0,
        confidence=0.5,
        reasoning="x",
    )
    with pytest.raises(SignerConfigError):
        signer.submit(proposal)


# ---------------------------------------------------------------------------
# Executor end-to-end with stubbed signer
# ---------------------------------------------------------------------------

def test_executor_live_path_refuses_without_env(executor, monkeypatch):
    ex, ledger = executor
    monkeypatch.delenv(LIVE_TRADING_ENV, raising=False)
    res = ex.execute(
        _make_proposal(),
        paper=False,
        strategy_name="stub",
        strategy_meta=_make_meta(live_trading=True),
    )
    assert res.status == "refused"
    assert LIVE_TRADING_ENV in res.reason
    # No successful trade written to ledger.
    assert ledger.list_trades(strategy="stub") == []


def test_executor_live_path_refuses_when_strategy_not_opted_in(
    executor, monkeypatch,
):
    ex, ledger = executor
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    res = ex.execute(
        _make_proposal(),
        paper=False,
        strategy_name="stub",
        strategy_meta=_make_meta(live_trading=False),
    )
    assert res.status == "refused"
    assert "live_trading" in res.reason
    assert ledger.list_trades(strategy="stub") == []


def test_executor_live_path_refuses_without_signer_factory(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    ledger = PaperLedger(str(tmp_path / "l.db"))
    ex = Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=KillSwitch(flag_path=str(tmp_path / "nokill")),
        position_cap=PositionCap(max_per_position_tao=10.0, max_total_tao=100.0),
        daily_loss_limit=DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger),
        ledger=ledger,
        signer_factory=None,
    )
    assert ex.has_signer is False
    res = ex.execute(
        _make_proposal(),
        paper=False,
        strategy_name="stub",
        strategy_meta=_make_meta(live_trading=True),
    )
    assert res.status == "refused"
    assert "signer_factory" in res.reason


def test_executor_live_path_succeeds_when_authorised(executor, monkeypatch):
    ex, ledger = executor
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    res = ex.execute(
        _make_proposal(action="stake", netuid=7),
        paper=False,
        strategy_name="stub",
        strategy_meta=_make_meta(live_trading=True),
    )
    assert res.status == "executed"
    assert res.paper is False
    rows = ledger.list_trades(strategy="stub")
    assert len(rows) == 1
    assert rows[0].paper is False
    assert rows[0].tx_hash == "0xabcdef1234567890"
    assert rows[0].action == "stake"


def test_executor_records_failed_live_attempt(executor, monkeypatch):
    """A chain rejection should still leave an audit row with
    ``action='stake_failed'`` and no tx_hash, so the operator can
    review what failed."""
    ex, ledger = executor
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")

    # Mutate the signer's subtensor response to simulate failure.
    # We can do this by wrapping the factory.
    bt = _stub_bt_module()
    handle = _StubSignerHandle()

    def failing_factory() -> BittensorSigner:
        signer = BittensorSigner(handle, bittensor_module=bt)
        # Force-create the subtensor so we can override its response.
        sub = signer._get_subtensor(bt)  # type: ignore[attr-defined]
        sub.next_response = _StubExtrinsicResponse(
            success=False, message="bad nonce",
        )
        return signer

    ex_with_fail = Executor(
        mode=ex.mode,
        kill_switch=ex._kill,  # type: ignore[attr-defined]
        position_cap=ex._cap,  # type: ignore[attr-defined]
        daily_loss_limit=ex._loss,  # type: ignore[attr-defined]
        ledger=ledger,
        signer_factory=failing_factory,
    )
    res = ex_with_fail.execute(
        _make_proposal(),
        paper=False,
        strategy_name="stub",
        strategy_meta=_make_meta(live_trading=True),
    )
    assert res.status == "refused"
    assert "bad nonce" in res.reason
    rows = ledger.list_trades(strategy="stub")
    assert len(rows) == 1
    assert rows[0].action == "stake_failed"
    assert rows[0].tx_hash is None
    assert rows[0].paper is False


def test_executor_handles_signer_construction_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    ledger = PaperLedger(str(tmp_path / "l.db"))

    def broken_factory() -> BittensorSigner:
        raise RuntimeError("simulated config blowup")

    ex = Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=KillSwitch(flag_path=str(tmp_path / "nokill")),
        position_cap=PositionCap(max_per_position_tao=10.0, max_total_tao=100.0),
        daily_loss_limit=DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger),
        ledger=ledger,
        signer_factory=broken_factory,
    )
    res = ex.execute(
        _make_proposal(),
        paper=False,
        strategy_name="stub",
        strategy_meta=_make_meta(live_trading=True),
    )
    assert res.status == "error"
    assert "simulated config blowup" in res.reason
    # No ledger row was written for an attempt that never reached the
    # signer. (Failed-live audit is for failures *during* signing.)
    assert ledger.list_trades(strategy="stub") == []


def test_executor_paper_path_unchanged_in_auto_trading_mode(executor, monkeypatch):
    """Paper trades still work, and don't touch the signer at all
    (so they don't need any of the live opt-ins)."""
    ex, ledger = executor
    monkeypatch.delenv(LIVE_TRADING_ENV, raising=False)
    res = ex.execute(
        _make_proposal(),
        paper=True,
        strategy_name="stub",
        strategy_meta=_make_meta(live_trading=False),
    )
    assert res.status == "executed"
    assert res.paper is True


def test_executor_kill_switch_overrides_live(executor, monkeypatch, tmp_path):
    """Kill switch refuses BEFORE the live gate even runs."""
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    kill_path = tmp_path / "kill"
    kill_path.write_text("manual stop")
    ledger = PaperLedger(str(tmp_path / "l.db"))
    bt = _stub_bt_module()
    handle = _StubSignerHandle()
    ex = Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=KillSwitch(flag_path=str(kill_path)),
        position_cap=PositionCap(max_per_position_tao=10.0, max_total_tao=100.0),
        daily_loss_limit=DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger),
        ledger=ledger,
        signer_factory=lambda: BittensorSigner(handle, bittensor_module=bt),
    )
    res = ex.execute(
        _make_proposal(),
        paper=False,
        strategy_name="stub",
        strategy_meta=_make_meta(live_trading=True),
    )
    assert res.status == "refused"
    assert "kill switch" in res.reason
    # No row at all — kill switch refusal happens before _live_execute.
    assert ledger.list_trades(strategy="stub") == []


def test_strategy_meta_live_trading_defaults_false():
    """Brand-new StrategyMeta is paper-only by default."""
    meta = StrategyMeta(
        name="x", version="1", max_position_tao=1.0, max_daily_loss_tao=1.0,
    )
    assert meta.live_trading is False


def test_submit_receipt_carries_fee():
    """SubmitReceipt round-trips the fee_tao value from the SDK."""
    r = SubmitReceipt(
        success=True, message="ok", action="stake",
        tx_hash="0xabc", fee_tao=0.000125,
    )
    assert r.fee_tao == pytest.approx(0.000125)
    # JSON-serialise the fields we care about (ledger uses these).
    payload = {
        "success": r.success, "action": r.action,
        "tx_hash": r.tx_hash, "fee_tao": r.fee_tao,
    }
    json.dumps(payload)  # must not raise
