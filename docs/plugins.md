# Plug-in agents

The TAO swarm ships with 15 built-in agents. **Plug-ins** let you add your
own agents without forking the core repo. A plug-in is a single Python
file (or installable package) that follows the SPEC.md agent contract;
the orchestrator discovers, validates, and registers it at runtime.

## Two ways to ship a plug-in

### 1. Path-based (drop a `*_agent.py` file in a folder)

Cheapest. No packaging, no `pip install`. You write:

```
/home/user/my-agents/
└── my_agent.py
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
# → {"loaded": ["my_agent"], "skipped": [], "errors": []}
```

### 2. Entry-point based (production / pip-installable)

When your plug-in lives in a real repo and you want users to
`pip install` it. In your repo's `pyproject.toml`:

```toml
[project]
name = "my-tao-plugins"
version = "0.1.0"

[project.entry-points."tao.agents"]
my_agent = "my_tao_plugins.my_agent:MyAgent"
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

`run()` MUST return a flat dict with a top-level `status` key and
MUST NOT raise to the orchestrator (return
`{"status": "error", "reason": ..., "agent_name": ...}` instead).
The structural test `tests/test_agent_contract.py` enforces this for
the built-ins; copy its shape for your own plug-in tests.

`validate_input()` MUST require `task["type"]` — every agent in the
system rejects tasks without a type, since the orchestrator routes by it.

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

## Listing what got loaded

```python
summary = load_plugins(orch, paths=[...])
print(summary.as_dict())
# {
#   "loaded":  ["<agent_name>"],
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
  `orch.execute_task({"type": "<your_type>"})` to dispatch.
- Plug-ins from `*_agent.py` files are imported into a private module
  namespace (`_tao_plugin_<stem>`) — relative imports between plug-in
  files in the same directory aren't supported. Use the entry-point
  installation path if you need a multi-file plug-in package.
