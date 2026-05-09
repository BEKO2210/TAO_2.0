# Plug-in agents

The TAO swarm ships with 15 built-in agents. **Plug-ins** let you add your
own agents — like `MicroFish` or `CricketBrain` — without forking the
core repo. A plug-in is a single Python file (or installable package)
that follows the SPEC.md agent contract; the orchestrator discovers,
validates, and registers it at runtime.

## Two ways to ship a plug-in

### 1. Path-based (drop a `*_agent.py` file in a folder)

Cheapest. No packaging, no `pip install`. You write:

```
/home/user/my-agents/
└── micro_fish_agent.py
```

Tell the swarm where to look:

```bash
export TAO_PLUGIN_PATHS=/home/user/my-agents
```

…or pass the path explicitly:

```python
from src.orchestrator import SwarmOrchestrator, load_plugins

orch = SwarmOrchestrator({"use_mock_data": True})
summary = load_plugins(orch, paths=["/home/user/my-agents"])
print(summary.as_dict())
# → {"loaded": ["micro_fish_agent"], "skipped": [], "errors": []}
```

### 2. Entry-point based (production / pip-installable)

When your plug-in lives in a real repo and you want users to
`pip install` it. In your repo's `pyproject.toml`:

```toml
[project]
name = "my-tao-plugins"
version = "0.1.0"

[project.entry-points."tao.agents"]
micro_fish = "my_tao_plugins.micro_fish_agent:MicroFishAgent"
cricket_brain = "my_tao_plugins.cricket_brain_agent:CricketBrainAgent"
```

Then `pip install my-tao-plugins` and:

```python
load_plugins(orch, entry_point_group="tao.agents")
```

## The agent contract

A plug-in must expose:

- Module-level constants `AGENT_NAME` (snake_case string) and `AGENT_VERSION`
- A class implementing the SPEC.md trio:
  - `__init__(self, config: dict | None = None)`
  - `run(self, task: dict) -> dict`
  - `get_status(self) -> dict`
  - `validate_input(self, task: dict) -> tuple[bool, str]`

Plug-ins that don't match this contract are **skipped, not registered** —
the loader records the reason in its `PluginLoadSummary.skipped` list.

## Scaffolding via Hygen

```bash
npx hygen plugin new
# Asks for: plug-in name, one-line role, output dir
# Generates: <dir>/<name>_agent.py + test_<name>_agent.py + README.md
```

The scaffold includes a fully-shaped agent class, a passing test
file, and a README that documents both delivery modes (path-based
and entry-point).

## Conflict policy

When a plug-in's `AGENT_NAME` matches an already-registered agent:

```python
from src.orchestrator import (
    load_plugins,
    ON_CONFLICT_SKIP,      # default — keep existing, skip new
    ON_CONFLICT_REPLACE,   # newer wins
    ON_CONFLICT_ERROR,     # raise ValueError
)

load_plugins(orch, paths=[...], on_conflict=ON_CONFLICT_REPLACE)
```

## Safety: plug-ins go through the gate

Loading a plug-in **does not** raise its trust level. Every plug-in
runs through the same `ApprovalGate` as built-ins:

- DANGER task types (`execute_trade`, `sign_transaction`, `stake`,
  `schedule_coldkey_swap`, …) are blocked **before** reaching the
  plug-in's `run()`.
- The plug-in receives `self.context` from the orchestrator — same
  pull-based shared bus that built-ins use.
- The plug-in MUST NOT request seeds / private keys / mnemonics. Same
  rules as built-in agents.

A regression test (`tests/test_plugin_loader.py::
test_plugin_does_not_get_special_classification_treatment`) locks
this in: even with a plug-in registered for a DANGER task type, the
plug-in's `run()` is never called.

## Worked example: MicroFish

`/home/user/microfish/micro_fish_agent.py`:

```python
"""MicroFish — a tiny example plug-in that scores a subnet's
'fishiness' (toy metric for docs)."""

import time
from typing import Any

AGENT_NAME = "micro_fish_agent"
AGENT_VERSION = "0.1.0"


class MicroFishAgent:
    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self.context: Any = None  # filled by orchestrator
        self._calls = 0

    def run(self, task: dict) -> dict:
        ok, reason = self.validate_input(task)
        if not ok:
            return {"status": "error", "reason": reason}
        self._calls += 1
        netuid = task.get("subnet_id")

        # Pull system_check report from the shared context (PR #7 bus)
        ram_gb = 0
        if self.context is not None:
            ram_gb = self.context.get(
                "system_check_agent.hardware_report.ram.total_gb", default=0,
            )

        # Toy fishiness metric — not a real signal
        fishiness = (netuid or 0) * 7 % 100

        return {
            "status": "complete",
            "task_type": task.get("type"),
            "subnet_id": netuid,
            "fishiness_score": fishiness,
            "host_ram_gb": ram_gb,
            "timestamp": time.time(),
        }

    def get_status(self) -> dict:
        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "state": "idle",
            "calls": self._calls,
        }

    def validate_input(self, task: dict) -> tuple[bool, str]:
        if not isinstance(task, dict):
            return False, "task must be a dict"
        return True, ""
```

Loading & using:

```python
from src.orchestrator import SwarmOrchestrator, load_plugins
from src.agents import SystemCheckAgent

orch = SwarmOrchestrator({"use_mock_data": True})
orch.register_agent(SystemCheckAgent({"use_mock_data": True}))

# Load the plug-in
summary = load_plugins(orch, paths=["/home/user/microfish"])
print(summary.loaded)  # → ['micro_fish_agent']

# Populate context so MicroFish can read system_check.hardware_report
orch.execute_task({"type": "system_check"})

# Run the plug-in directly (the router doesn't know its task type yet)
fish = orch.agents["micro_fish_agent"]
print(fish.run({"type": "fish_check", "subnet_id": 12}))
```

## Listing what got loaded

```python
summary = load_plugins(orch, paths=[...])
print(summary.as_dict())
# {
#   "loaded":  ["micro_fish_agent", "cricket_brain_agent"],
#   "skipped": [{"source": "path:/x/y_agent.py",
#                "target": "...",
#                "reason": "no class with AGENT_NAME / required methods found"}],
#   "errors":  [{"source": "path",
#                "target": "/does/not/exist",
#                "reason": "directory does not exist"}],
# }
```

## Limitations

- Plug-ins don't auto-register their task types in `TaskRouter`.
  Run them via `orch.agents["<name>"].run(...)` directly, or extend
  `TaskRouter._task_map` from your plug-in's `__init__` if you want
  `orch.execute_task({"type": "fish_check"})` to dispatch.
- Plug-ins from `*_agent.py` files are imported into a private module
  namespace (`_tao_plugin_<stem>`) — relative imports between plug-in
  files in the same directory aren't supported. Use the entry-point
  installation path if you need a multi-file plug-in package.
