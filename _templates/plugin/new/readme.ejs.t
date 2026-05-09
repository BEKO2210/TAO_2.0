---
to: <%= out_dir %>/README.md
---
# <%= h.pascal(name) %> — TAO Swarm plug-in

<%= role %>

A plug-in for the [TAO/Bittensor Multi-Agent Swarm](https://github.com/BEKO2210/TAO_2.0).
This directory is **standalone** — drop it into any path the swarm
discovers (`TAO_PLUGIN_PATHS` env var or `load_plugins(orch, paths=...)`).

## Files

- `<%= h.snake(name) %>_agent.py` — the agent itself
- `test_<%= h.snake(name) %>_agent.py` — sanity tests

## Quick start

```bash
# 1. Tell the swarm where this plug-in lives
export TAO_PLUGIN_PATHS=/path/to/this/dir

# 2. Or load explicitly from Python
python - <<'PY'
from src.orchestrator import SwarmOrchestrator, load_plugins
orch = SwarmOrchestrator({"use_mock_data": True})
print(load_plugins(orch, paths=["/path/to/this/dir"]).as_dict())
PY
```

## Contract

This plug-in honours the SPEC.md agent contract:

- `AGENT_NAME = "<%= h.snake(name) %>_agent"` (module-level)
- `AGENT_VERSION` (module-level, semver string)
- `<%= h.pascal(name) %>Agent.run(task) -> dict`
- `<%= h.pascal(name) %>Agent.get_status() -> dict`
- `<%= h.pascal(name) %>Agent.validate_input(task) -> tuple[bool, str]`

## Safety

- Loaded plug-ins receive `self.context` from the orchestrator —
  pull-only access to other agents' published outputs.
- Every action runs through the swarm's `ApprovalGate` —
  DANGER actions (sign_transaction, stake, transfer, etc.) are
  blocked **before** reaching this plug-in's code.
- The plug-in MUST NOT request seeds, private keys, or perform
  auto-trades. Same rules as built-in agents.

## Distributing

Two ways for users to get your plug-in:

### A) Drop-in (zero packaging)
Just zip / git-clone this directory and put it under a path on
`TAO_PLUGIN_PATHS`.

### B) PyPI / installable (production)
Add a `pyproject.toml` next to the agent file:

```toml
[project]
name = "<%= h.snake(name) %>"
version = "0.1.0"
[project.entry-points."tao.agents"]
<%= h.snake(name) %> = "<%= h.snake(name) %>_agent:<%= h.pascal(name) %>Agent"
```

Then `pip install -e .` and `load_plugins(orch, entry_point_group="tao.agents")`
picks it up automatically.
