"""
Live-signing path for the AUTO_TRADING executor.

Bridges three things that must NEVER touch each other directly:

- The encrypted keystore (``tao_swarm.trading.keystore``) which holds
  the seed at rest and only releases it inside a
  :class:`~tao_swarm.trading.keystore.SignerHandle` context.
- The Bittensor SDK (``bittensor>=10``) which exposes
  ``Subtensor.add_stake / unstake / transfer`` against
  ``bittensor.utils.balance.Balance`` amounts.
- The :class:`~tao_swarm.trading.executor.Executor` decision matrix
  which already checks kill-switch / mode / position-cap / daily-loss
  before letting anything reach this module.

This is the FIRST module in the project that is allowed to broadcast
a real transaction. It earns that authority by enforcing the
**three-step authorisation gate** at every call:

1. ``TAO_LIVE_TRADING`` environment variable is exactly ``"1"``.
2. The :class:`Executor` was given a ``signer_factory`` (so the
   operator deliberately wired up signing infrastructure).
3. The strategy's :class:`~tao_swarm.trading.strategy_base.
   StrategyMeta` declares ``live_trading=True``.

If any one is missing, this module refuses without touching the
network or the keystore.

About cold/hot keys
-------------------

Bittensor's ``add_stake`` / ``unstake`` / ``transfer`` extrinsics are
**coldkey-signed** at the protocol level. There is no way for a
read-only "hotkey" to authorise these on the chain — that's a
network rule, not a swarm rule. The keystore in this project stores
whatever seed you put in it; if you intend to auto-trade on Bittensor
mainnet, that seed *will* act as a coldkey for the duration of the
extrinsic.

The protective rule from CLAUDE.md still stands: do **not** put your
main coldkey here. Put a **dedicated** trading coldkey, funded only
with the cap you can afford to lose, and keep your main coldkey on a
hardware wallet or air-gapped machine. The swarm enforces the
position cap, daily-loss limit, and kill-switch — but it cannot
reach into the chain and undo a signed extrinsic.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from tao_swarm.trading.strategy_base import StrategyMeta, TradeProposal

if TYPE_CHECKING:
    from tao_swarm.trading.keystore import SignerHandle

logger = logging.getLogger(__name__)


# Env-var sentinel. Value MUST be exactly "1" — anything else
# (including "true", "yes", "ok") refuses, on purpose. We want
# "did the operator type the magic value" to be the test, not
# "did some downstream code accidentally truthy-cast a string".
LIVE_TRADING_ENV = "TAO_LIVE_TRADING"
LIVE_TRADING_MAGIC_VALUE = "1"

# Actions this signer will broadcast. Any action a strategy emits
# that is not on this list → AuthorizationError. We deliberately
# keep this tight; adding a new live action means adding it here AND
# updating the SDK-call mapping AND adding a test.
SUPPORTED_ACTIONS: frozenset[str] = frozenset({
    "stake", "unstake", "transfer",
})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LiveSignerError(Exception):
    """Base class for everything in this module."""


class AuthorizationError(LiveSignerError):
    """One of the three authorisation steps was not satisfied.

    This is the most common refusal — it means the operator hasn't
    completed the opt-in dance yet, not that anything went wrong on
    the chain. Reasons are deliberately verbose so the operator can
    see which of the three gates they tripped on.
    """


class BroadcastError(LiveSignerError):
    """The SDK accepted the call but the chain rejected it.

    Wraps the ``ExtrinsicResponse.message`` plus any underlying
    ``ExtrinsicResponse.error`` so the operator can audit.
    """


class SignerConfigError(LiveSignerError):
    """The signer was constructed with bad inputs (e.g. empty seed,
    missing target)."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubmitReceipt:
    """The outcome of a single ``BittensorSigner.submit()`` call.

    Mirrors the subset of :class:`bittensor.core.types.ExtrinsicResponse`
    fields the executor cares about, with all SDK-specific types
    flattened so the rest of the swarm doesn't need to import
    ``bittensor`` to inspect a result.

    Chain-truth verification (PR 2H)
    --------------------------------

    When the operator opts in via ``BittensorSigner(verify=True)``,
    the signer re-reads the on-chain stake **after** broadcast and
    reports the result here:

    - ``verified``: ``True`` if the on-chain delta after the
      extrinsic matches the proposal direction within tolerance,
      ``False`` if it doesn't, ``None`` if verification was disabled
      or the read itself failed.
    - ``observed_delta_tao``: signed change in stake observed
      on-chain. Positive for stake, negative for unstake.
    - ``verify_message``: human-readable detail (e.g. "expected
      stake to grow by 1.0 TAO, observed +0.998 TAO within 1% tolerance").

    A failed verification does NOT change the broadcast result —
    the extrinsic was already accepted by the chain. The signer
    surfaces the divergence so the operator's audit trail captures
    it; the executor records a ``_verification_failed`` ledger note.
    """

    success: bool
    message: str
    action: str
    tx_hash: str | None = None
    fee_tao: float | None = None
    raw: Any = None  # the original ExtrinsicResponse, for deep audit
    verified: bool | None = None
    observed_delta_tao: float | None = None
    verify_message: str | None = None


