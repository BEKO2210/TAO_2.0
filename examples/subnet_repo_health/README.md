# SubnetRepoHealth — example external plug-in

A working example of a user-defined plug-in for the
[TAO Swarm](https://github.com/BEKO2210/TAO_2.0). Scores the health
of a Bittensor subnet's source repository using real GitHub metadata.
The plug-in lives **outside** `src/` — exactly the position your own
plug-in (in your repo or as a pip-installable package) would be in.

## What's in this directory

```
examples/subnet_repo_health/
├── subnet_repo_health_agent.py   # The agent itself (~280 LOC)
└── README.md                     # This file
```

In your real plug-in repo you'd usually also have a `pyproject.toml`
and a `tests/` directory; both are optional for path-based loading.

## What it does

For a Bittensor subnet (passed by `subnet_id` or directly by
`repo_url`), it pulls live metadata from GitHub (or a deterministic
mock fixture in offline mode) and computes a 0–100
`repo_health_score`:

| Component   | Max points | Signal                                |
|-------------|-----------:|---------------------------------------|
| Recency     |         60 | Days since last `pushed_at` (decays linearly 14–365 days) |
| Adoption    |         25 | `log10(stars + 1)` capped at log10(1000) |
| Engagement  |         15 | `open_issues > 0` (active triage) vs none |

Verdict ladder:

| Score   | Verdict       |
|--------:|---------------|
|     80+ | `HEALTHY`     |
|     50+ | `MAINTAINED`  |
|     20+ | `STALE`       |
|     >0  | `DORMANT`     |
|       0 | `ABANDONED` (archived) |

If a subnet's repo hasn't been pushed in 18 months, this surfaces it.
If the repo is archived, the verdict is `ABANDONED` regardless of star
count — a hard signal that the subnet's code is unmaintained.

The agent reads `repo_url` from the orchestrator's
**`AgentContext` bus** if `subnet_discovery_agent` ran first, or from
`task['repo_url']` if the caller supplies it directly. The output
carries a `repo_source` field so consumers can audit data provenance.

## Running it

### 1. Path-based discovery (drop a file, set an env var)

```bash
# From the TAO_2.0 repo root
export TAO_PLUGIN_PATHS=$(pwd)/examples/subnet_repo_health

python -m src.cli.tao_swarm capabilities
# → ... subnet_repo_health_agent listed under loaded plug-ins ...
```

### 2. Programmatic discovery

```python
from src.orchestrator import SwarmOrchestrator, load_plugins
from src.agents import SubnetDiscoveryAgent

orch = SwarmOrchestrator({"use_mock_data": True})
orch.register_agent(SubnetDiscoveryAgent({"use_mock_data": True}))
load_plugins(orch, paths=["examples/subnet_repo_health"])

# Run subnet_discovery first so the context bus has data
orch.execute_task({"type": "subnet_discovery"})

# Now invoke the plug-in
agent = orch.agents["subnet_repo_health_agent"]
out = agent.run({"type": "subnet_repo_health", "subnet_id": 1})

print(out["repo_health_score"], out["verdict"], out["score_components"])
# → 40.0 STALE  {'recency': 0.0, 'adoption': 25.0, 'engagement': 15.0,
#                'days_since_last_push': 707.0, 'stars': 1100, 'open_issues': 75}
```

### 3. As a pip-installable package (for distribution)

In your own repo's `pyproject.toml`:

```toml
[project.entry-points."tao.agents"]
subnet_repo_health = "subnet_repo_health_agent:SubnetRepoHealthAgent"
```

Then `pip install -e .` and
`load_plugins(orch, entry_point_group="tao.agents")`.

## Safety contract

This plug-in is loaded as a regular agent and runs through the **same
`ApprovalGate`** as built-ins. It cannot bypass any DANGER classification.

The plug-in:
- only reads from GitHub (read-only HTTP GET)
- never reads or writes private keys / seeds
- never executes a transaction
- only reads from `self.context` (pull-only) and the supplied task dict

A regression test in the swarm
(`tests/test_subnet_repo_health_demo.py::test_danger_actions_still_blocked_with_plugin_loaded`)
ensures DANGER actions are still blocked even when this plug-in is
registered.

## Use this as a starting point

For your own plug-in:

```bash
npx hygen plugin new
# Asks: name, role, output dir
# Generates: <dir>/<name>_agent.py + test + README
```

The Hygen scaffold is the same shape as `subnet_repo_health_agent.py`
(minus the repo-health domain logic). Replace the helpers with your
real domain code and you're set.
