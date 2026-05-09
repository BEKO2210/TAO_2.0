# Walkthrough — CricketBrain external plug-in

This walks through the full lifecycle of a user-defined plug-in, end
to end. By the time you finish, you'll have:

1. Generated a fresh plug-in skeleton via Hygen
2. Customised it with real domain logic
3. Loaded it into the swarm via `TAO_PLUGIN_PATHS`
4. Watched it pull data from the orchestrator's context bus
5. Verified it can't bypass the safety gate

The example we follow ships in `examples/cricket_brain/` — a real,
runnable, tested plug-in you can copy as a starting point for
`MicroFish`, `OracleBot`, or whatever you actually want to build.

## 1. Generate a skeleton

From the `TAO_2.0` repo root:

```bash
npx hygen plugin new
# Asks:
#   Plug-in name (snake_case, no '_agent' suffix): cricket_brain
#   One-line description:                          Cricket-themed subnet-vibes scorer
#   Output directory:                              ~/cricket-brain
```

Result:

```
~/cricket-brain/
├── cricket_brain_agent.py
├── test_cricket_brain_agent.py
└── README.md
```

The scaffold is fully working — `python -m pytest ~/cricket-brain` passes
out of the box. You add the domain logic in `_execute()`.

## 2. Customise it

`examples/cricket_brain/cricket_brain_agent.py` is the polished
version of the scaffold. Compared to the raw Hygen output:

- `_execute()` is replaced with `_score_vibes()` and `_verdict_for()` —
  the actual scoring logic.
- A `_gather_candidate_text()` helper pulls subnet name/description
  from the **context bus** (`self.context.get("subnet_discovery_agent")`)
  if available, falling back to a synthesised placeholder.
- `validate_input()` rejects non-int `subnet_id`s (defence in depth).
- The return dict includes `context_source` so consumers can see
  whether the score was computed from real subnet data or a stub.

Read the file — it's ~150 LOC and shows every contract the swarm
expects from a plug-in.

## 3. Load it into the swarm

### Option A: env var (zero config)

```bash
export TAO_PLUGIN_PATHS=$(pwd)/examples/cricket_brain

# All swarm code paths now see the plug-in
python -m src.cli.tao_swarm capabilities       # (after PR #22 merges)
```

### Option B: programmatic

```python
from src.orchestrator import SwarmOrchestrator, load_plugins
from src.agents import SubnetDiscoveryAgent

orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
orch.register_agent(SubnetDiscoveryAgent({"use_mock_data": True}))

summary = load_plugins(orch, paths=["examples/cricket_brain"])
print(summary.as_dict())
# {"loaded": ["cricket_brain_agent"], "skipped": [], "errors": []}
```

## 4. Run it through the orchestrator

```python
# Populate context (CricketBrain pulls from subnet_discovery_agent)
orch.context.publish("subnet_discovery_agent", {
    "subnets": [{
        "netuid": 42,
        "name": "Wicket-Spin",
        "description": "Pitch innings boundary century powerplay yorker",
    }],
})

agent = orch.agents["cricket_brain_agent"]
out = agent.run({"type": "cricket_vibes", "subnet_id": 42})

print(out)
# {
#   "status": "complete",
#   "task_type": "cricket_vibes",
#   "subnet_id": 42,
#   "vibes_score": 48.0,
#   "verdict": "MIXED_VIBES",
#   "matched_tokens": ["boundary", "century", "innings", "pitch",
#                      "powerplay", "spin", "wicket", "yorker"],
#   "candidate_text_preview": "Wicket-Spin Pitch innings boundary century ...",
#   "context_source": "subnet_discovery_agent",
#   "timestamp": 1715050000.0,
# }
```

The `context_source` field tells you the score used real subnet data
(`subnet_discovery_agent`) rather than the synthetic fallback. That's
the context bus working.

## 5. Verify the safety guarantee

Plug-ins **cannot** bypass the ApprovalGate. Even with CricketBrain
loaded, DANGER actions are still blocked at the gate before reaching
any agent code:

```python
out = orch.execute_task({"type": "execute_trade", "amount": 100})
print(out["status"], out["classification"])
# blocked DANGER
```

The regression test
`tests/test_cricket_brain_demo.py::test_danger_actions_still_blocked_with_cricket_brain_loaded`
locks this in. CricketBrain's `run()` is **never called** for this
task — the gate stops it at the front door.

## 6. Distribute it

Two paths to your friends / coworkers:

### A. Drop-in zip
Zip `examples/cricket_brain/` (or your real plug-in dir), share, the
recipient does:

```bash
unzip cricket_brain.zip -d ~/plugins
export TAO_PLUGIN_PATHS=~/plugins/cricket_brain
```

### B. PyPI / pip-installable

In your plug-in's `pyproject.toml`:

```toml
[project]
name = "tao-cricket-brain"
version = "0.1.0"

[project.entry-points."tao.agents"]
cricket_brain = "cricket_brain_agent:CricketBrainAgent"
```

```bash
pip install tao-cricket-brain
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
tests/test_cricket_brain_demo.py
  ├ test_plugin_directory_exists
  ├ test_load_plugins_picks_up_cricket_brain
  ├ test_loaded_plugin_satisfies_spec_md_contract
  ├ test_loaded_plugin_received_context_injection
  ├ test_cricket_brain_no_vibes_for_synthetic_text
  ├ test_cricket_brain_strong_vibes_for_explicit_text
  ├ test_cricket_brain_picks_up_subnet_discovery_via_context
  ├ test_cricket_brain_validate_input_rejects_bad_subnet_id
  ├ test_danger_actions_still_blocked_with_cricket_brain_loaded
  └ test_cricket_brain_run_call_count_increments
```

If any of these break in the future, the plug-in pipeline regressed.
That's the smoke test for the whole external-plug-in workflow.

## Next steps for your own plug-in

1. Run `npx hygen plugin new` outside this repo
2. Replace the `_execute` / `_score_vibes` body with your real domain logic
3. (Optional) Declare `AGENT_CAPABILITIES` for auto-routing once
   PR #22 lands
4. Write tests for the domain logic (use the scaffolded test as a
   starting point)
5. Either zip + share, or `pip install -e .` with `pyproject.toml`
   entry-points

The swarm doesn't change. Your plug-in is the swarm's plug-in.
