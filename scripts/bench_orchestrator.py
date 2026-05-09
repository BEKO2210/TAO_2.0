"""
Benchmark: SwarmOrchestrator end-to-end pipeline.

Three realistic workload personas drive the orchestrator so the
numbers reflect "what users actually do", not "what's easy to time
in a tight loop":

- ``researcher_session`` — discover subnets, score the top few,
  risk-review them, repeat for 5 candidates. The dominant flow.
- ``operator_setup`` — system_check → miner_setup → validator_setup
  → wallet_watch. What a user runs the first time they bring up a
  node. Hits the new context bus (PR #7, PR #12).
- ``watcher_loop`` — wallet_watch + market_analysis on a tight
  cadence. What a portfolio dashboard would do every minute.

Each persona is iterated 10× (the warm pass) to capture cache
behaviour without microbenchmark inflation. The cold pass times
the very first run from a fresh orchestrator.

Also benchmarks the gate-blocked DANGER path and the bare
``execute_task`` overhead so we can attribute regressions later.

Usage:
    python -m scripts.bench_orchestrator
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._bench import Benchmark, dump_results, format_results_path, print_table  # noqa: E402

logging.disable(logging.CRITICAL)

from src.orchestrator import SwarmOrchestrator  # noqa: E402
from src.agents import (  # noqa: E402
    SystemCheckAgent, ProtocolResearchAgent, SubnetDiscoveryAgent,
    SubnetScoringAgent, WalletWatchAgent, MarketTradeAgent,
    RiskSecurityAgent, MinerEngineeringAgent, ValidatorEngineeringAgent,
    InfraDevopsAgent, DashboardDesignAgent, FullstackDevAgent,
    QATestAgent, DocumentationAgent,
)


def _build_orchestrator() -> SwarmOrchestrator:
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    for agent_cls in (
        SystemCheckAgent, ProtocolResearchAgent, SubnetDiscoveryAgent,
        SubnetScoringAgent, WalletWatchAgent, MarketTradeAgent,
        RiskSecurityAgent, MinerEngineeringAgent, ValidatorEngineeringAgent,
        InfraDevopsAgent, DashboardDesignAgent, FullstackDevAgent,
        QATestAgent, DocumentationAgent,
    ):
        orch.register_agent(agent_cls({"use_mock_data": True}))
    return orch


# Workload personas. Each is a list of tasks representing one
# "session" — a researcher / operator / watcher loop iteration.

def researcher_session(seed: int = 0) -> list[dict]:
    """Discover subnets, score 5 candidates, risk-review each, then
    look at market context. Mirrors the e2e pipeline simulation."""
    candidate_ids = [(seed * 5 + i) % 50 + 1 for i in range(5)]
    tasks: list[dict] = [{"type": "subnet_discovery"}]
    for nid in candidate_ids:
        tasks.append({"type": "subnet_scoring", "subnet_id": nid})
        tasks.append({"params": {"target": "general",
                                 "content": f"subnet {nid} review"}})
    tasks.append({"type": "market_analysis", "params": {"pair": "TAO/USD"}})
    return tasks


def operator_setup(seed: int = 0) -> list[dict]:
    """First-time node setup. Touches the context bus: miner /
    validator agents pull system_check.hardware_report."""
    return [
        {"type": "system_check"},
        {"type": "miner_setup", "subnet_id": (seed % 20) + 1},
        {"type": "validator_setup", "subnet_id": (seed % 20) + 1},
        {"type": "wallet_watch",
         "address": "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"},
    ]


def watcher_loop(seed: int = 0) -> list[dict]:
    """Tight portfolio-dashboard loop."""
    return [
        {"type": "wallet_watch",
         "address": "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"},
        {"type": "market_analysis", "params": {"pair": "TAO/USD"}},
    ]


# DANGER tasks the gate must block before routing.
DANGER_TASKS: list[dict] = [
    {"type": "execute_trade", "amount": 100},
    {"type": "sign_transaction", "tx": "0xabc"},
    {"type": "stake_tao", "amount": 50},
]


def _time_persona(name: str, persona, sessions: int) -> tuple[Benchmark, Benchmark]:
    """Time one cold + ``sessions`` warm runs of a persona."""
    orch = _build_orchestrator()
    first_session = persona(seed=0)

    # cold: very first session through a fresh orchestrator
    with Benchmark(f"{name}::cold", iterations=len(first_session)) as cold:
        t0 = time.perf_counter()
        for task in first_session:
            orch.execute_task(task)
        cold.record(time.perf_counter() - t0)
    cold.metadata["session_size"] = len(first_session)

    # warm: same orchestrator, varied seeds → realistic cache mix
    total_tasks = 0
    with Benchmark(f"{name}::warm_per_task",
                   iterations=sessions * len(persona(seed=0))) as warm:
        for s in range(1, sessions + 1):
            for task in persona(seed=s):
                t0 = time.perf_counter()
                orch.execute_task(task)
                warm.record(time.perf_counter() - t0)
                total_tasks += 1
    warm.metadata["sessions"] = sessions
    return cold, warm


def main() -> None:
    benchmarks: list[Benchmark] = []

    # ---- bench: three realistic workload personas ------------------
    for name, persona, sessions in (
        ("researcher", researcher_session, 10),
        ("operator", operator_setup, 10),
        ("watcher", watcher_loop, 60),  # watcher is a tight loop, more samples
    ):
        cold, warm = _time_persona(name, persona, sessions)
        benchmarks.append(cold)
        benchmarks.append(warm)

    # ---- bench: DANGER tasks blocked at the gate -------------------
    orch = _build_orchestrator()
    with Benchmark("danger_blocked_per_task", iterations=2_000) as b:
        for i in range(b.iterations):
            t0 = time.perf_counter()
            orch.execute_task(DANGER_TASKS[i % len(DANGER_TASKS)])
            b.record(time.perf_counter() - t0)
    benchmarks.append(b)

    # ---- bench: agent registration overhead ------------------------
    with Benchmark("orchestrator_setup_14_agents", iterations=50) as b:
        for _ in range(b.iterations):
            t0 = time.perf_counter()
            _build_orchestrator()
            b.record(time.perf_counter() - t0)
    benchmarks.append(b)

    # ---- bench: sequential vs parallel run ------------------------
    # 30 mixed tasks across multiple agents. Parallel speedup will
    # be modest because the workloads are tiny (Python GIL bites),
    # but the bench locks the comparison in for future regressions.
    mixed_tasks: list[dict] = []
    for s in range(6):
        mixed_tasks.extend(researcher_session(seed=s))

    orch = _build_orchestrator()
    orch.execute_run({"tasks": mixed_tasks[:5]})  # warm-up

    with Benchmark("execute_run_sequential",
                   iterations=len(mixed_tasks)) as b_seq:
        t0 = time.perf_counter()
        orch.execute_run({"tasks": mixed_tasks})
        b_seq.record(time.perf_counter() - t0)
    b_seq.metadata["task_count"] = len(mixed_tasks)
    benchmarks.append(b_seq)

    orch = _build_orchestrator()
    orch.execute_run({"tasks": mixed_tasks[:5]})  # warm-up
    with Benchmark("execute_run_parallel_4",
                   iterations=len(mixed_tasks)) as b_par:
        t0 = time.perf_counter()
        orch.execute_run({"tasks": mixed_tasks}, parallel=True, max_workers=4)
        b_par.record(time.perf_counter() - t0)
    b_par.metadata["task_count"] = len(mixed_tasks)
    b_par.metadata["max_workers"] = 4
    benchmarks.append(b_par)

    # ---- bench: bare execute_task overhead -------------------------
    # Use a cheap agent (protocol_research is pure-Python, no subprocess
    # or SQLite writes) so we measure orchestrator framing cost rather
    # than agent work. This is the floor for any orchestrator-side
    # optimisation: the gate, router, and context publish all run here.
    orch = _build_orchestrator()
    cheap_task = {"type": "protocol_research", "topic": "yuma_consensus"}
    orch.execute_task(cheap_task)  # warm-up
    with Benchmark("execute_task_orchestrator_overhead", iterations=2_000) as b:
        for _ in range(b.iterations):
            t0 = time.perf_counter()
            orch.execute_task(cheap_task)
            b.record(time.perf_counter() - t0)
    b.metadata["agent_used"] = "protocol_research (cheap)"
    benchmarks.append(b)

    print_table(benchmarks, title="Orchestrator end-to-end (workload personas)")
    out_path = dump_results(benchmarks, category="orchestrator")
    print()
    print(f"  results: {format_results_path(out_path)}")


if __name__ == "__main__":
    main()
