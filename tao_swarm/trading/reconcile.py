"""
Cold-start reconciliation — read on-chain stake into the runner's
position book before the first tick.

Why
===

The :class:`tao_swarm.trading.runner.TradingRunner` keeps an
in-memory position book so the executor's
:class:`~tao_swarm.trading.guards.PositionCap` sees the right
``current_total_tao`` on every tick. That book is built up
incrementally as the runner observes stake / unstake proposals it
itself executed.

If the bot process restarts — crash, deploy, kill — the in-memory
book is lost. Without reconciliation, the next tick would see
``current_total_tao = 0``, the cap arithmetic would be wrong by
the entire amount the operator is already staked, and the runner
could overshoot the operator's exposure cap at the very moment
they cared most about it.

What this module does
=====================

- :class:`ChainPositionReader` — abstract interface for "read the
  on-chain stake of coldkey X". Pluggable so tests can use a fake
  reader and operators can override the source (e.g. a fast cache,
  a different RPC).
- :class:`BittensorChainPositionReader` — concrete implementation
  that uses the same :class:`bittensor.Subtensor` API the live
  signer talks to. Lazy-imports the SDK so paper-only callers
  never load it.
- :class:`ReconciledPosition` — a single (netuid, hotkey, size)
  triple as observed on-chain.

This module never signs or broadcasts anything. It is read-only by
construction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReconciledPosition:
    """One stake row pulled from the chain.

    The runner aggregates these by ``netuid`` to produce the
    in-memory position book; multiple rows on the same netuid (one
    per delegated hotkey) get summed.
    """

    netuid: int
    hotkey_ss58: str
    size_tao: float
    is_registered: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "netuid": self.netuid,
            "hotkey_ss58": self.hotkey_ss58,
            "size_tao": self.size_tao,
            "is_registered": self.is_registered,
        }


class ChainPositionReader:
    """Interface: ``read_positions(coldkey_ss58)`` →
    ``list[ReconciledPosition]``.

    Implementations must be side-effect-free read-only. They MUST
    raise on transport / decode errors so the caller can decide
    whether to fail loudly or fall back to an empty book.
    """

    def read_positions(self, coldkey_ss58: str) -> list[ReconciledPosition]:  # pragma: no cover - interface
        raise NotImplementedError


class BittensorChainPositionReader(ChainPositionReader):
    """Concrete reader backed by ``bittensor.Subtensor``.

    Args:
        network: ``"finney"`` (mainnet), ``"test"`` (testnet) or any
            other network the SDK accepts.
        endpoint: Optional websocket override.
        subtensor_factory: Inject a Subtensor-like object for tests
            so this class can be exercised without the SDK or any
            network.
        bittensor_module: Inject the ``bittensor`` namespace itself
            for tests. Production callers leave this ``None``.
    """

    def __init__(
        self,
        *,
        network: str = "finney",
        endpoint: str | None = None,
        subtensor_factory: Callable[..., Any] | None = None,
        bittensor_module: Any = None,
    ) -> None:
        self._network = network
        self._endpoint = endpoint
        self._subtensor_factory = subtensor_factory
        self._bittensor_module = bittensor_module
        self._subtensor: Any = None

    def close(self) -> None:
        sub = self._subtensor
        self._subtensor = None
        if sub is not None:
            close = getattr(sub, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:  # pragma: no cover - SDK noise
                    logger.warning("Subtensor.close raised on reader: %s", exc)

    def __enter__(self) -> BittensorChainPositionReader:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def read_positions(self, coldkey_ss58: str) -> list[ReconciledPosition]:
        if not coldkey_ss58:
            raise ValueError("coldkey_ss58 must be a non-empty ss58 string")
        bt = self._bittensor()
        sub = self._get_subtensor(bt)
        infos = sub.get_stake_info_for_coldkey(coldkey_ss58=coldkey_ss58)
        if infos is None:
            return []
        out: list[ReconciledPosition] = []
        for info in infos:
            try:
                netuid = int(getattr(info, "netuid"))
                hotkey = str(getattr(info, "hotkey_ss58"))
                size_obj = getattr(info, "stake")
                size_tao = self._balance_to_tao(size_obj)
                is_reg = bool(getattr(info, "is_registered", True))
            except (AttributeError, TypeError, ValueError) as exc:
                logger.warning(
                    "skipping malformed StakeInfo: %r (%s)", info, exc,
                )
                continue
            if size_tao <= 0:
                continue
            out.append(ReconciledPosition(
                netuid=netuid,
                hotkey_ss58=hotkey,
                size_tao=size_tao,
                is_registered=is_reg,
            ))
        return out

    # ---- internals ----

    def _bittensor(self) -> Any:
        if self._bittensor_module is not None:
            return self._bittensor_module
        try:
            import bittensor as bt  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "bittensor SDK is required for chain reconciliation; "
                "install with `pip install bittensor>=10`"
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
        kwargs: dict[str, Any] = {"network": self._network}
        if self._endpoint:
            kwargs["chain_endpoint"] = self._endpoint
        self._subtensor = bt.Subtensor(**kwargs)
        return self._subtensor

    @staticmethod
    def _balance_to_tao(value: Any) -> float:
        """Coerce a SDK ``Balance`` (or plain number) to TAO units."""
        tao = getattr(value, "tao", None)
        if tao is not None:
            try:
                return float(tao)
            except (TypeError, ValueError):
                return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


def aggregate_by_netuid(
    positions: list[ReconciledPosition],
) -> dict[int, float]:
    """Sum ``size_tao`` per netuid across all delegated hotkeys.

    Useful for the runner's per-netuid position book and for the
    executor's ``current_total_tao`` cap arithmetic.
    """
    by_netuid: dict[int, float] = {}
    for p in positions:
        by_netuid[p.netuid] = by_netuid.get(p.netuid, 0.0) + p.size_tao
    return by_netuid
