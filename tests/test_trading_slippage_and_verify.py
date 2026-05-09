"""
Tests for the PR 2H additions:

- Slippage passthroughs (``rate_tolerance``, ``allow_partial``) on
  :class:`TradeProposal` → :class:`BittensorSigner`.
- Post-broadcast chain-truth verification on :class:`BittensorSigner`
  + the executor's ``_verification_failed`` audit row.

The tests use a stubbed bittensor module so nothing real is signed
or broadcast. The stubs are richer than ``test_trading_signer.py``'s
because they need to track per-(coldkey, hotkey, netuid) stake
state and react to the slippage kwargs.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tao_swarm.trading import (
    LIVE_TRADING_ENV,
    BittensorSigner,
    DailyLossLimit,
    Executor,
    KillSwitch,
    PaperLedger,
    PositionCap,
    StrategyMeta,
    TradeProposal,
    WalletMode,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubBalance:
    def __init__(self, tao: float) -> None:
        self.tao = float(tao)

    @classmethod
    def from_tao(cls, tao: float) -> "_StubBalance":
        return cls(tao)


class _StubKeypair:
    def __init__(self, seed_hex: str) -> None:
        self.seed_hex = seed_hex
        self.ss58_address = "5SignerColdkeySS58"

    @classmethod
    def create_from_seed(cls, seed_hex: str) -> "_StubKeypair":
        return cls(seed_hex)


class _StubWallet:
    def __init__(self, name: str = "", hotkey: str = "") -> None:
        self.name = name
        self._coldkey: Any = None
        self._hotkey: Any = None
        self._coldkeypub: Any = None


class _StatefulSubtensor:
    """Mimics enough of bittensor.Subtensor to track stake state."""

    def __init__(self, *, network: str = "finney", endpoint: str | None = None) -> None:
        self.network = network
        self.endpoint = endpoint
        # (coldkey_ss58, hotkey_ss58, netuid) → tao
        self._stakes: dict[tuple[str, str, int], float] = {}
        self.calls: list[tuple[str, dict]] = []
        self.next_response_success: bool = True
        self.applied_delta_factor: float = 1.0  # used to simulate slippage
        self.closed = False

    # --- read paths ---

    def get_stake_for_coldkey_and_hotkey(
        self, *, coldkey_ss58: str, hotkey_ss58: str, netuids=None,
    ):
        out = {}
        if netuids:
            for n in netuids:
                key = (coldkey_ss58, hotkey_ss58, int(n))
                tao = self._stakes.get(key, 0.0)
                out[int(n)] = SimpleNamespace(stake=_StubBalance(tao))
        return out

    # --- write paths ---

    def add_stake(self, *, wallet, netuid, hotkey_ss58, amount, **kwargs):
        self.calls.append(("add_stake", {
            "netuid": netuid, "hotkey_ss58": hotkey_ss58, "amount": amount,
            **kwargs,
        }))
        if not self.next_response_success:
            return SimpleNamespace(success=False, message="rejected")
        coldkey = wallet._coldkey.ss58_address
        key = (coldkey, hotkey_ss58, int(netuid))
        self._stakes[key] = self._stakes.get(key, 0.0) + (
            amount.tao * self.applied_delta_factor
        )
        return SimpleNamespace(
            success=True, message="ok",
            extrinsic_receipt=SimpleNamespace(extrinsic_hash="0xstaked"),
        )

    def unstake(self, *, wallet, netuid, hotkey_ss58, amount, **kwargs):
        self.calls.append(("unstake", {
            "netuid": netuid, "hotkey_ss58": hotkey_ss58, "amount": amount,
            **kwargs,
        }))
        if not self.next_response_success:
            return SimpleNamespace(success=False, message="rejected")
        coldkey = wallet._coldkey.ss58_address
        key = (coldkey, hotkey_ss58, int(netuid))
        delta = amount.tao * self.applied_delta_factor
        self._stakes[key] = max(0.0, self._stakes.get(key, 0.0) - delta)
        return SimpleNamespace(
            success=True, message="ok",
            extrinsic_receipt=SimpleNamespace(extrinsic_hash="0xunstaked"),
        )

    def transfer(self, *, wallet, destination_ss58, amount, **kwargs):
        self.calls.append(("transfer", {
            "destination_ss58": destination_ss58, "amount": amount, **kwargs,
        }))
        return SimpleNamespace(
            success=True, message="ok",
            extrinsic_receipt=SimpleNamespace(extrinsic_hash="0xtransfer"),
        )

    def close(self) -> None:
        self.closed = True


def _bt_module() -> Any:
    bt = SimpleNamespace()
    bt.Keypair = _StubKeypair
    bt.Wallet = _StubWallet
    bt.utils = SimpleNamespace(balance=SimpleNamespace(Balance=_StubBalance))
    return bt


class _StubHandle:
    def __init__(self) -> None:
        self.closed = False
        self.label = "stub"

    def with_seed(self, callback):
        return callback(b"\x01" * 32)

    def close(self):
        self.closed = True


def _proposal(
    action: str = "stake",
    netuid: int = 1,
    amount: float = 1.0,
    *,
    rate_tolerance: float | None = None,
    allow_partial: bool = False,
) -> TradeProposal:
    return TradeProposal(
        action=action,
        target={"netuid": netuid, "hotkey": "5DestHotkey"},
        amount_tao=amount,
        price_tao=100.0,
        confidence=0.5,
        reasoning="t",
        rate_tolerance=rate_tolerance,
        allow_partial=allow_partial,
    )


def _meta(*, live: bool = True) -> StrategyMeta:
    return StrategyMeta(
        name="stub", version="1.0",
        max_position_tao=10.0, max_daily_loss_tao=10.0,
        actions_used=("stake", "unstake"),
        live_trading=live,
    )


# ---------------------------------------------------------------------------
# TradeProposal — slippage field validation
# ---------------------------------------------------------------------------

def test_proposal_rejects_negative_rate_tolerance():
    with pytest.raises(ValueError):
        TradeProposal(
            action="stake", target={"netuid": 1}, amount_tao=1.0,
            price_tao=0.0, confidence=0.5, reasoning="x",
            rate_tolerance=-0.01,
        )


def test_proposal_rejects_rate_tolerance_above_one():
    with pytest.raises(ValueError):
        TradeProposal(
            action="stake", target={"netuid": 1}, amount_tao=1.0,
            price_tao=0.0, confidence=0.5, reasoning="x",
            rate_tolerance=1.5,
        )


def test_proposal_accepts_none_rate_tolerance():
    p = TradeProposal(
        action="stake", target={"netuid": 1}, amount_tao=1.0,
        price_tao=0.0, confidence=0.5, reasoning="x",
    )
    assert p.rate_tolerance is None
    assert p.allow_partial is False


def test_proposal_accepts_valid_slippage_combo():
    p = TradeProposal(
        action="stake", target={"netuid": 1}, amount_tao=1.0,
        price_tao=0.0, confidence=0.5, reasoning="x",
        rate_tolerance=0.005, allow_partial=True,
    )
    assert p.rate_tolerance == 0.005
    assert p.allow_partial is True


# ---------------------------------------------------------------------------
# Signer — slippage passthrough
# ---------------------------------------------------------------------------

def test_signer_passes_rate_tolerance_to_add_stake():
    bt = _bt_module()
    sub = _StatefulSubtensor()
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(_StubHandle(), bittensor_module=bt)
    signer.submit(_proposal(action="stake", rate_tolerance=0.005))
    assert sub.calls[0][0] == "add_stake"
    kwargs = sub.calls[0][1]
    assert kwargs["rate_tolerance"] == 0.005
    assert kwargs.get("safe_staking") is True


def test_signer_passes_rate_tolerance_to_unstake_with_correct_flag():
    bt = _bt_module()
    sub = _StatefulSubtensor()
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(_StubHandle(), bittensor_module=bt)
    # Pre-fund so the unstake doesn't fail verification by going negative.
    sub._stakes[("5SignerColdkeySS58", "5DestHotkey", 1)] = 5.0
    signer.submit(_proposal(action="unstake", rate_tolerance=0.005))
    kwargs = sub.calls[0][1]
    assert kwargs["rate_tolerance"] == 0.005
    # Unstake uses safe_unstaking flag, not safe_staking.
    assert kwargs.get("safe_unstaking") is True
    assert "safe_staking" not in kwargs


def test_signer_passes_allow_partial_stake():
    bt = _bt_module()
    sub = _StatefulSubtensor()
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(_StubHandle(), bittensor_module=bt)
    signer.submit(_proposal(action="stake", allow_partial=True))
    assert sub.calls[0][1].get("allow_partial_stake") is True


def test_signer_omits_slippage_kwargs_when_unset():
    bt = _bt_module()
    sub = _StatefulSubtensor()
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(_StubHandle(), bittensor_module=bt)
    signer.submit(_proposal(action="stake"))
    kwargs = sub.calls[0][1]
    assert "rate_tolerance" not in kwargs
    assert "safe_staking" not in kwargs
    assert "allow_partial_stake" not in kwargs


# ---------------------------------------------------------------------------
# Signer — chain-truth verification
# ---------------------------------------------------------------------------

def test_signer_verify_off_by_default():
    bt = _bt_module()
    sub = _StatefulSubtensor()
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(_StubHandle(), bittensor_module=bt)
    receipt = signer.submit(_proposal(action="stake"))
    assert receipt.verified is None
    assert receipt.observed_delta_tao is None


def test_signer_verify_success_records_match():
    bt = _bt_module()
    sub = _StatefulSubtensor()
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(
        _StubHandle(), bittensor_module=bt,
        verify=True, verify_tolerance_pct=0.01,
    )
    receipt = signer.submit(_proposal(action="stake", amount=1.0))
    assert receipt.verified is True
    assert receipt.observed_delta_tao == pytest.approx(1.0)
    assert "expected" in (receipt.verify_message or "")


def test_signer_verify_detects_under_delivery():
    """SDK reports success but the chain only credited 50% of the
    requested amount → verification fails."""
    bt = _bt_module()
    sub = _StatefulSubtensor()
    sub.applied_delta_factor = 0.5  # only half of the requested amount lands
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(
        _StubHandle(), bittensor_module=bt,
        verify=True, verify_tolerance_pct=0.01,
    )
    receipt = signer.submit(_proposal(action="stake", amount=1.0))
    assert receipt.success is True  # broadcast itself accepted
    assert receipt.verified is False
    assert receipt.observed_delta_tao == pytest.approx(0.5)


def test_signer_verify_within_tolerance_passes():
    """Tiny rounding mismatch within tolerance is verified OK."""
    bt = _bt_module()
    sub = _StatefulSubtensor()
    sub.applied_delta_factor = 0.999  # 0.1% under, within 1% tolerance
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(
        _StubHandle(), bittensor_module=bt,
        verify=True, verify_tolerance_pct=0.01,
    )
    receipt = signer.submit(_proposal(action="stake", amount=1.0))
    assert receipt.verified is True


def test_signer_verify_unstake_direction():
    bt = _bt_module()
    sub = _StatefulSubtensor()
    sub._stakes[("5SignerColdkeySS58", "5DestHotkey", 1)] = 5.0
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(
        _StubHandle(), bittensor_module=bt,
        verify=True,
    )
    receipt = signer.submit(_proposal(action="unstake", amount=1.0))
    assert receipt.verified is True
    assert receipt.observed_delta_tao == pytest.approx(-1.0)


def test_signer_verify_skipped_for_transfer():
    bt = _bt_module()
    sub = _StatefulSubtensor()
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(
        _StubHandle(), bittensor_module=bt,
        verify=True,
    )
    proposal = TradeProposal(
        action="transfer",
        target={"destination": "5DestSS58Addr"},
        amount_tao=0.5, price_tao=0.0, confidence=1.0, reasoning="t",
    )
    receipt = signer.submit(proposal)
    assert receipt.verified is None
    assert receipt.observed_delta_tao is None
    assert receipt.verify_message and "stake/unstake" in receipt.verify_message


def test_signer_verify_rejects_negative_tolerance():
    from tao_swarm.trading import SignerConfigError
    with pytest.raises(SignerConfigError):
        BittensorSigner(
            _StubHandle(), bittensor_module=_bt_module(),
            verify=True, verify_tolerance_pct=-0.1,
        )


def test_signer_verify_handles_post_read_failure():
    """If the post-broadcast read raises, verification reports None
    rather than crashing the whole broadcast."""
    bt = _bt_module()

    class _FlakySub(_StatefulSubtensor):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._post_call_count = 0

        def get_stake_for_coldkey_and_hotkey(self, **kw):
            self._post_call_count += 1
            if self._post_call_count > 1:
                # Simulate the post-broadcast read failing.
                raise ConnectionError("rpc dropped")
            return super().get_stake_for_coldkey_and_hotkey(**kw)

    sub = _FlakySub()
    bt.Subtensor = lambda **kwargs: sub
    signer = BittensorSigner(
        _StubHandle(), bittensor_module=bt,
        verify=True,
    )
    receipt = signer.submit(_proposal(action="stake"))
    assert receipt.success is True
    assert receipt.verified is None  # skipped, not failed
    assert "post-broadcast" in (receipt.verify_message or "")


# ---------------------------------------------------------------------------
# Executor — verification result threads into ledger
# ---------------------------------------------------------------------------

def _build_executor_with_signer(tmp_path, sub: _StatefulSubtensor, *, verify: bool):
    ledger = PaperLedger(str(tmp_path / "ledger.db"))
    bt = _bt_module()
    bt.Subtensor = lambda **kwargs: sub
    handle = _StubHandle()

    def factory():
        return BittensorSigner(
            handle, bittensor_module=bt,
            verify=verify,
        )

    return Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=KillSwitch(flag_path=str(tmp_path / "no_kill")),
        position_cap=PositionCap(max_per_position_tao=10.0, max_total_tao=100.0),
        daily_loss_limit=DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger),
        ledger=ledger,
        signer_factory=factory,
    ), ledger


def test_executor_records_verified_action_on_match(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    sub = _StatefulSubtensor()
    ex, ledger = _build_executor_with_signer(tmp_path, sub, verify=True)
    ex.execute(
        _proposal(action="stake"),
        paper=False, strategy_name="t",
        strategy_meta=_meta(),
    )
    rows = ledger.list_trades(strategy="t")
    assert len(rows) == 1
    assert rows[0].action == "stake"
    assert "verified" in rows[0].note


def test_executor_records_verification_failed_action_on_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    sub = _StatefulSubtensor()
    sub.applied_delta_factor = 0.4
    ex, ledger = _build_executor_with_signer(tmp_path, sub, verify=True)
    res = ex.execute(
        _proposal(action="stake"),
        paper=False, strategy_name="t",
        strategy_meta=_meta(),
    )
    # Broadcast itself succeeded — extrinsic accepted.
    assert res.status == "executed"
    rows = ledger.list_trades(strategy="t")
    assert len(rows) == 1
    assert rows[0].action == "stake_verification_failed"
    assert "VERIFY-MISMATCH" in rows[0].note


def test_executor_no_verify_when_signer_verify_off(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_TRADING_ENV, "1")
    sub = _StatefulSubtensor()
    sub.applied_delta_factor = 0.0  # would fail verification IF it ran
    ex, ledger = _build_executor_with_signer(tmp_path, sub, verify=False)
    ex.execute(
        _proposal(action="stake"),
        paper=False, strategy_name="t",
        strategy_meta=_meta(),
    )
    rows = ledger.list_trades(strategy="t")
    # No verify_message, action stays plain "stake".
    assert rows[0].action == "stake"
    assert "verified" not in rows[0].note
    assert "VERIFY-MISMATCH" not in rows[0].note
