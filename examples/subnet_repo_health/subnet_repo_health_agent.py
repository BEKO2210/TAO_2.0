"""
SubnetRepoHealthAgent — example external plug-in for the TAO Swarm.

A serious, real-domain plug-in that scores the health of a Bittensor
subnet's source repository. Unlike a built-in agent, this lives outside
``src/`` — exactly the position a user's plug-in (in their own repo or
a pip-installable package) would be in.

What it does
------------

Given a subnet (or a list of subnets discovered by
``subnet_discovery_agent``), it pulls each subnet's repo URL and
computes a 0-100 ``repo_health_score`` from real GitHub metadata:

- Recency:      days since last push (closer = better)
- Adoption:     star count (log-scaled — the curve flattens fast)
- Engagement:   open issues (some = active, many = backlog risk)
- Liveness:     archived → score collapses to 0 with verdict ABANDONED

The verdict ladder is:

| Score   | Verdict       |
|--------:|---------------|
|     80+ | HEALTHY       |
|     50+ | MAINTAINED    |
|     20+ | STALE         |
|      0+ | DORMANT       |
|       0 | ABANDONED     |

This is genuinely useful for a TAO researcher — a subnet whose repo
hasn't been pushed in 18 months is a yellow flag worth surfacing.

Demonstrates
------------

- The SPEC.md agent contract (``AGENT_NAME`` / ``AGENT_VERSION``
  module constants + ``run`` / ``get_status`` / ``validate_input``).
- Pulling state from the orchestrator's shared
  ``AgentContext`` — reads ``subnet_discovery_agent``'s output for
  the repo URL.
- Using a TAO Swarm collector (``GitHubRepoCollector``) — the same
  one a built-in agent uses. Plug-ins have no special privilege.
- Returning the swarm-conventional flat ``status`` + ``timestamp``
  dict shape so downstream consumers don't need a special path.
- Honouring ``use_mock_data=True`` — the collector returns the
  ``opentensor/bittensor`` fixture, which lets the test suite exercise
  the agent with no network.

Usage
-----

    export TAO_PLUGIN_PATHS=$(pwd)/examples/subnet_repo_health
    python -m src.cli.tao_swarm capabilities

…or programmatically::

    from src.orchestrator import SwarmOrchestrator, load_plugins
    orch = SwarmOrchestrator({"use_mock_data": True})
    load_plugins(orch, paths=["examples/subnet_repo_health"])

    out = orch.agents["subnet_repo_health_agent"].run({
        "type": "subnet_repo_health",
        "repo_url": "https://github.com/opentensor/bittensor",
    })

The plug-in routes through the same ``ApprovalGate`` as built-ins —
loading it does NOT raise its trust level. DANGER actions stay
blocked.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "subnet_repo_health_agent"
AGENT_VERSION: str = "1.0.0"


# Verdict cutoffs (inclusive lower bound).
_VERDICT_HEALTHY: float = 80.0
_VERDICT_MAINTAINED: float = 50.0
_VERDICT_STALE: float = 20.0


class SubnetRepoHealthAgent:
    """Score the health of a subnet's source repository."""

    def __init__(self, config: dict | None = None) -> None:
        """
        Args:
            config: Optional config dict. Recognised keys:
                - ``use_mock_data``: bool, forwarded to the collector
                - ``github_token``: optional GitHub PAT for higher rate limits
                - ``collector``: pre-built ``GitHubRepoCollector`` for tests
        """
        self.config: dict = config or {}
        self._status: str = "idle"
        self._calls: int = 0
        self._last_run: float | None = None
        # Filled by orchestrator at register time.
        self.context: Any = None
        # Allow injecting a collector for tests; otherwise lazy-build one.
        self._collector = self.config.get("collector")
        logger.info("%s initialized (use_mock_data=%s)",
                    AGENT_NAME, bool(self.config.get("use_mock_data", True)))

    # ---------------------------------------------------------------- public

    def run(self, task: dict) -> dict:
        ok, reason = self.validate_input(task)
        if not ok:
            return {
                "status": "error",
                "reason": reason,
                "agent_name": AGENT_NAME,
                "task_type": task.get("type"),
            }

        self._status = "running"
        self._calls += 1
        self._last_run = time.time()

        try:
            repo_url, repo_source = self._resolve_repo_url(task)
            if not repo_url:
                self._status = "complete"
                return {
                    "status": "complete",
                    "task_type": task.get("type"),
                    "subnet_id": task.get("subnet_id"),
                    "repo_url": None,
                    "repo_health_score": 0.0,
                    "verdict": "NO_REPO",
                    "reason_no_repo": (
                        "no repo_url in task and no subnet repo found "
                        "in context bus"
                    ),
                    "repo_source": repo_source,
                    "timestamp": time.time(),
                }

            collector = self._get_collector()
            info = collector.get_repo_info(repo_url)
            if "error" in info:
                self._status = "complete"
                return {
                    "status": "complete",
                    "task_type": task.get("type"),
                    "subnet_id": task.get("subnet_id"),
                    "repo_url": repo_url,
                    "repo_health_score": 0.0,
                    "verdict": "REPO_UNREACHABLE",
                    "collector_error": info.get("error"),
                    "repo_source": repo_source,
                    "timestamp": time.time(),
                }

            score, components = self._score_repo(info)
            verdict = self._verdict_for(info, score)
            self._status = "complete"

            return {
                "status": "complete",
                "task_type": task.get("type"),
                "subnet_id": task.get("subnet_id"),
                "repo_url": repo_url,
                "repo_full_name": info.get("full_name") or info.get("name"),
                "repo_health_score": round(score, 1),
                "verdict": verdict,
                "score_components": components,
                "repo_archived": bool(info.get("archived")),
                "repo_stars": int(info.get("stars", 0) or 0),
                "repo_open_issues": int(info.get("open_issues", 0) or 0),
                "repo_source": repo_source,
                "data_mode": (info.get("_meta") or {}).get("mode", "unknown"),
                "timestamp": time.time(),
            }

        except Exception as e:  # belt-and-braces — never escape to orchestrator
            self._status = "error"
            logger.exception("%s: scoring failed: %s", AGENT_NAME, e)
            return {
                "status": "error",
                "reason": str(e),
                "agent_name": AGENT_NAME,
                "task_type": task.get("type"),
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
        repo_url = task.get("repo_url")
        if repo_url is not None and not isinstance(repo_url, str):
            return False, "repo_url must be a str when provided"
        return True, ""

    # ---------------------------------------------------------------- helpers

    def _get_collector(self):
        """Lazy-build a GitHubRepoCollector unless one was injected."""
        if self._collector is not None:
            return self._collector
        from src.collectors.github_repos import GitHubRepoCollector

        coll_cfg = {
            "use_mock_data": self.config.get("use_mock_data", True),
        }
        if "github_token" in self.config:
            coll_cfg["github_token"] = self.config["github_token"]
        self._collector = GitHubRepoCollector(coll_cfg)
        return self._collector

    def _resolve_repo_url(self, task: dict) -> tuple[str | None, str]:
        """Resolve repo URL with priority:

        1. ``task['repo_url']`` (caller supplied)
        2. ``subnet_discovery_agent.subnets[netuid].repo_url`` from context
        """
        explicit = task.get("repo_url")
        if explicit:
            return str(explicit), "task"

        netuid = task.get("subnet_id")
        if netuid is None or self.context is None:
            return None, "missing"

        if not hasattr(self.context, "get"):
            return None, "missing"
        bundle = self.context.get("subnet_discovery_agent") or {}
        for row in (bundle.get("subnets") or []):
            if row.get("netuid") == netuid:
                url = row.get("repo_url") or ""
                if url:
                    return url, "subnet_discovery_agent"
                return None, "subnet_discovery_agent"
        return None, "missing"

    @staticmethod
    def _days_since_iso(iso_ts: str | None) -> float | None:
        """Days since an ISO-8601 timestamp; ``None`` if unparseable."""
        if not iso_ts:
            return None
        try:
            ts = iso_ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            return max(0.0, delta.total_seconds() / 86400.0)
        except (ValueError, TypeError):
            return None

    def _score_repo(self, info: dict) -> tuple[float, dict]:
        """0-100 score with a transparent breakdown.

        Components (each capped at its allotted points):
          - Recency  (60 pts max): full points if pushed within 14 days,
            decaying linearly to 0 at 365 days.
          - Adoption (25 pts max): log10(stars + 1) capped at log10(1000).
          - Engagement (15 pts max): open_issues > 0 → 15, == 0 → 5
            (no issues at all is a faint warning sign for an active project).

        An archived repo collapses the score to 0 regardless of recency.
        """
        if info.get("archived"):
            return 0.0, {
                "recency": 0.0,
                "adoption": 0.0,
                "engagement": 0.0,
                "archived_penalty": True,
            }

        # Recency: prefer pushed_at (last commit), fall back to updated_at.
        days = self._days_since_iso(info.get("pushed_at"))
        if days is None:
            days = self._days_since_iso(info.get("updated_at"))

        if days is None:
            recency = 30.0  # Unknown freshness → middle of the road.
        elif days <= 14:
            recency = 60.0
        elif days >= 365:
            recency = 0.0
        else:
            # Linear decay between 14 and 365 days.
            recency = 60.0 * (1.0 - (days - 14.0) / (365.0 - 14.0))

        stars = int(info.get("stars", 0) or 0)
        adoption_raw = math.log10(stars + 1) if stars >= 0 else 0.0
        adoption = min(25.0, adoption_raw * 25.0 / 3.0)  # 1000 stars → 25 pts

        open_issues = int(info.get("open_issues", 0) or 0)
        if open_issues == 0:
            engagement = 5.0
        elif open_issues >= 200:
            engagement = 10.0  # Backlog risk
        else:
            engagement = 15.0  # Active triage

        score = round(recency + adoption + engagement, 2)
        components = {
            "recency": round(recency, 2),
            "adoption": round(adoption, 2),
            "engagement": round(engagement, 2),
            "days_since_last_push": round(days, 1) if days is not None else None,
            "stars": stars,
            "open_issues": open_issues,
        }
        return score, components

    @staticmethod
    def _verdict_for(info: dict, score: float) -> str:
        if info.get("archived"):
            return "ABANDONED"
        if score >= _VERDICT_HEALTHY:
            return "HEALTHY"
        if score >= _VERDICT_MAINTAINED:
            return "MAINTAINED"
        if score >= _VERDICT_STALE:
            return "STALE"
        return "DORMANT"
