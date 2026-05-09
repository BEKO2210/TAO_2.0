# CLAUDE.md — TAO / Bittensor Multi-Agent Intelligence System

Guidance for Claude Code (and other AI agents) working in this repository.

## Project at a glance

- **What:** A locally-run, **read-only** multi-agent intelligence system for researching, monitoring, and analysing Bittensor (TAO).
- **Architecture:** Central `SwarmOrchestrator` routes tasks to 15 specialised agents. Every action passes an `ApprovalGate` that classifies it as `SAFE` / `CAUTION` / `DANGER`.
- **Wallet modes:** `NO_WALLET` (default) → `WATCH_ONLY` → `MANUAL_SIGNING`. The system never auto-signs.
- **Stack:** Python 3.10+, SQLite, Docker, optional FastAPI / Streamlit. Node.js is used **only** for Hygen scaffolding, never at runtime.

The canonical product spec is `SPEC.md`; the swarm constitution is `KIMI.md`. Read both before non-trivial changes.

## Repository layout

```
.
├── README.md / KIMI.md / SPEC.md      # Project, constitution, spec
├── Dockerfile / docker-compose.yml    # Container setup
├── Makefile                           # Common dev commands
├── requirements.txt / requirements-dev.txt
├── .env.example                       # Copy to .env (never commit .env)
├── docs/                              # Architecture, methods, run log, plan
├── tao_swarm/
│   ├── orchestrator/  approval_gate.py · task_router.py · orchestrator.py
│   ├── agents/        15 *_agent.py modules (see SPEC.md)
│   ├── collectors/    chain_readonly · subnet_metadata · market_data · wallet_watchonly · github_repos
│   ├── scoring/       subnet · risk · trade_risk · miner_readiness · validator_readiness
│   ├── dashboard/     app.py
│   └── cli/           tao_swarm.py        # console-script: ``tao-swarm``
├── tests/             pytest suite
└── _templates/        Hygen scaffolding templates
```

## Safety architecture

The system supports four operating modes with strictly increasing
authority. The defaults sit at the safest end and the higher-risk
modes are explicit opt-ins, gate-protected, and limit-bounded.

| Mode | Wallet | Signing | Sends value | Default? |
|---|---|---|---|---|
| `NO_WALLET` | none | no | no | yes |
| `WATCH_ONLY` | public addr | no | no | no |
| `MANUAL_SIGNING` | public addr | external | no | no |
| `AUTO_TRADING` | hot key | yes (gated) | yes (gated) | no |

### Always-on rules (these MUST NOT be relaxed)

1. **NEVER** request, store, log, or transmit **seed phrases or
   mnemonics** — full credentials never live in this system.
2. **NEVER** request, store, log, or transmit **a coldkey private
   key**. Auto-trading uses a hot key with a hard cap; the coldkey
   stays out of this system entirely.
3. `WATCH_ONLY` mode accepts public addresses only.
4. No cloud telemetry; everything runs locally.

### Auto-trading rules (apply only in `AUTO_TRADING` mode)

5. The `ApprovalGate` continues to classify every action; in
   `AUTO_TRADING` mode it routes `DANGER` actions to the audited
   `auto_trader` execution path **only** when all of these are
   satisfied: kill-switch off, hot-key configured, position-size
   limit set, daily-loss-limit set, strategy explicitly opted in.
6. Any one of {kill-switch on, daily-loss-limit hit, position-size
   exceeded, hot-key missing, strategy not opted in} forces the
   gate back to "plan only" output.
7. The auto-trader's hot-key handling, signing path, and broadcast
   path are isolated in their own module so the read-only swarm
   stays read-only by construction.

If a change could weaken any of these rules, stop and ask.

## Agent interface contract

Every agent in `tao_swarm/agents/` must implement:

```python
AGENT_NAME    = "<snake_case_name>"
AGENT_VERSION = "1.0.0"

class <Pascal>Agent:
    def __init__(self, config: dict | None = None) -> None: ...
    def run(self, task: dict) -> dict: ...
    def get_status(self) -> dict: ...
    def validate_input(self, task: dict) -> tuple[bool, str]: ...
```

