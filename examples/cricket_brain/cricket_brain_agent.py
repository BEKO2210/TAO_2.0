"""
CricketBrain — example external plug-in for the TAO Swarm.

This is a fully-working example of a user-defined plug-in that lives
**outside** the swarm core. The same file scaffolded by
``npx hygen plugin new`` would normally live in your own repo
(e.g. ``~/cricket-brain/cricket_brain_agent.py``); we keep it under
``examples/`` so anyone can study it and copy it.

What it does
------------

A toy "cricket vibes" scorer for Bittensor subnets. Given a subnet
name or repo description, it counts cricket-themed tokens (bat,
wicket, pitch, over, innings, …) and returns a 0-100 vibes score.
The domain is silly on purpose — the point is the plumbing, not the
analysis.

Demonstrates
------------

- The SPEC.md agent contract (``AGENT_NAME`` / ``AGENT_VERSION``
  module constants + ``run`` / ``get_status`` / ``validate_input``).
- Pulling state from the orchestrator's shared
  ``AgentContext`` — CricketBrain reads ``subnet_discovery_agent``'s
  output if available so it can score by name, not just by id.
- Logging a heartbeat via the logger (no orchestrator dependency).
- Returning the swarm-conventional ``status`` + ``timestamp`` flat
  dict shape so downstream consumers don't need a special path.

Usage
-----

    export TAO_PLUGIN_PATHS=$(pwd)/examples/cricket_brain
    python -m src.cli.tao_swarm capabilities

…or programmatically::

    from src.orchestrator import SwarmOrchestrator, load_plugins
    orch = SwarmOrchestrator({"use_mock_data": True})
    load_plugins(orch, paths=["examples/cricket_brain"])

    out = orch.execute_task({
        "type": "cricket_vibes",
        "subnet_id": 12,
        "agent": "cricket_brain_agent",
    })

The ``agent`` hint is needed because the demo doesn't pre-register
the ``cricket_vibes`` task type in ``_DEFAULT_TASK_MAP`` — that's
intentional: shows how a plug-in plays nicely with the existing
router without modifying core code. (When PR #22 lands and adds
``AGENT_CAPABILITIES``, the plug-in can declare its task types and
auto-register.)
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "cricket_brain_agent"
AGENT_VERSION: str = "0.1.0"


# Cricket-themed tokens used for the vibes score. Lower-case so we
# can do a case-insensitive substring sweep without per-token regex.
_CRICKET_TOKENS: tuple[str, ...] = (
    "cricket", "bat", "wicket", "pitch", "over", "innings", "bowl",
    "spin", "stump", "yorker", "googly", "duck", "boundary",
    "century", "lbw", "powerplay",
)


class CricketBrainAgent:
    """Score a subnet's cricket-themed vibes."""

    def __init__(self, config: dict | None = None) -> None:
        self.config: dict = config or {}
        self._status: str = "idle"
        self._calls: int = 0
        self._last_run: float | None = None
        # Filled by orchestrator at register time.
        self.context: Any = None
        logger.info("%s initialized (cricket tokens=%d)",
                    AGENT_NAME, len(_CRICKET_TOKENS))

    def run(self, task: dict) -> dict:
        ok, reason = self.validate_input(task)
        if not ok:
            return {
                "status": "error",
                "reason": reason,
                "task_type": task.get("type"),
            }

        self._status = "running"
        self._calls += 1
        self._last_run = time.time()

        netuid = task.get("subnet_id")
        # Pull a candidate description from the context bus. The user
        # is expected to have run ``subnet_discovery_agent`` /
        # ``subnet_metadata_agent`` first, but we fall back to a
        # synthesised name if nothing is available.
        candidate_text = self._gather_candidate_text(netuid, task)

        score, hits = self._score_vibes(candidate_text)
        verdict = self._verdict_for(score)

        self._status = "complete"
        return {
            "status": "complete",
            "task_type": task.get("type"),
            "subnet_id": netuid,
            "vibes_score": score,
            "verdict": verdict,
            "matched_tokens": sorted(hits),
            "candidate_text_preview": candidate_text[:120],
            "context_source": (
                "subnet_discovery_agent"
                if self._has_context_data(netuid) else "synthesized"
            ),
            "timestamp": time.time(),
        }

    def get_status(self) -> dict:
        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "state": self._status,
            "calls": self._calls,
            "last_run": self._last_run,
        }

    def validate_input(self, task: dict) -> tuple[bool, str]:
        if not isinstance(task, dict):
            return False, "task must be a dict"
        if "type" not in task:
            return False, "task.type is required"
        netuid = task.get("subnet_id")
        if netuid is not None and not isinstance(netuid, int):
            return False, "subnet_id must be an int when provided"
        return True, ""

    # ----- helpers ----------------------------------------------------

    def _gather_candidate_text(self, netuid: int | None, task: dict) -> str:
        """
        Build the text that the vibes scorer sweeps over. Priority:

        1. ``task['text']`` (caller supplied text directly)
        2. ``subnet_discovery_agent.subnets[netuid].name + description``
           pulled from context
        3. Synthesised placeholder using the netuid

        Logs which path it took so a user can see the context bus
        actually flowing.
        """
        explicit = task.get("text")
        if explicit:
            return str(explicit)

        if netuid is not None and self._has_context_data(netuid):
            row = self._lookup_subnet_row(netuid)
            parts = [str(row.get("name", "")), str(row.get("description", ""))]
            text = " ".join(p for p in parts if p)
            logger.debug(
                "%s: scored from context for netuid=%s (%d chars)",
                AGENT_NAME, netuid, len(text),
            )
            return text

        synth = f"subnet_{netuid or 0} placeholder description"
        logger.debug(
            "%s: no context data — synthesising %r", AGENT_NAME, synth,
        )
        return synth

    def _lookup_subnet_row(self, netuid: int) -> dict:
        """Look up a single subnet row in the context bus, if present."""
        if self.context is None or not hasattr(self.context, "get"):
            return {}
        data = self.context.get("subnet_discovery_agent") or {}
        for row in data.get("subnets", []) or []:
            if row.get("netuid") == netuid:
                return row
        return {}

    def _has_context_data(self, netuid: int | None) -> bool:
        if netuid is None:
            return False
        return bool(self._lookup_subnet_row(netuid))

    @staticmethod
    def _score_vibes(text: str) -> tuple[float, set[str]]:
        """Return a 0..100 vibes score and the set of matched tokens.

        Each unique cricket token in the text contributes ~6 points,
        capped at 100. Punctuation-insensitive substring match is good
        enough for a demo — the production version (in your own repo,
        not ours!) would tokenise properly.
        """
        haystack = text.lower()
        hits: set[str] = {tok for tok in _CRICKET_TOKENS if tok in haystack}
        score = min(100.0, len(hits) * 6.0)
        return score, hits

    @staticmethod
    def _verdict_for(score: float) -> str:
        if score >= 60:
            return "STRONG_VIBES"
        if score >= 30:
            return "MIXED_VIBES"
        if score > 0:
            return "WEAK_VIBES"
        return "NO_VIBES"
