"""
Benchmark: per-agent task latency.

Three timing flavours per agent so consumers can tell the difference
between "how fast does this run in a hot loop with cache hits"
(misleading) and "how fast is a typical single call from the CLI or
orchestrator" (what users actually experience):

- ``cold``       — fresh agent instance, first ``run()`` call. Closest
                   to what the user sees on `tao-swarm <command>`.
- ``warm_same``  — same instance, same task input, repeated. Reflects
                   the cached / steady-state path. Inflated by SQLite
                   cache hits — useful only as a lower bound.
- ``warm_varied``— same instance, varying task input (different subnet
                   IDs, addresses, …). Reflects what an agent
                   processing a list of items actually pays per item.

Each iteration count is sized to the realistic burst length, not the
microbenchmark inflation that hides setup costs.

Usage:
    python -m scripts.bench_agents
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._bench import Benchmark, dump_results, format_results_path, print_table  # noqa: E402

logging.disable(logging.CRITICAL)

from tao_swarm.agents import (  # noqa: E402
    DashboardDesignAgent,
    DocumentationAgent,
    FullstackDevAgent,
    InfraDevopsAgent,
    MarketTradeAgent,
    MinerEngineeringAgent,
    ProtocolResearchAgent,
    QATestAgent,
    RiskSecurityAgent,
    SubnetDiscoveryAgent,
    SubnetScoringAgent,
    SystemCheckAgent,
    TrainingExperimentAgent,
    ValidatorEngineeringAgent,
    WalletWatchAgent,
)

# Realistic burst sizes (single CLI invocations, not microbenchmark loops).
WARM_REPEATS = 20

# Test addresses for wallet_watch warm_varied
_ADDRS = [
    "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy",
    "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
    "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
    "5DfhGyQdFobKM8NsWvEeAKk5EQQgYe9AydgJ7rMB6E1EqRzV",
    "5GoKvZWG5ZPYL1WUovuHW3zJBWBP5eT8CbqjdRY4Q6iMaDtZ",
]


def _vary(scenario: str, i: int) -> dict:
    """Return a slightly different task per iteration, so cache effects
    don't dominate the warm_varied numbers."""
    if scenario == "system_check":
        return {"type": "system_check"}
    if scenario == "protocol_research":
        topics = ["yuma_consensus", "subnets", "miners", "validators", "stake"]
        return {"type": "protocol_research", "topic": topics[i % len(topics)]}
    if scenario == "subnet_discovery":
        return {"type": "subnet_discovery"}
    if scenario == "subnet_scoring":
        return {"type": "subnet_scoring", "subnet_id": (i % 50) + 1}
    if scenario == "wallet_watch":
        return {"type": "wallet_watch", "address": _ADDRS[i % len(_ADDRS)]}
    if scenario == "market_analysis":
        return {"type": "market_analysis", "params": {"pair": "TAO/USD"}}
    if scenario == "risk_review":
        contents = [
            "read subnet metadata",
            "stake check for subnet 12",
            "wallet snapshot for cold address",
        ]
        return {"params": {"target": "general", "content": contents[i % len(contents)]}}
    if scenario == "miner_setup":
        return {"type": "miner_setup", "subnet_id": (i % 20) + 1}
    if scenario == "validator_setup":
        return {"type": "validator_setup", "subnet_id": (i % 20) + 1}
    if scenario == "training_plan":
        models = ["bert-base", "gpt2-small", "distilbert", "llama-7b"]
        return {"type": "training_plan",
                "params": {"action": "plan", "model_name": models[i % len(models)]}}
    if scenario == "infrastructure":
        return {"type": "infrastructure"}
    if scenario == "dashboard_design":
        return {"type": "dashboard_design"}
    if scenario == "development":
        return {"type": "development"}
    if scenario == "quality_assurance_lite":
        return {"params": {"action": "secret_check", "content": ""}}
    if scenario == "documentation":
        return {"type": "documentation"}
    raise ValueError(f"unknown scenario {scenario}")


SCENARIOS: list[tuple[type, str]] = [
    (SystemCheckAgent,           "system_check"),
    (ProtocolResearchAgent,      "protocol_research"),
    (SubnetDiscoveryAgent,       "subnet_discovery"),
    (SubnetScoringAgent,         "subnet_scoring"),
    (WalletWatchAgent,           "wallet_watch"),
    (MarketTradeAgent,           "market_analysis"),
    (RiskSecurityAgent,          "risk_review"),
    (MinerEngineeringAgent,      "miner_setup"),
    (ValidatorEngineeringAgent,  "validator_setup"),
    (TrainingExperimentAgent,    "training_plan"),
    (InfraDevopsAgent,           "infrastructure"),
    (DashboardDesignAgent,       "dashboard_design"),
    (FullstackDevAgent,          "development"),
    (QATestAgent,                "quality_assurance_lite"),
    (DocumentationAgent,         "documentation"),
]


def _bench_agent(agent_cls: type, name: str) -> tuple[Benchmark, Benchmark, Benchmark]:
    """Return (cold, warm_same, warm_varied) benchmarks."""
    # cold: instantiate + first run
    with Benchmark(f"{name}::cold", iterations=1) as cold:
        agent = agent_cls({"use_mock_data": True})
        t0 = time.perf_counter()
        agent.run(_vary(name, 0))
        cold.record(time.perf_counter() - t0)

    # warm_same: same input — best case (cache hits)
    same_task = _vary(name, 0)
    with Benchmark(f"{name}::warm_same", iterations=WARM_REPEATS) as warm_same:
        for _ in range(WARM_REPEATS):
            t0 = time.perf_counter()
            agent.run(same_task)
            warm_same.record(time.perf_counter() - t0)

    # warm_varied: realistic — different inputs each call
    with Benchmark(f"{name}::warm_varied", iterations=WARM_REPEATS) as warm_varied:
        for i in range(WARM_REPEATS):
            t0 = time.perf_counter()
            agent.run(_vary(name, i + 1))
            warm_varied.record(time.perf_counter() - t0)
    return cold, warm_same, warm_varied


def main() -> None:
    benchmarks: list[Benchmark] = []
    for cls, name in SCENARIOS:
        for b in _bench_agent(cls, name):
            benchmarks.append(b)

    print_table(benchmarks, title="Agent latency (mock mode, realistic burst sizes)")
    out_path = dump_results(benchmarks, category="agents")
    print()
    print(f"  results: {format_results_path(out_path)}")


if __name__ == "__main__":
    main()
