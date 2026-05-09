"""
Tests for ``SwarmOrchestrator.execute_run(parallel=True)``.

Parallel execution is opt-in (``parallel=False`` is the default), so
existing callers see no behaviour change. The contract for the parallel
path:

1. Results are returned in **input order**, regardless of completion order.
2. The ApprovalGate runs **before** any agent is touched, so DANGER
   tasks are blocked even when they're scheduled concurrently.
3. ``run_log`` is mutation-safe — concurrent ``_log_event`` writes do
   not lose or interleave events.
4. Calls into the **same** agent serialise via per-agent locks; calls
   into **different** agents run concurrently.
5. Per-task results are identical to those produced by sequential
   execution.

These tests pin all five down. They use the GIL-friendly thread pool
(no actual CPU parallelism), so the bar isn't speed but correctness.
"""

from __future__ import annotations

import threading
import time

import pytest

from src.orchestrator import SwarmOrchestrator
from src.agents import (
    SystemCheckAgent,
    ProtocolResearchAgent,
    SubnetDiscoveryAgent,
    SubnetScoringAgent,
    MarketTradeAgent,
    RiskSecurityAgent,
)


def _build_orch() -> SwarmOrchestrator:
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    for cls in (
        SystemCheckAgent, ProtocolResearchAgent, SubnetDiscoveryAgent,
        SubnetScoringAgent, MarketTradeAgent, RiskSecurityAgent,
    ):
        orch.register_agent(cls({"use_mock_data": True}))
    return orch


def _mixed_tasks(n: int = 10) -> list[dict]:
    """A reproducible spread of tasks across multiple agents. Every
    task carries a ``type`` field so the orchestrator's input
    validator doesn't short-circuit them — keeps the per-task event
    counting tests honest."""
    types = [
        ("protocol_research", lambda i: {"type": "protocol_research"}),
        ("subnet_discovery",  lambda i: {"type": "subnet_discovery"}),
        ("subnet_scoring",    lambda i: {"type": "subnet_scoring", "subnet_id": (i % 50) + 1}),
        ("market_analysis",   lambda i: {"type": "market_analysis", "params": {"pair": "TAO/USD"}}),
        ("risk_review",       lambda i: {"type": "risk_review",
                                          "params": {"target": "general", "content": f"r{i}"}}),
    ]
    return [types[i % len(types)][1](i) for i in range(n)]


# ---------------------------------------------------------------------------
# Default behaviour: parallel=False is sequential (no regression)
# ---------------------------------------------------------------------------

def test_execute_run_default_is_sequential():
    orch = _build_orch()
    tasks = _mixed_tasks(5)
    out = orch.execute_run({"tasks": tasks})
    assert out["status"] == "complete"
    assert len(out["results"]) == 5
    # No parallel field on a sequential run? Either acceptable —
    # the run_start log event records it.
    starts = [e for e in orch.run_log if e.get("event_type") == "run_start"]
    assert any(e.get("parallel") is False for e in starts)


# ---------------------------------------------------------------------------
# Result ordering must match input order
# ---------------------------------------------------------------------------

def test_parallel_preserves_task_order():
    orch = _build_orch()
    tasks = _mixed_tasks(20)
    out = orch.execute_run({"tasks": tasks}, parallel=True, max_workers=8)
    assert len(out["results"]) == 20
    for inp, res in zip(tasks, out["results"]):
        # task_type may come from inp['type'] or default 'unknown' if
        # only params were given (risk_review case).
        expected = inp.get("type", "unknown")
        assert res["task_type"] == expected


def test_parallel_results_match_sequential_results():
    """Parallel execution must produce the same per-task statuses
    in the same order as sequential execution."""
    tasks = _mixed_tasks(10)

    seq_orch = _build_orch()
    seq_out = seq_orch.execute_run({"tasks": tasks})

    par_orch = _build_orch()
    par_out = par_orch.execute_run({"tasks": tasks}, parallel=True, max_workers=4)

    seq_statuses = [r["status"] for r in seq_out["results"]]
    par_statuses = [r["status"] for r in par_out["results"]]
    assert seq_statuses == par_statuses


# ---------------------------------------------------------------------------
# Safety: DANGER tasks blocked even in parallel mode
# ---------------------------------------------------------------------------

