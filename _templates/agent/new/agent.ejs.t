---
to: src/agents/<%= h.snake(name) %>_agent.py
---
"""
<%= h.pascal(name) %> Agent.

<%= role %>

Implements the standard agent interface from SPEC.md:
- run(task) -> dict          # flat report with top-level "status"
- get_status(self) -> dict   # agent's running state, NOT the per-call status
- validate_input(task) -> tuple[bool, str]

STRICT RULES:
- NEVER request or store seeds / private keys
- NEVER auto-sign, auto-stake, or auto-trade
- All outputs are read-only or plan-only artifacts

Return-shape convention (matches the rest of src/agents/):
- ``run`` returns a flat dict with at least ``status`` (e.g. "complete",
  "error", "INSUFFICIENT_DATA") and any agent-specific report fields
  alongside it. Do **not** wrap the payload in a ``result`` key — the
  orchestrator already wraps the whole return value under ``output``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "<%= h.snake(name) %>_agent"
AGENT_VERSION: str = "1.0.0"


class <%= h.pascal(name) %>Agent:
    """<%= role %>"""

    def __init__(self, config: dict | None = None) -> None:
        self.config: dict = config or {}
        self._status: str = "idle"
        self._last_run: float | None = None
        logger.info("%s initialized", AGENT_NAME)

    def run(self, task: dict) -> dict:
        ok, reason = self.validate_input(task)
        if not ok:
            return {"status": "error", "reason": reason, "task_type": task.get("type")}

        self._status = "running"
        self._last_run = time.time()
        try:
            report = self._execute(task)
            self._status = "complete"
            return {
                "status": "complete",
                "task_type": task.get("type"),
                "timestamp": time.time(),
                **report,
            }
        except Exception as exc:  # noqa: BLE001 — surfaced to orchestrator
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
        }

    def validate_input(self, task: dict) -> tuple[bool, str]:
        if not isinstance(task, dict):
            return False, "task must be a dict"
        if "type" not in task:
            return False, "task.type is required"
        return True, ""

    def _execute(self, task: dict) -> dict[str, Any]:
        # TODO: implement agent-specific logic. Return a flat dict — the
        # framing wrapper in run() will merge it with status / timestamp.
        return {"message": f"{AGENT_NAME} executed"}
