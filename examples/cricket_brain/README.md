# CricketBrain — example external plug-in

A fully-working example of a user-defined plug-in for the
[TAO Swarm](https://github.com/BEKO2210/TAO_2.0). The domain (cricket
vibes) is silly — the point is the **plumbing**: how a Python file in
your own repo plugs into the swarm without any core-code changes.

## What's in this directory

```
examples/cricket_brain/
├── cricket_brain_agent.py     # The agent itself (~150 LOC)
└── README.md                  # This file
```

In your real plug-in repo you'd usually also have a `pyproject.toml`
and a `tests/` directory; both are optional for path-based loading.

## What it does

Counts cricket-themed tokens (`bat`, `wicket`, `pitch`, `over`,
`innings`, `bowl`, `spin`, `stump`, `yorker`, `googly`, `duck`,
`boundary`, `century`, `lbw`, `powerplay`) in a subnet's name +
description and returns a 0–100 "vibes" score with verdict:

| Score | Verdict |
|------:|---|
|  60+  | `STRONG_VIBES` |
|  30+  | `MIXED_VIBES` |
|   1+  | `WEAK_VIBES`   |
|   0   | `NO_VIBES`     |

It pulls subnet name/description from the orchestrator's
**`AgentContext` bus** if `subnet_discovery_agent` ran first, or
synthesises a placeholder if not. Either way, the result carries a
`context_source` field so you can tell where the input came from.

## Running it

### 1. Path-based discovery (drop a file, set an env var)

```bash
# From the TAO_2.0 repo root
export TAO_PLUGIN_PATHS=$(pwd)/examples/cricket_brain

python -m src.cli.tao_swarm capabilities
# → ... cricket_brain_agent listed under loaded plug-ins ...
```

### 2. Programmatic discovery

```python
from src.orchestrator import SwarmOrchestrator, load_plugins
from src.agents import SubnetDiscoveryAgent

orch = SwarmOrchestrator({"use_mock_data": True})
orch.register_agent(SubnetDiscoveryAgent({"use_mock_data": True}))
load_plugins(orch, paths=["examples/cricket_brain"])

# Run subnet_discovery first so the context bus has data
orch.execute_task({"type": "subnet_discovery"})

# Now invoke the plug-in
agent = orch.agents["cricket_brain_agent"]
out = agent.run({"type": "cricket_vibes", "subnet_id": 12})

print(out["vibes_score"], out["verdict"], out["matched_tokens"])
# → 0.0  NO_VIBES  []   (mock subnet 12 has no cricket words)

# Try with explicit text
out = agent.run({
    "type": "cricket_vibes",
    "text": "A pitch and bat scoring innings — over the boundary!",
})
print(out["vibes_score"], out["verdict"], out["matched_tokens"])
# → 30.0  MIXED_VIBES  ['bat', 'boundary', 'innings', 'over', 'pitch']
```

### 3. As a pip-installable package (for distribution)

In your own repo's `pyproject.toml`:

```toml
[project.entry-points."tao.agents"]
cricket_brain = "cricket_brain_agent:CricketBrainAgent"
```

Then `pip install -e .` and `load_plugins(orch, entry_point_group="tao.agents")`.

## Safety contract

CricketBrain is loaded as a regular agent and runs through the **same
`ApprovalGate`** as built-ins. It cannot bypass any DANGER classification.

The plug-in:
- has no network access
- never reads or writes private keys / seeds
- never executes a transaction
- only reads from `self.context` (pull-only) and the supplied task dict

A regression test in the swarm
(`tests/test_plugin_loader.py::test_plugin_does_not_get_special_classification_treatment`)
ensures DANGER actions are still blocked even when CricketBrain-style
plug-ins are registered.

## Use this as a starting point

For your own plug-in:

```bash
npx hygen plugin new
# Asks: name, role, output dir
# Generates: <dir>/<name>_agent.py + test + README
```

The Hygen scaffold is the same shape as `cricket_brain_agent.py`
(minus the cricket-vibes domain logic). Replace `_score_vibes` with
your real domain code and you're set.
