# Changelog

All notable changes to TAO_2.0 are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed — Licensing & legal hardening

- **Switched from MIT to Business Source License 1.1 (BUSL-1.1).**
  Rationale: until the project reaches its next milestone, the
  authors want explicit control over production / commercial /
  hosting deployments while still allowing free Non-Production Use
  (personal, research, evaluation, teams up to 5 people, mock-mode
  development, plug-in writing). BUSL-1.1 is the standard
  source-available licence that fits this exact pattern (used by
  HashiCorp, MariaDB, Sentry, etc.).
- **Change Date: 2030-01-01.** On that date the licence
  automatically converts to Apache License 2.0 — the project
  becomes fully open source at that point and the
  Non-Production-Use restriction lifts.
- **Additional Use Grant** in `LICENSE` defines Non-Production Use
  exhaustively: personal/educational/research/evaluation, teams ≤
  5 people, no third-party hosting, no automated value-moving
  decisions, no embedding in distributed products.
- **New `DISCLAIMER.md`** — comprehensive risk, liability, and
  compliance disclosures covering: not-financial-advice,
  cryptocurrency volatility, no-automated-value-movement guarantees,
  read-only assumptions, third-party endpoint terms, no-warranty,
  user-responsibility-for-compliance, production-use boundaries,
  upstream-dependency-licences.
- **README.md** restructured with a top-level "Lizenz & rechtlicher
  Status" section that names what's allowed / not allowed without
  the user having to open the licence file. Quick Start now uses
  the `tao-swarm` console-script and shows live-mode examples
  alongside mock. Schnellüberblick refreshed to reflect the actual
  state: 547 tests, 10 live smokes, real chain reads, BUSL.
- `pyproject.toml` classifier updated from
  `License :: OSI Approved :: MIT License` to
  `License :: Other/Proprietary License` (BUSL is source-available,
  not OSI-approved Open Source).

## [1.0.0] — 2026-05-09

First public release. The framework, safety architecture, and
plug-in system have reached production-grade quality; **agent
implementations vary in maturity** (see "Agent quality matrix"
below). Treat this as a **Beta** in PyPI classifier terms — the
contracts are stable, but several agents still emit template
output rather than reasoning over collector data.

### Added

- **Multi-agent orchestrator** with 15 built-in agents covering
  system probing, protocol research, subnet discovery / scoring,
  watch-only wallet snapshot, market analysis, risk review,
  miner / validator engineering, training experiment planning,
  infra / DevOps templating, dashboard / fullstack design, QA,
  and documentation.
- **`ApprovalGate`** — 3-tier classification (`SAFE` / `CAUTION` /
  `DANGER`) applied **before** routing, so DANGER actions
  (`execute_trade`, `sign_transaction`, `stake`, `swap_coldkey`,
  `reveal_seed`, …) are blocked even when no agent is mapped.
- **`TaskRouter`** — dynamic task-type → agent map, capability
  registration on `register_agent`, fuzzy fallback for unmapped
  types.
- **Pull-based context bus** (`AgentContext`) — agents publish
  their `run()` output under their name; later agents read via
  `self.context.get("system_check_agent")`. Failed runs
  (`status == "error"`) are skipped so consumers never pick up
  stale data.
- **Wallet modes:** `NO_WALLET` (default) → `WATCH_ONLY` (public
  addresses only) → `MANUAL_SIGNING` (user signs externally —
  never auto-signed).
- **Plug-in architecture** — user-defined agents live OUTSIDE the
  repo. Two delivery modes: path-based (drop a `*_agent.py` file,
  set `TAO_PLUGIN_PATHS`) or entry-point-based
  (`[project.entry-points."tao.agents"]` in the user's own
  `pyproject.toml`). Plug-ins go through the same `ApprovalGate`
  as built-ins; loading does not raise their trust level.
- **Hygen scaffolding** — `npx hygen agent|collector|scoring|test|doc|plugin new`
  generates contract-compliant skeletons with matching tests.
- **Read-only Bittensor SDK v10 collector** — `chain_readonly`
  uses `SubtensorApi` and `metagraph` for real economics, with a
  mock-data fallback when the SDK isn't installed.
- **Risk detectors** — Bittensor-specific (PyPI typosquats,
  coldkey-swap detection, validator-risk patterns).
- **Chain-derived subnet scoring** — 5 quality criteria from
  on-chain data plus mock fallback.
- **Real Subscan integration** — `wallet_watchonly` queries balance
  and staking from Subscan; mock fallback when network is absent.
- **Live CUDA / GPU detection** — `system_check` shells out to
  `nvidia-smi` for accurate GPU counts and memory.
- **Per-task resilience** — opt-in timeout, retry policy, and
  cooperative cancel token on `execute_task`.
- **Concurrent execution** — opt-in parallel `execute_run` with
  per-agent locks for safety.
- **Capabilities + heartbeat** — agents advertise capabilities
  (auto-registered into the router) and report progress through
  the orchestrator's heartbeat channel.
- **Streamlit dashboard** — import-clean without Streamlit
  installed; namespaced cache discovery.
- **Benchmark suite** — realistic workload personas, mock by
  default, opt-in `make bench-live` for real endpoints.
- **CricketBrain demo plug-in** — end-to-end worked example of an
  external agent (later removed in favor of a serious replacement
  plug-in tracked separately).
