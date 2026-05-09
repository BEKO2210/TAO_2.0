"""
Benchmark: ApprovalGate classification throughput.

The gate sits in front of every orchestrator task, so its per-call
cost multiplies through every realistic workload. The traffic mix
matters: a research session is dominated by SAFE reads (subnet
discovery, scoring, market analysis), CAUTION events are rare
(install_deps, connect_api), and DANGER attempts are the exception
not the rule (a user trying ``execute_trade`` to see it bounce).

Workloads modelled here:

- ``research_session_mix`` — 95% SAFE reads, 4% CAUTION (install /
  api connect), 1% DANGER probe. Mirrors the e2e simulation.
- ``operator_mix`` — 80% SAFE, 15% CAUTION, 5% DANGER. Models a
  user actively setting up a miner: more install/connect, more
  attempts at staking that get bounced.
- ``danger_only`` — adversarial baseline. What's the worst case
  if a misbehaving caller throws nothing but DANGER actions at us?

Each workload is sized so its `iterations` reflects a plausible
real burst (a few hundred to a few thousand calls) rather than the
half-million microbenchmark inflation that hides cache effects.

Usage:
    python -m scripts.bench_approval_gate
"""

from __future__ import annotations

import logging
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._bench import Benchmark, dump_results, format_results_path, print_table  # noqa: E402
from tao_swarm.orchestrator.approval_gate import ApprovalGate  # noqa: E402

logging.disable(logging.CRITICAL)


SAFE_ACTIONS: list[tuple[str, dict]] = [
    ("read", {"target": "subnet"}),
    ("analyze", {"data": "subnets"}),
    ("query", {"q": "stake"}),
    ("paper_trade", {"pair": "TAO/USD"}),
    ("wallet_watch_only", {"address": "5DAA..."}),
    ("subnet_discovery", {}),
    ("subnet_scoring", {"subnet_id": 12}),
    ("market_analysis", {"pair": "TAO/USD"}),
    ("system_check", {}),
    ("protocol_research", {"topic": "yuma_consensus"}),
]

CAUTION_ACTIONS: list[tuple[str, dict]] = [
    ("install_deps", {"pkg": "numpy"}),
    ("connect_api", {"host": "subscan.io"}),
    ("write_file", {"path": "report.md"}),
]

DANGER_ACTIONS: list[tuple[str, dict]] = [
    ("execute_trade", {"pair": "TAO/USD", "amount": 100}),
    ("sign_transaction", {"tx": "0xdeadbeef"}),
    ("stake", {"amount": 50}),
    ("unstake", {"amount": 50}),
    ("transfer", {"to": "5XYZ..."}),
    ("create_wallet", {}),
]


def _build_mix(safe_pct: float, caution_pct: float, danger_pct: float, n: int,
               seed: int = 0) -> list[tuple[str, dict]]:
    """Build a deterministic action stream of length ``n`` with the given
    SAFE / CAUTION / DANGER percentages. Deterministic so reruns of the
    benchmark compare apples-to-apples."""
    assert abs(safe_pct + caution_pct + danger_pct - 1.0) < 0.01
    rng = random.Random(seed)
    stream: list[tuple[str, dict]] = []
    for _ in range(n):
        r = rng.random()
        if r < safe_pct:
            pool = SAFE_ACTIONS
        elif r < safe_pct + caution_pct:
            pool = CAUTION_ACTIONS
        else:
            pool = DANGER_ACTIONS
        stream.append(rng.choice(pool))
    return stream


def main() -> None:
    gate = ApprovalGate()
    benchmarks: list[Benchmark] = []

    # ---- bench: research session mix (most realistic) ---------------
    research = _build_mix(0.95, 0.04, 0.01, n=2_000, seed=1)
    with Benchmark("research_session_95_4_1", iterations=len(research)) as b:
        for action, params in research:
            gate.classify_action(action, params)
    b.metadata["mix"] = "95% SAFE, 4% CAUTION, 1% DANGER"
    b.metadata["realism"] = "research_session"
    benchmarks.append(b)

    # ---- bench: operator mix ---------------------------------------
    operator = _build_mix(0.80, 0.15, 0.05, n=2_000, seed=2)
    with Benchmark("operator_setup_80_15_5", iterations=len(operator)) as b:
        for action, params in operator:
            gate.classify_action(action, params)
    b.metadata["mix"] = "80% SAFE, 15% CAUTION, 5% DANGER"
    b.metadata["realism"] = "operator_setup"
    benchmarks.append(b)

    # ---- bench: adversarial DANGER-only baseline -------------------
    with Benchmark("danger_only_adversarial", iterations=2_000) as b:
        for i in range(b.iterations):
            action, params = DANGER_ACTIONS[i % len(DANGER_ACTIONS)]
            gate.classify_action(action, params)
    b.metadata["mix"] = "100% DANGER"
    b.metadata["realism"] = "adversarial_worst_case"
    benchmarks.append(b)

    # ---- bench: can_execute on prefetched classifications ----------
    classifications = [
        gate.classify_action(a, p) for a, p in (SAFE_ACTIONS + DANGER_ACTIONS)
    ]
    with Benchmark("can_execute_check", iterations=10_000) as b:
        for i in range(b.iterations):
            gate.can_execute(classifications[i % len(classifications)])
    benchmarks.append(b)

    # ---- bench: validate_plan composite (medium plan) --------------
    plan = {"actions": [{"type": a, "params": p}
                        for a, p in (SAFE_ACTIONS[:5] + DANGER_ACTIONS[:2])]}
    with Benchmark("validate_plan_7_actions", iterations=2_000) as b:
        for _ in range(b.iterations):
            gate.validate_plan(plan)
    b.metadata["plan_size"] = len(plan["actions"])
    benchmarks.append(b)

    print_table(benchmarks, title="ApprovalGate throughput (realistic mixes)")
    out_path = dump_results(benchmarks, category="approval_gate")
    print()
    print(f"  results: {format_results_path(out_path)}")


if __name__ == "__main__":
    main()