def test_danger_tasks_still_blocked_in_parallel():
    orch = _build_orch()
    tasks = [
        {"type": "protocol_research"},
        {"type": "execute_trade", "amount": 100},   # DANGER
        {"type": "subnet_discovery"},
        {"type": "sign_transaction", "tx": "0xabc"},  # DANGER
        {"type": "market_analysis", "params": {"pair": "TAO/USD"}},
    ]
    out = orch.execute_run({"tasks": tasks}, parallel=True, max_workers=4)
    # Order preserved: positions 1 and 3 should be blocked.
    assert out["results"][0]["status"] == "success"
    assert out["results"][1]["status"] == "blocked"
    assert out["results"][2]["status"] == "success"
    assert out["results"][3]["status"] == "blocked"
    assert out["results"][4]["status"] == "success"


# ---------------------------------------------------------------------------
# run_log: thread-safe concurrent appends
# ---------------------------------------------------------------------------

def test_run_log_no_lost_events_under_concurrency():
    """Each task generates several log events (start, complete). Under
    parallel execution, the count must still match what sequential
    would produce — no drops, no duplicates."""
    seq_orch = _build_orch()
    par_orch = _build_orch()
    tasks = _mixed_tasks(15)

    seq_orch.execute_run({"tasks": tasks})
    par_orch.execute_run({"tasks": tasks}, parallel=True, max_workers=4)

    # Extract just the per-task event types (drop run_start / run_complete
    # boilerplate that's identical in both modes).
    def per_task_events(orch):
        return sorted(
            e["event_type"] for e in orch.run_log
            if e.get("event_type") in ("task_start", "task_complete", "task_blocked")
        )
    assert per_task_events(seq_orch) == per_task_events(par_orch)


def test_run_log_event_count_matches_under_high_concurrency():
    """Hammer the run with 50 tasks across 16 workers and confirm we
    have exactly the expected number of task_start + task_complete
    events. A race on run_log.append would manifest as dropped events
    here."""
    orch = _build_orch()
    tasks = _mixed_tasks(50)
    orch.execute_run({"tasks": tasks}, parallel=True, max_workers=16)

    starts = sum(1 for e in orch.run_log if e.get("event_type") == "task_start")
    completes = sum(1 for e in orch.run_log if e.get("event_type") == "task_complete")
    assert starts == 50
    assert completes == 50


# ---------------------------------------------------------------------------
# Per-agent serialisation: same agent → no concurrent calls into run()
# ---------------------------------------------------------------------------

class _ProbeAgent:
    """Records concurrency on its run() — fails the test if more than
    one thread is inside ``run`` at any moment."""

    AGENT_NAME = "probe_agent"
    AGENT_VERSION = "1.0.0"

    def __init__(self, config=None) -> None:
        self.config = config or {}
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def run(self, task: dict) -> dict:
        with self._lock:
            self.in_flight += 1
            if self.in_flight > self.max_in_flight:
                self.max_in_flight = self.in_flight
        # Sleep without holding the probe lock so multiple threads
        # would actually overlap if the orchestrator's per-agent lock
        # weren't doing its job.
        time.sleep(0.005)
        with self._lock:
            self.in_flight -= 1
        return {"status": "complete", "task_type": task.get("type")}

    def get_status(self) -> dict:
        return {"agent": self.AGENT_NAME, "state": "idle"}

    def validate_input(self, task: dict) -> tuple[bool, str]:
        return True, ""


def test_same_agent_calls_are_serialised_under_parallel():
    """Even with parallel=True and high worker count, calls into the
    *same* agent must serialise — agents keep mutable state that
    would race otherwise."""
    orch = SwarmOrchestrator({"use_mock_data": True})
    probe = _ProbeAgent()
    orch.register_agent(probe)

    # Force the router to map our test task type to the probe agent.
    # The router's task→agent map is private; reach into it for the
    # test rather than expanding the public API just to test this.
    orch.task_router._task_map["probe_task"] = "probe_agent"

    # 20 tasks, all probe — should still see at most 1 concurrent call
    tasks = [{"type": "probe_task"} for _ in range(20)]
    orch.execute_run({"tasks": tasks}, parallel=True, max_workers=8)
    assert probe.max_in_flight == 1


# ---------------------------------------------------------------------------
# Empty plan + max_workers edge cases
# ---------------------------------------------------------------------------

def test_empty_plan_short_circuits_with_error():
    orch = _build_orch()
    out = orch.execute_run({"tasks": []}, parallel=True)
    assert out["status"] == "error"
    assert "no tasks" in out["error"].lower()


def test_max_workers_clamped_to_task_count():
    """A task_count < max_workers shouldn't spawn idle workers —
    not a correctness bug, but a smell. We just check the run
    completes without hanging."""
    orch = _build_orch()
    tasks = _mixed_tasks(2)
    out = orch.execute_run({"tasks": tasks}, parallel=True, max_workers=32)
    assert len(out["results"]) == 2