`run` should **never** raise to the orchestrator — wrap failures in `{"status": "error", "reason": ...}`.

### Return-shape convention

`run()` returns a **flat dict** with at least a top-level `status` key. Agent-specific report fields sit alongside it. Do **not** wrap the payload in a `result` key — the orchestrator already wraps the whole return value under `output`, and carries the agent's per-call `status` up as `agent_result_status` for easy access.

```python
# Good: flat, with status — matches the existing tao_swarm/agents/ majority.
return {"status": "complete", "verdict": "PROCEED", "findings": [], "timestamp": time.time()}

# Avoid: nesting under result wraps once more on top of the orchestrator wrap.
return {"status": "ok", "agent": AGENT_NAME, "result": {"verdict": "PROCEED", ...}}
```

`get_status()` reports the agent's **running state** (idle / running / error / complete) — that's a different thing from the per-call status of any single `run()`.

## Scaffolding new modules — use Hygen, do not hand-roll

Hygen templates live in `_templates/` and enforce the conventions above.

```bash
npm install                # one-time
npx hygen agent new        # interactive: creates tao_swarm/agents/<name>_agent.py + tests/test_<name>_agent.py
npx hygen collector new    # creates tao_swarm/collectors/<name>.py
npx hygen scoring new      # creates tao_swarm/scoring/<name>_score.py + tests/test_<name>_score.py
npx hygen test new         # creates tests/test_<name>.py (variants per kind)
npx hygen doc new          # creates docs/<name>.md
npx hygen plugin new       # external plug-in scaffold (lives OUTSIDE this repo)
```

## Plug-ins (user-defined external agents)

Users add their own agents via
`tao_swarm.orchestrator.load_plugins(orch, paths=[...], entry_point_group="tao.agents")`.
Plug-ins must obey the SPEC.md agent contract (run / get_status /
validate_input + AGENT_NAME / AGENT_VERSION) and are routed through
the same `ApprovalGate` as built-ins — loading a plug-in does **not**
raise its trust level. Full guide in `docs/plugins.md`; scaffold via
`npx hygen plugin new`.

Aliases: `npm run new:agent`, `npm run new:collector`, `npm run new:scoring`, `npm run new:test`, `npm run new:doc`.

After generating, register the new agent in `tao_swarm/agents/__init__.py` (and the analogue for collectors / scoring).

## Common dev commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Tests
pytest -q
pytest tests/test_approval_gate.py -q   # focused

# Linters / formatters (see Makefile for the canonical list)
make lint
make format

# CLI
tao-swarm --help
```

If `make` is available, prefer it over the raw commands above — `Makefile` is the source of truth for project automation.

## Coding conventions

- **Type hints** everywhere; use `from __future__ import annotations` in new files.
- **snake_case** modules and functions; **PascalCase** classes.
- Logging via `logging.getLogger(__name__)`, never `print` in library code.
- No network I/O at import time; no global mutable state.
- Tests live next to behaviour: `tests/test_<module>.py`. Prefer pure unit tests; mock collectors with `use_mock_data=True`.
- Keep collectors **read-only** — if you need to mutate something, that belongs to an agent (so it can route through `ApprovalGate`).

## When making changes

1. Read `SPEC.md` (architecture) and `KIMI.md` (constitution) first.
2. Use Hygen for any new agent / collector / scorer / doc — do not copy-paste.
3. Add or update tests in the same change.
4. Run `pytest -q` before committing.
5. Update `docs/run_log.md` for non-trivial runs or architectural changes.

## Things to avoid

- Adding network calls inside collectors without a mock-data path.
- Bypassing `ApprovalGate` for any action that mutates external state.
- Introducing cloud SDKs, telemetry, or analytics dependencies.
- Hand-writing a new agent when `npx hygen agent new` would do it correctly.
- Committing anything matching `.env`, `*coldkey*`, `*hotkey*`, `*seed*`, `*mnemonic*` (already in `.gitignore` — keep it that way).
