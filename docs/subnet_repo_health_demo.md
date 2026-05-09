# Walkthrough — SubnetRepoHealth external plug-in

This walks through the full lifecycle of a user-defined plug-in, end
to end. By the time you finish, you'll have:

1. Generated a fresh plug-in skeleton via Hygen
2. Customised it with real domain logic
3. Loaded it into the swarm via `TAO_PLUGIN_PATHS`
4. Watched it pull data from the orchestrator's context bus
5. Verified it can't bypass the safety gate

The example we follow ships in `examples/subnet_repo_health/` — a real,
runnable, tested plug-in you can copy as a starting point for
your own agent.

## 1. Generate a skeleton

From the `TAO_2.0` repo root:

```bash
npx hygen plugin new
# Asks:
#   Plug-in name (snake_case, no '_agent' suffix): subnet_repo_health
#   One-line description:                          Score subnet repo health from GitHub
#   Output directory:                              ~/subnet-repo-health
```

Result:

```
~/subnet-repo-health/
├── subnet_repo_health_agent.py
├── test_subnet_repo_health_agent.py
└── README.md
```

The scaffold is fully working — `python -m pytest ~/subnet-repo-health`
passes out of the box. You add the domain logic in `_execute()`.

## 2. Customise it

`examples/subnet_repo_health/subnet_repo_health_agent.py` is the
polished version of the scaffold. Compared to the raw Hygen output:

- `_execute()` is replaced with `_score_repo()` and `_verdict_for()` —
  the actual scoring logic (recency / adoption / engagement weights).
- A `_resolve_repo_url()` helper pulls the repo URL from the
  **context bus** (`self.context.get("subnet_discovery_agent")`)
  if available, falling back to a caller-supplied URL.
- A `_get_collector()` helper lazy-builds a `GitHubRepoCollector` (or
  uses an injected one for tests).
- `validate_input()` rejects non-int `subnet_id` and non-str
  `repo_url` (defence in depth).
- The return dict includes `repo_source` and `data_mode` so consumers
  can audit data provenance.

Read the file — it's ~280 LOC and shows every contract the swarm
expects from a plug-in.

## 3. Load it into the swarm

### Option A: env var (zero config)

```bash
export TAO_PLUGIN_PATHS=$(pwd)/examples/subnet_repo_health

# All swarm code paths now see the plug-in
python -m src.cli.tao_swarm capabilities
```

### Option B: programmatic

```python
from src.orchestrator import SwarmOrchestrator, load_plugins
from src.agents import SubnetDiscoveryAgent

orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
orch.register_agent(SubnetDiscoveryAgent({"use_mock_data": True}))

summary = load_plugins(orch, paths=["examples/subnet_repo_health"])
print(summary.as_dict())
# {"loaded": ["subnet_repo_health_agent"], "skipped": [], "errors": []}
```

## 4. Run it through the orchestrator

```python
# Populate context (the plug-in pulls from subnet_discovery_agent)
orch.context.publish("subnet_discovery_agent", {
    "subnets": [{
        "netuid": 1,
        "name": "Text Prompting",
        "repo_url": "https://github.com/opentensor/bittensor",
    }],
})

agent = orch.agents["subnet_repo_health_agent"]
out = agent.run({"type": "subnet_repo_health", "subnet_id": 1})

print(out)
# {
#   "status": "complete",
#   "task_type": "subnet_repo_health",
#   "subnet_id": 1,
#   "repo_url": "https://github.com/opentensor/bittensor",
#   "repo_full_name": "opentensor/bittensor",
#   "repo_health_score": 40.0,
#   "verdict": "STALE",
#   "score_components": {
#     "recency": 0.0, "adoption": 25.0, "engagement": 15.0,
#     "days_since_last_push": 707.0, "stars": 1100, "open_issues": 75,
#   },
#   "repo_archived": False,
#   "repo_stars": 1100,
#   "repo_open_issues": 75,
#   "repo_source": "subnet_discovery_agent",
#   "data_mode": "mock",
#   "timestamp": 1715050000.0,
# }
```

The `repo_source` field tells you the score used real subnet data
(`subnet_discovery_agent`) rather than a caller-supplied URL. The
`data_mode` field tells you whether GitHub was actually called
(`live`) or the deterministic fixture was used (`mock`). Both are
the context bus + collector working in concert.

## 5. Verify the safety guarantee

Plug-ins **cannot** bypass the ApprovalGate. Even with this plug-in
loaded, DANGER actions are still blocked at the gate before reaching
any agent code:

```python
out = orch.execute_task({"type": "execute_trade", "amount": 100})
print(out["status"], out["classification"])
# blocked DANGER
```

The regression test
`tests/test_subnet_repo_health_demo.py::test_danger_actions_still_blocked_with_plugin_loaded`
locks this in. The plug-in's `run()` is **never called** for this
task — the gate stops it at the front door.

## 6. Distribute it

Two paths to your friends / coworkers:

### A. Drop-in zip
Zip `examples/subnet_repo_health/` (or your real plug-in dir), share,
the recipient does:

```bash
unzip subnet_repo_health.zip -d ~/plugins
export TAO_PLUGIN_PATHS=~/plugins/subnet_repo_health
```

### B. PyPI / pip-installable

In your plug-in's `pyproject.toml`:

```toml
[project]
name = "tao-subnet-repo-health"
version = "1.0.0"

[project.entry-points."tao.agents"]
subnet_repo_health = "subnet_repo_health_agent:SubnetRepoHealthAgent"
```

```bash
pip install tao-subnet-repo-health
```

Then in the swarm:

```python
load_plugins(orch, entry_point_group="tao.agents")
```

Both paths discover and validate the plug-in via the **same**
`load_plugins` code path. The contract checks (`AGENT_NAME` /
`AGENT_VERSION` / required methods) and the safety injections
(context bus, agent-lock, gate) happen identically.

## What's tested

The repo carries a full regression suite for the demo:

```
tests/test_subnet_repo_health_demo.py
  ├ test_plugin_directory_exists
  ├ test_load_plugins_picks_up_subnet_repo_health
  ├ test_loaded_plugin_satisfies_spec_md_contract
  ├ test_loaded_plugin_received_context_injection
  ├ test_repo_health_with_direct_repo_url
  ├ test_repo_health_no_repo_returns_no_repo_verdict
  ├ test_repo_health_pulls_repo_url_from_subnet_discovery_context
  ├ test_repo_health_archived_repo_collapses_to_zero
  ├ test_validate_input_rejects_bad_subnet_id
  ├ test_validate_input_rejects_missing_type
  ├ test_danger_actions_still_blocked_with_plugin_loaded
  └ test_run_call_count_increments
```

If any of these break in the future, the plug-in pipeline regressed.
That's the smoke test for the whole external-plug-in workflow.

## Next steps for your own plug-in

1. Run `npx hygen plugin new` outside this repo
2. Replace the `_execute` body with your real domain logic
3. (Optional) Declare `AGENT_CAPABILITIES` for auto-routing
4. Write tests for the domain logic (use the scaffolded test as a
   starting point)
5. Either zip + share, or `pip install -e .` with `pyproject.toml`
   entry-points

The swarm doesn't change. Your plug-in is the swarm's plug-in.
