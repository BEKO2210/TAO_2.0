"""
Shared base for read-only collectors.

Every collector in ``src/collectors/`` honours the same mock/live
contract:

- ``use_mock_data: bool`` (config key) — single source of truth.
  Default **True** because the swarm is offline-first and SPEC.md
  rules out cloud telemetry. Callers (CLI, tests) flip this to False
  when they want to talk to the real upstream.

- ``_resolve_mode(reason_when_unavailable) -> str`` — returns either
  ``"mock"`` or ``"live"``. If a collector asks for live but the
  underlying dependency (network, SDK) isn't usable, this method
  returns ``"mock"`` and records the reason on
  ``self._mock_fallback_reason`` so the result payload can carry a
  ``_meta`` block explaining what happened. This keeps the swarm
  auditable: a downstream agent never has to guess whether the
  data came from upstream or a fixture.

- ``_meta(...)`` — builds the standard metadata dict every collector
  result should carry: source name, mode, fetched-at timestamp, and
  the fallback reason if applicable. Consumers can read
  ``payload["_meta"]["mode"]`` to tell mock from live without parsing
  the body.

The base intentionally doesn't enforce a method shape on subclasses
— different collectors expose different reads (subnets vs repos vs
prices) and the swarm has lived with that variety since day one.
What we standardise here is the *plumbing*, not the surface.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class BaseCollector:
    """
    Common scaffolding for the five collectors.

    Subclasses still implement their own data-fetch methods. They
    consult ``self.use_mock_data`` (or call ``self._resolve_mode``
    when a live attempt is feasible) to choose between fixture data
    and a real upstream call, and they wrap their return payload
    with ``self._meta`` so callers can audit the source.
    """

    SOURCE_NAME: str = "unknown_collector"

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        # Offline-first: default to mock so importing a collector
        # doesn't accidentally hit the network during tests.
        self.use_mock_data: bool = bool(config.get("use_mock_data", True))
        self.cache_ttl: float = float(config.get("cache_ttl", 300))
        self.timeout: float = float(config.get("timeout", 10))
        self._mock_fallback_reason: str | None = None
        logger.debug(
            "%s initialized (use_mock_data=%s, cache_ttl=%.0fs)",
            self.SOURCE_NAME, self.use_mock_data, self.cache_ttl,
        )

    # ------------------------------------------------------------------
    # Mode selection
    # ------------------------------------------------------------------

    def _resolve_mode(
        self,
        live_available: bool = True,
        reason_when_unavailable: str = "",
    ) -> str:
        """
        Decide whether this call should run mock or live.

        Returns ``"mock"`` when ``use_mock_data`` is True or when the
        caller signals that the live path is unavailable (e.g. the
        SDK isn't installed). When falling back from live to mock
        because of unavailability, sets ``_mock_fallback_reason`` so
        the result payload can carry it.
        """
        if self.use_mock_data:
            self._mock_fallback_reason = None
            return "mock"
        if not live_available:
            self._mock_fallback_reason = (
                reason_when_unavailable or "live path unavailable"
            )
            logger.warning(
                "%s falling back to mock: %s",
                self.SOURCE_NAME, self._mock_fallback_reason,
            )
            return "mock"
        self._mock_fallback_reason = None
        return "live"

    # ------------------------------------------------------------------
    # Result framing
    # ------------------------------------------------------------------

    def _meta(self, mode: str, **extra: Any) -> dict[str, Any]:
        """
        Build the standard ``_meta`` block every collector attaches
        to its return payload.

        ``mode`` is ``"mock"`` or ``"live"``; if the collector wanted
        live but had to fall back, ``mode == "mock"`` and the meta
        carries ``fallback_reason``. Extra keyword args are merged in
        for collector-specific fields (``network``, ``api_endpoint``,
        ``cached: bool``, …).
        """
        meta: dict[str, Any] = {
            "source": self.SOURCE_NAME,
            "mode": mode,
            "fetched_at": time.time(),
        }
        if mode == "mock" and self._mock_fallback_reason:
            meta["fallback_reason"] = self._mock_fallback_reason
        meta.update(extra)
        return meta