# ---------------------------------------------------------------------------
# Authorisation helper (called by Executor._live_execute)
# ---------------------------------------------------------------------------

def authorise_live_trade(
    *,
    strategy_meta: StrategyMeta | None,
    signer_factory: Callable[[], BittensorSigner] | None,
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Run the three-step gate. Returns ``(ok, reason)``.

    Pure function; no side effects. ``env`` defaults to
    ``os.environ`` but is injectable for tests.
    """
    env = env if env is not None else dict(os.environ)
    if env.get(LIVE_TRADING_ENV) != LIVE_TRADING_MAGIC_VALUE:
        return False, (
            f"live trading requires {LIVE_TRADING_ENV}={LIVE_TRADING_MAGIC_VALUE!r} "
            f"in the environment (got {env.get(LIVE_TRADING_ENV)!r})"
        )
    if signer_factory is None:
        return False, (
            "live trading requires a signer_factory wired into the "
            "Executor; none was provided so the live path is closed"
        )
    if strategy_meta is None:
        return False, (
            "live trading requires the calling strategy to publish a "
            "StrategyMeta with live_trading=True; none was passed in"
        )
    if not strategy_meta.live_trading:
        return False, (
            f"strategy {strategy_meta.name!r} has not opted in to live "
            "trading (StrategyMeta.live_trading=False); paper-only"
        )
    return True, ""


# ---------------------------------------------------------------------------
# BittensorSigner — the actual SDK adapter
# ---------------------------------------------------------------------------

class BittensorSigner:
    """Adapter from a :class:`SignerHandle` + :class:`TradeProposal` to
    a real Bittensor SDK extrinsic.

    Construct with the unlocked keystore handle and a network name
    (``"finney"`` is mainnet, ``"test"`` is testnet). The signer
    opens a ``Subtensor`` connection lazily on first ``submit()``
    and caches it; close it via the context-manager protocol.

    For tests, both ``subtensor_factory`` (returns a Subtensor-like
    object) and ``bittensor_module`` (the ``bittensor`` namespace
    itself) can be injected so the test never touches the real SDK
    or the network. Production callers leave both ``None`` so the
    real SDK is used.
    """

    __slots__ = (
        "_handle", "_network", "_endpoint",
        "_subtensor_factory", "_bittensor_module",
        "_subtensor", "_closed",
        "_verify", "_verify_tolerance_pct", "_coldkey_ss58_for_verify",
    )

    def __init__(
        self,
        handle: SignerHandle,
        *,
        network: str = "finney",
        endpoint: str | None = None,
        subtensor_factory: Callable[..., Any] | None = None,
        bittensor_module: Any = None,
        verify: bool = False,
        verify_tolerance_pct: float = 0.01,
        coldkey_ss58: str | None = None,
    ) -> None:
        if handle is None or handle.closed:
            raise SignerConfigError(
                "BittensorSigner requires an unlocked SignerHandle"
            )
        if verify_tolerance_pct < 0:
            raise SignerConfigError(
                f"verify_tolerance_pct must be >= 0, got {verify_tolerance_pct}"
            )
        self._handle = handle
        self._network = network
        self._endpoint = endpoint
        self._subtensor_factory = subtensor_factory
        self._bittensor_module = bittensor_module
        self._subtensor: Any = None
        self._closed = False
        self._verify = bool(verify)
        self._verify_tolerance_pct = float(verify_tolerance_pct)
        self._coldkey_ss58_for_verify = coldkey_ss58

    # ---- lifecycle ----

    def __enter__(self) -> BittensorSigner:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying Subtensor connection. Idempotent.

        The :class:`SignerHandle` is *not* closed here — its lifetime
        is owned by whoever unlocked it.
        """
        if self._closed:
            return
        sub = self._subtensor
        self._subtensor = None
        self._closed = True
        if sub is not None:
            close = getattr(sub, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:  # pragma: no cover - SDK noise
                    logger.warning("Subtensor.close() raised: %s", exc)

    # ---- public ----

    def submit(
        self,
        proposal: TradeProposal,
        *,
        target_hotkey_ss58: str | None = None,
    ) -> SubmitReceipt:
        """Sign and broadcast ``proposal``. Returns a SubmitReceipt.

        Args:
            proposal: The validated TradeProposal coming from the
                Executor. The action must be in ``SUPPORTED_ACTIONS``.
            target_hotkey_ss58: For ``stake`` / ``unstake`` actions
                this is the hotkey ss58 receiving / releasing the
                stake. For ``transfer`` it is the destination ss58.
                If ``None`` the value is read from ``proposal.target``.

        Raises:
            SignerConfigError: bad inputs (closed handle, missing target).
            AuthorizationError: action not in ``SUPPORTED_ACTIONS``.
            BroadcastError: chain returned a failure response.
        """
        if self._closed:
            raise SignerConfigError("BittensorSigner is closed")
        if proposal.action not in SUPPORTED_ACTIONS:
            raise AuthorizationError(
                f"action {proposal.action!r} not in supported "
                f"live-trading actions {sorted(SUPPORTED_ACTIONS)}; "
                "extend SUPPORTED_ACTIONS + handler if intentional"
            )

        bt = self._bittensor()
        wallet = self._handle.with_seed(
            lambda seed: _build_wallet_from_seed(bt, seed),
        )
        sub = self._get_subtensor(bt)
        amount_balance = bt.utils.balance.Balance.from_tao(proposal.amount_tao)

        # Snapshot pre-broadcast stake for chain-truth verification.
        pre_stake_tao: float | None = None
        if self._verify and proposal.action in ("stake", "unstake"):
            pre_stake_tao = self._read_stake_tao(
                sub=sub,
                proposal=proposal,
                wallet=wallet,
                target_hotkey_ss58=target_hotkey_ss58,
            )

        try:
            response = self._dispatch(
                bt=bt,
                sub=sub,
                wallet=wallet,
                proposal=proposal,
                amount=amount_balance,
                target_hotkey_ss58=target_hotkey_ss58,
            )
        except (AuthorizationError, SignerConfigError):
            raise
        except Exception as exc:
            # SDK / transport errors bubble up as BroadcastError so the
            # Executor can record the failure without a stack trace
            # leaking SDK internals into the ledger note.
            raise BroadcastError(
                f"{proposal.action} broadcast failed: {exc}"
            ) from exc

        success = bool(getattr(response, "success", False))
        message = str(getattr(response, "message", "") or "")
        if not success:
            raise BroadcastError(
                f"{proposal.action} chain-rejected: {message or 'no message'}"
            )

        verified, observed_delta, verify_msg = self._verify_post_broadcast(
            sub=sub,
            proposal=proposal,
            wallet=wallet,
            target_hotkey_ss58=target_hotkey_ss58,
            pre_stake_tao=pre_stake_tao,
        )

        return SubmitReceipt(
            success=True,
            message=message or f"{proposal.action} broadcast accepted",
            action=proposal.action,
            tx_hash=_extract_tx_hash(response),
            fee_tao=_extract_fee_tao(response),
            raw=response,
            verified=verified,
            observed_delta_tao=observed_delta,
            verify_message=verify_msg,
        )

    # ---- internals ----

    def _bittensor(self) -> Any:
        if self._bittensor_module is not None:
            return self._bittensor_module
        # Late-import so this module loads even when bittensor is not
        # installed (e.g. in a paper-only deployment that never calls
        # submit()).
        try:
            os.environ.setdefault("BT_READ_ONLY", "0")
            import bittensor as bt  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SignerConfigError(
                "bittensor SDK is required for live trading; install "
                "with `pip install bittensor>=10`"
            ) from exc
        return bt

    def _get_subtensor(self, bt: Any) -> Any:
        if self._subtensor is not None:
            return self._subtensor
        if self._subtensor_factory is not None:
            self._subtensor = self._subtensor_factory(
                network=self._network, endpoint=self._endpoint,
            )
            return self._subtensor
        # Default: real SDK Subtensor on the configured network.
        kwargs: dict[str, Any] = {"network": self._network}
        if self._endpoint:
            kwargs["chain_endpoint"] = self._endpoint
        self._subtensor = bt.Subtensor(**kwargs)
        return self._subtensor

    def _read_stake_tao(
        self,
        *,
        sub: Any,
        proposal: TradeProposal,
        wallet: Any,
        target_hotkey_ss58: str | None,
    ) -> float | None:
        """Read the current stake for (coldkey, hotkey, netuid) in TAO.

        Returns ``None`` if the read can't be performed — verification
        is best-effort; the broadcast itself already succeeded.
        """
        try:
            netuid = int(proposal.target.get("netuid"))
        except (TypeError, ValueError):
            return None
        hotkey = target_hotkey_ss58 or proposal.target.get("hotkey")
        if not hotkey:
            return None
        coldkey = self._coldkey_ss58_for_verify or _wallet_ss58(wallet)
        if not coldkey:
            return None
        try:
            stakes = sub.get_stake_for_coldkey_and_hotkey(
                coldkey_ss58=str(coldkey),
                hotkey_ss58=str(hotkey),
                netuids=[netuid],
            )
        except Exception as exc:
            logger.warning("verify-read failed: %s", exc)
            return None
        if not stakes:
            return 0.0
        info = stakes.get(netuid) if isinstance(stakes, dict) else None
        if info is None:
            return 0.0
        balance = getattr(info, "stake", info)
        tao = getattr(balance, "tao", None)
        if tao is not None:
            try:
                return float(tao)
            except (TypeError, ValueError):
                return None
        try:
            return float(balance)
        except (TypeError, ValueError):
            return None

    def _verify_post_broadcast(
        self,
        *,
        sub: Any,
        proposal: TradeProposal,
        wallet: Any,
        target_hotkey_ss58: str | None,
        pre_stake_tao: float | None,
    ) -> tuple[bool | None, float | None, str | None]:
        """Re-read on-chain stake and confirm the delta matches the
        proposal direction within ``verify_tolerance_pct``.

        Returns ``(verified, observed_delta_tao, message)``. Each
        component may be ``None`` when verification was disabled or
        skipped (paper trades, transfer action, missing pre-snapshot).
        """
        if not self._verify:
            return None, None, None
        if proposal.action not in ("stake", "unstake"):
            return None, None, "verification skipped: action is not stake/unstake"
        if pre_stake_tao is None:
            return None, None, "verification skipped: pre-broadcast read unavailable"
        post_stake_tao = self._read_stake_tao(
            sub=sub, proposal=proposal, wallet=wallet,
            target_hotkey_ss58=target_hotkey_ss58,
        )
        if post_stake_tao is None:
            return None, None, "verification skipped: post-broadcast read unavailable"
        observed_delta = post_stake_tao - pre_stake_tao
        expected_sign = 1.0 if proposal.action == "stake" else -1.0
        expected_delta = expected_sign * proposal.amount_tao
        # Tolerance is a fraction of the proposed amount.
        tol = abs(expected_delta) * self._verify_tolerance_pct
        # Direction first — if the sign is wrong, no tolerance saves us.
        same_sign = (expected_delta == 0) or (
            (observed_delta >= 0) == (expected_delta >= 0)
        )
        magnitude_ok = abs(observed_delta - expected_delta) <= max(tol, 1e-9)
        verified = bool(same_sign and magnitude_ok)
        msg = (
            f"{proposal.action}: expected delta {expected_delta:+.6f} TAO, "
            f"observed {observed_delta:+.6f} TAO "
            f"(tolerance {self._verify_tolerance_pct * 100:.2f}%)"
        )
        if not verified:
            logger.warning("chain-truth verification mismatch: %s", msg)
        return verified, observed_delta, msg

    def _dispatch(
        self,
        *,
        bt: Any,
        sub: Any,
        wallet: Any,
        proposal: TradeProposal,
        amount: Any,
        target_hotkey_ss58: str | None,
    ) -> Any:
        """Map proposal.action to the right Subtensor method."""
        if proposal.action in ("stake", "unstake"):
            netuid = proposal.target.get("netuid")
            if netuid is None:
                raise SignerConfigError(
                    f"{proposal.action} requires 'netuid' in proposal.target"
                )
            hotkey_ss58 = target_hotkey_ss58 or proposal.target.get("hotkey")
            if not hotkey_ss58:
                raise SignerConfigError(
                    f"{proposal.action} requires a hotkey ss58 (pass "
                    "target_hotkey_ss58=… or set 'hotkey' on the proposal)"
                )
            method = sub.add_stake if proposal.action == "stake" else sub.unstake
            kwargs: dict[str, Any] = {
                "wallet": wallet,
                "netuid": int(netuid),
                "hotkey_ss58": str(hotkey_ss58),
                "amount": amount,
            }
            # Slippage controls (PR 2H). The SDK uses different flag
            # names for stake vs. unstake; pass both rather than
            # branching on action twice.
            if proposal.rate_tolerance is not None:
                kwargs["rate_tolerance"] = float(proposal.rate_tolerance)
                if proposal.action == "stake":
                    kwargs["safe_staking"] = True
                else:
                    kwargs["safe_unstaking"] = True
            if proposal.allow_partial:
                kwargs["allow_partial_stake"] = True
            return method(**kwargs)
        if proposal.action == "transfer":
            destination = (
                target_hotkey_ss58
                or proposal.target.get("destination")
                or proposal.target.get("hotkey")
            )
            if not destination:
                raise SignerConfigError(
                    "transfer requires a destination ss58 (pass "
                    "target_hotkey_ss58=… or set 'destination' on the proposal)"
                )
            return sub.transfer(
                wallet=wallet,
                destination_ss58=str(destination),
                amount=amount,
            )
        # Should be unreachable because submit() pre-checks SUPPORTED_ACTIONS,
        # but defensive in case someone bypasses submit().
        raise AuthorizationError(  # pragma: no cover - defensive
            f"no dispatch for action {proposal.action!r}"
        )


# ---------------------------------------------------------------------------
# Wallet construction from raw seed
# ---------------------------------------------------------------------------

def _build_wallet_from_seed(bt: Any, seed: bytes) -> Any:
    """Construct a Bittensor ``Wallet`` whose coldkey + hotkey are
    derived from ``seed`` — without ever writing the seed to disk.

    Bittensor's standard ``Wallet`` reads keys from
    ``~/.bittensor/wallets/<name>/...``. We bypass that path entirely
    by constructing a ``Keypair`` directly from the seed bytes and
    attaching it to a transient wallet's private slots. The same
    keypair acts as both coldkey and hotkey from the SDK's
    perspective; the on-chain destination hotkey is supplied
    separately per call.

    The seed bytes are passed in as a fresh ``bytes`` copy from
    ``SignerHandle.with_seed()``; this function does NOT retain a
    reference to them after the wallet is built.
    """
    if not isinstance(seed, (bytes, bytearray)) or len(seed) == 0:
        raise SignerConfigError("seed must be non-empty bytes")
    seed_hex = "0x" + bytes(seed).hex()
    keypair = bt.Keypair.create_from_seed(seed_hex)
    wallet = bt.Wallet(name="tao-swarm-live", hotkey="tao-swarm-live")
    # Bittensor's Wallet uses underscore-prefixed slots for the
    # decrypted keypair caches. Setting them here means subsequent
    # ``wallet.coldkey`` / ``wallet.hotkey`` accesses return our
    # in-memory keypair without any disk lookup.
    wallet._coldkey = keypair
    wallet._hotkey = keypair
    # Some SDK paths look at coldkeypub specifically; alias it.
    wallet._coldkeypub = keypair
    return wallet


# ---------------------------------------------------------------------------
# Receipt-extraction helpers — defensive against SDK shape drift
# ---------------------------------------------------------------------------

def _wallet_ss58(wallet: Any) -> str | None:
    """Best-effort coldkey ss58 extraction from a Bittensor Wallet."""
    coldkey = getattr(wallet, "_coldkey", None) or getattr(wallet, "coldkey", None)
    if coldkey is None:
        return None
    return getattr(coldkey, "ss58_address", None)


def _extract_tx_hash(response: Any) -> str | None:
    """Best-effort tx-hash extraction across SDK shapes."""
    receipt = getattr(response, "extrinsic_receipt", None)
    if receipt is None:
        return None
    for attr in ("extrinsic_hash", "block_hash", "hash"):
        val = getattr(receipt, attr, None)
        if val:
            return str(val)
    return None


def _extract_fee_tao(response: Any) -> float | None:
    """Best-effort fee extraction in TAO units."""
    fee = getattr(response, "transaction_tao_fee", None)
    if fee is None:
        fee = getattr(response, "extrinsic_fee", None)
    if fee is None:
        return None
    # Balance objects expose .tao; raw floats / ints pass through.
    tao = getattr(fee, "tao", None)
    if tao is not None:
        try:
            return float(tao)
        except (TypeError, ValueError):
            return None
    try:
        return float(fee)
    except (TypeError, ValueError):
        return None
