---
to: <%= out_dir %>/<%= h.snake(name) %>_agent.py
---
"""
<%= h.pascal(name) %> — TAO Swarm plug-in.

<%= role %>

Drop this file into a directory referenced by ``TAO_PLUGIN_PATHS``
or pass that directory to ``load_plugins(orch, paths=[...])``. The
swarm validates the SPEC.md agent contract on load:

- Module-level ``AGENT_NAME`` and ``AGENT_VERSION`` constants
- A class with ``run(task) -> dict``, ``get_status() -> dict``,
  and ``validate_input(task) -> tuple[bool, str]``

SAFETY: this plug-in receives the swarm's ``AgentContext`` via
``self.context`` and runs through the same ``ApprovalGate`` as
built-in agents. It MUST NOT request seeds / private keys, MUST
NOT auto-sign, and MUST NOT auto-trade — DANGER actions are
blocked at the gate before reaching this code.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "<%= h.snake(name) %>_agent"
AGENT_VERSION: str = "0.1.0"


class <%= h.pascal(name) %>Agent:
    """<%= role %>"""

    def __init__(self, config: dict | None = None) -> None:
        self.config: dict = config or {}
        self._status: str = "idle"
        self._last_run: float | None = None
        self._calls: int = 0
        # ``self.context`` is populated by the orchestrator at register
        # time. Pull from it via dotted-path lookup, e.g.
        # ``self.context.get("system_check_agent.hardware_report")``.
        self.context: Any = None
        logger.info("%s plug-in initialized", AGENT_NAME)

    def run(self, task: dict) -> dict:
        ok, reason = self.validate_input(task)
        if not ok:
            return {"status": "error", "reason": reason,
                    "task_type": task.get("type")}
        self._status = "running"
        self._last_run = time.time()
        self._calls += 1
        try:
            report = self._execute(task)
            self._status = "complete"
            return {
                "status": "complete",
                "task_type": task.get("type"),
                "timestamp": time.time(),
                **report,
            }
        except Exception as exc:  # noqa: BLE001 — surface to orchestrator
            self._status = "error"
            logger.exception("%s failed: %s", AGENT_NAME, exc)
            return {
                "status": "error",
                "reason": str(exc),
                "task_type": task.get("type"),
            }

    def get_status(self) -> dict:
        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "state": self._status,
            "last_run": self._last_run,
            "calls": self._calls,
        }

    def validate_input(self, task: dict) -> tuple[bool, str]:
        if not isinstance(task, dict):
            return False, "task must be a dict"
        if "type" not in task:
            return False, "task.type is required"
        return True, ""

    def _execute(self, task: dict) -> dict[str, Any]:
        # TODO: implement <%= h.snake(name) %> logic. Return a flat
        # dict — the framing wrapper in run() merges status / timestamp.
        return {"message": f"{AGENT_NAME} executed",
                "task_type": task.get("type")}
