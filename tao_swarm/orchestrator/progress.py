"""
Progress reporting / heartbeat channel for long-running agents.

LLM-free analogue of Temporal heartbeats: agents that loop over many
items (subnet sweeps, repo scans, multi-call live collectors) can
periodically call ``self.report_progress(pct, message)`` to:

- Tell the orchestrator "I'm still alive" (used for stale-task
  detection — paired with the cancel token from PR D, this is the
  cooperative "is it stuck?" signal).
- Surface human-readable progress in the run log so the CLI / dashboard
  can render it.

The mechanism is opt-in: agents that don't call it lose nothing, and
agents that DO call it are not coupled to the orchestrator (they call
through ``self.report_progress`` which the orchestrator injects on
``register_agent``).

Contract:

    self.report_progress(
        percent=27.5,                         # 0..100, may be None
        message="scoring subnet 14 of 51",    # short, human-readable
    )

The orchestrator stamps each call into ``run_log`` with
``event_type="progress"``, ``agent_name``, ``percent``, ``message``,
``timestamp``. ``last_progress_at`` is also tracked per agent for
stale-task detection.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


# ProgressReporter signature: percent + optional message + optional
# free-form fields the agent wants to attach.
ProgressReporter = Callable[..., None]


class _OrchestratorProgressChannel:
    """
    Internal: per-orchestrator progress sink that writes through the
    log lock and tracks last-heartbeat timestamps.
    """

    def __init__(self, log_event: Callable[..., None]) -> None:
        self._log_event = log_event
        self._lock = threading.Lock()
        self._last_progress: dict[str, float] = {}

    def report(
        self,
        agent_name: str,
        percent: float | None = None,
        message: str = "",
        **extra: Any,
    ) -> None:
        """Record a progress / heartbeat event for ``agent_name``."""
        if percent is not None:
            try:
                percent = float(percent)
            except (TypeError, ValueError):
                percent = None
            else:
                if percent < 0:
                    percent = 0.0
                elif percent > 100:
                    percent = 100.0

        with self._lock:
            self._last_progress[agent_name] = time.time()

        self._log_event(
            event_type="progress",
            agent_name=agent_name,
            percent=percent,
            message=str(message)[:500] if message else "",
            **{k: v for k, v in extra.items() if isinstance(k, str)},
        )

    def last_progress_at(self, agent_name: str) -> float | None:
        """Last heartbeat timestamp for ``agent_name``, or None."""
        with self._lock:
            return self._last_progress.get(agent_name)

    def stale_agents(self, threshold_seconds: float) -> list[tuple[str, float]]:
        """
        Return ``(agent_name, age_seconds)`` for agents whose last
        progress event is older than ``threshold_seconds``.

        Useful for the dashboard / a future watchdog: paired with a
        cancel token, you can build "any agent silent for >N seconds
        gets cancelled" without touching the agents themselves.
        """
        now = time.time()
        with self._lock:
            return [
                (name, now - ts)
                for name, ts in self._last_progress.items()
                if (now - ts) > threshold_seconds
            ]

    def make_reporter_for(self, agent_name: str) -> ProgressReporter:
        """
        Build a per-agent reporter closure to inject onto
        ``agent.report_progress``. Each agent gets its own bound
        reporter so it can't accidentally report progress under
        someone else's name.
        """
        def _reporter(percent: float | None = None,
                      message: str = "",
                      **extra: Any) -> None:
            self.report(agent_name, percent=percent, message=message, **extra)

        return _reporter