- **Hardened agent contract** — every built-in's `run()` is
  guaranteed not to raise to the orchestrator; every
  `validate_input` rejects tasks without a `type` field;
  `agent_result_status` is consistently lifted to the top-level
  result. Locked in by `tests/test_agent_contract.py` (77
  parametrized regression tests).
- **Hardened plug-in loader** — same-filename-different-dirs
  collision in `sys.modules` resolved via parent-path hashing;
  stricter `AGENT_NAME` shape validation (rejects non-str,
  whitespace-only, padded names with structured skip reason);
  regression tests for `__init__` raising and `run()` raising.

### Tests

530 passing, 2 deselected, 27 test files. Coverage spans:
- Approval-gate classification matrix.
- Task router dispatch and fuzzy fallback.
- Per-agent contract conformance (parametrized over all 15).
- Plug-in loader: discovery, contract checks, conflict policies,
  AGENT_NAME shape, init-raising, run-raising, same-filename
  collisions, env-var path resolution, entry-point resolution.
- Context bus pull semantics.
- Resilience: timeout, retry, cancel.
- Concurrent run with per-agent locking.

### Documentation

- `SPEC.md` — canonical architecture spec.
- `KIMI.md` — swarm constitution.
- `CLAUDE.md` — guidance for AI agents working in the repo.
- `docs/plugins.md` — plug-in author guide.
- `docs/agent_architecture.md`, `docs/bittensor_basics.md`,
  `docs/{miner,validator}_readiness.md`,
  `docs/risk_model.md`, `docs/subnet_research_method.md`,
  `docs/trade_research_method.md`, `docs/wallet_safety.md`.

### Safety

- Default wallet mode is `NO_WALLET`.
- `.gitignore` blocks `.env`, `*coldkey*`, `*hotkey*`, `*seed*`,
  `*mnemonic*`, key-template files (templates allowed).
- No cloud telemetry. Everything runs locally.
- DANGER actions output **plans / checklists only** — they do not
  execute.

### Agent quality matrix

A 2026-05-09 audit of all 15 agents found uneven maturity. The
framework, contracts, gate, router, plug-in loader, and tests are
production-grade, but agent depth varies:

**A-/B+ — real logic, sensible outputs:**
- `risk_security_agent` — Bittensor-specific detectors (PyPI
  typosquats, coldkey-swap pattern, validator delegation risk
  scoring) with weighted severity; cites real CVEs.
- `system_check_agent` — genuine `nvidia-smi` CSV parsing,
  tri-source CUDA detection (smi/nvcc/torch) with documented
  authority order.
- `wallet_watch_agent` — watch-only flow with mock fallback;
  SS58 prefix check (no full checksum yet).
- `subnet_scoring_agent` — 10 weighted criteria with proper
  flat/nested-params merge.

**B-/B — competent templates with hardcoded heuristics:**
- `miner_engineering_agent` / `validator_engineering_agent` —
  the only two agents that consume the pull-based context bus
  (via `src/agents/_hardware.py`). Setup steps are realistic but
  some thresholds are placeholders.
- `market_trade_agent` — CoinGecko fetch path exists; most
  analysis is still mock-derived.
- `qa_test_agent` — real filesystem walking with secret regexes;
  shells out to pytest.

**C/C-/D+ — mostly hardcoded constants or string templates:**
- `protocol_research_agent` — substring search over a static
  knowledge dict.
- `subnet_discovery_agent` — 19 hardcoded subnets; real
  Bittensor has 60+ netuids.
- `training_experiment_agent` — fixed hyperparameter tables.
- `infra_devops_agent` — emits hardcoded f-string Dockerfiles.
- `dashboard_design_agent` — fixed panel/theme dicts.
- `fullstack_dev_agent` — 12-module plan with hand-typed hours.
- `documentation_agent` — agent list hardcoded twice; drift risk.

**Architectural gap (will be closed in 1.1.x):**

Despite the swarm shipping with full read-only collector and
scoring packages (`src/collectors/`, `src/scoring/`), **no agent
currently imports from either**. The infrastructure exists; the
weakest 7 agents would graduate from C/D to B simply by calling
the collectors that are already there instead of fabricating
data. Tracking this as the highest-leverage 1.1.0 work.

### Known limitations (will land in a follow-up minor release)

- **Collector / scoring wiring**: 13 of 15 agents bypass the
  available data layer (see "Architectural gap" above).
- The package is not yet pip-installable: `src/` is the top-level
  package. A layout migration to `tao_swarm/` is queued so that
  `pip install tao-swarm` and a console entry-point work
  out-of-the-box.
- `make bench-live` exists but a recorded canonical run against
  real endpoints is not in this release.
- Test coverage percentage is not tracked in CI yet.
- Agent `run()` outputs are flat dicts with a `status` key rather
  than typed artifacts (TypedDict / pydantic). Industry consensus
  is shifting toward typed artifacts; we'll migrate in a minor
  release without breaking the wire format.
- Collector text (especially `github_repos`) is published to the
  context bus without prompt-injection sanitization. Mitigated
  in practice by the read-only architecture (no LLM in the loop
  yet); will be hardened before any LLM consumer is wired in.

[Unreleased]: https://github.com/BEKO2210/TAO_2.0/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/BEKO2210/TAO_2.0/releases/tag/v1.0.0
