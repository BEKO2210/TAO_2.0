"""
Agent context bus for the TAO/Bittensor swarm.

A small, deliberately boring key-value store the ``SwarmOrchestrator``
hands to every registered agent. After each successful ``execute_task``,
the orchestrator publishes the agent's output under the agent's name
(``context["system_check_agent"] = {...}``). Any agent that wants prior
results can pull them with ``self.context.get(key)`` — no broadcasting,
no callbacks, no implicit dependencies in the agent classes themselves.

Design choices:

- **Pull, not push.** Agents that don't need context keep working unchanged.
- **Single namespace per agent.** Output is stored under the agent's
  ``AGENT_NAME``. Sub-keys (e.g. ``"system_check_agent.hardware_report"``)
  resolve via dotted lookup so callers can ask narrowly without copying
  whole reports around.
- **No mutation contract.** The store accepts dict values and hands them
  back as deep copies, so a downstream agent can't accidentally corrupt
  another agent's report.
- **Resettable.** ``reset()`` wipes the bus between independent runs;
  the orchestrator exposes this as ``reset_context()``.
"""

from __future__ import annotations

import copy
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


_MISSING: Any = object()


class AgentContext:
    """
    Thread-safe key-value store shared across agents in a single run.

    The orchestrator publishes each successful agent output under the
    agent's name. Agents pull what they need:

        report = self.context.get("system_check_agent")
        cpu = self.context.get("system_check_agent.hardware_report.cpu")
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._lock: threading.RLock = threading.RLock()

    # ---- writes ---------------------------------------------------------

    def publish(self, agent_name: str, output: Any) -> None:
        """Store ``output`` under ``agent_name``. Later writes overwrite."""
        with self._lock:
            self._store[agent_name] = copy.deepcopy(output)
            logger.debug("AgentContext: published key=%s", agent_name)

    def reset(self) -> None:
        """Drop everything. Use between independent runs."""
        with self._lock:
            self._store.clear()
            logger.debug("AgentContext: reset")

    # ---- reads ----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """
        Look up a value, optionally via dotted path.

        ``key`` may be ``"system_check_agent"`` (whole namespace) or
        ``"system_check_agent.hardware_report.cpu"`` (dotted lookup
        through nested dicts). Returns ``default`` for any missing
        segment so callers don't need exception handling for the
        common "not yet published" case.
        """
        with self._lock:
            parts = key.split(".")
            head, rest = parts[0], parts[1:]
            value = self._store.get(head, _MISSING)
            if value is _MISSING:
                return default
            for segment in rest:
                if not isinstance(value, dict):
                    return default
                value = value.get(segment, _MISSING)
                if value is _MISSING:
                    return default
            # Hand callers a deep copy so they can't mutate the bus.
            return copy.deepcopy(value)

    def has(self, key: str) -> bool:
        """Whether a dotted-path lookup would resolve to a non-default value."""
        return self.get(key, _MISSING) is not _MISSING

    def keys(self) -> list[str]:
        """Top-level keys currently in the store."""
        with self._lock:
            return list(self._store.keys())

    # ---- introspection --------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __contains__(self, key: str) -> bool:
        return self.has(key)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"AgentContext(keys={self.keys()})"
