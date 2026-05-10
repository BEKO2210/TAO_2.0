# Changelog

All notable changes to TAO_2.0 are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added — `TradingCouncil` wired as runner pre-tick veto (PR 2U)

The `TradingCouncil` (PR 2T) is now an optional pre-tick veto in
`TradingRunner`. When wired, the runner calls `council.aggregate()`
before every tick; if the decision is `"halt"` (high-confidence
VETO from `risk_security_agent` or `qa_test_agent`), the tick is
skipped — no snapshot, no `strategy.evaluate`, no executor dispatch
— and the decision is recorded under `status.last_council_decision`.
The runner is **not** permanently halted: the next tick re-asks the
council so a transient veto unblocks naturally without operator
`reset()`. `bullish` / `neutral` / `bearish` are advisory and do not
block the tick.

**This PR also renames the aggregator from "TradingBrain" to
"TradingCouncil"** to better reflect what it is: a multi-voice
expert team with a veto layer, not a single anthropomorphic decider.
All identifiers, files, CLI command, docs, and tests follow the new
name; no functional change to the aggregator itself.

What changed
- `tao_swarm/trading/runner.py`: optional `council=` constructor arg;
  new pre-tick check in `tick()`; new status fields `council_enabled`,
  `council_skipped_ticks`, `last_council_decision`,
  `last_council_skip_ts`. Defensive: a council `aggregate()` that
  raises is recorded as a runner error but never breaks the loop.
- `tao_swarm/cli/tao_swarm.py`: `trade run` gains `--require-council`
  + `--council-task` flags. With `--require-council`, the CLI builds
  a `SwarmOrchestrator`, runs `--council-task` once to populate
  `AgentContext`, constructs a `TradingCouncil(orch.context)`, and
  hands it to the runner. Run-end summary surfaces
  `council: skipped N tick(s) on veto`.
- `tao_swarm/trading/council.py` (was `brain.py`), `__init__.py`
  re-exports, `tao_swarm/cli/tao_swarm.py` (`trade council`
  command), `docs/trading_council.md`, `README.md`,
  `tests/test_trading_council.py`: rename `TradingBrain` →
  `TradingCouncil`, `BrainDecision` → `CouncilDecision`,
  `BRAIN_DEFAULT_WEIGHTS` → `COUNCIL_DEFAULT_WEIGHTS`.
- `docs/trading_council.md`: new "Runner-Integration" section with
  the Python API + the `--require-council` CLI flow.
- `tests/test_runner_council_integration.py` (new, 9 tests): runner
  default behaviour without council; halt path skips the tick;
  transient halt → clear resumes; bullish / neutral / bearish do not
  block; `aggregate()` exception is advisory; status JSON round-trip
  preserves the council fields.

Tests: 998 passed, 12 deselected; council suite alone is 57.

### Changed — License: BUSL-1.1 → fully proprietary

The owner has elected to take the project closed-source. The previous
"source-available, free for non-production, auto-converts to Apache
2.0 on 2030-01-01" framing is replaced with a fully proprietary
"All Rights Reserved" licence. The repository remains visible on
GitHub for evaluation, but no use, copy, modify, distribute,
sublicense, or trademark rights are granted to anyone other than the
Licensor or under a separate written licence agreement.

What changed
- `LICENSE`: replaced with a 10-section proprietary licence
  (no implied permissions; evaluation-viewing only; no reverse
  engineering except where mandatory law overrides; no trademark
  grant; earlier-version licences (MIT / BUSL-1.1) remain valid
  only for the snapshots they covered).
- `DISCLAIMER.md`: section 4 updated — `AUTO_TRADING` is intended
  for use only by the Licensor and individuals expressly licensed
  in writing; no public Additional Use Grant any more.
- `README.md`: top notice rewritten ("All rights reserved … keine
  Nutzungserlaubnis"), license badge changed to "Proprietary",
  installation / quickstart sections gated on having a separate
  written licence, full Lizenz-Section rewritten with two columns
  (Erlaubt-ohne-Lizenz vs. Erfordert-schriftliche-Lizenz),
  Schnellüberblick row updated.
- `landing/index.html` + `landing/de.html`: Hero eyebrow says
  "Proprietary" instead of "BUSL-1.1"; license section rewritten
  in the same shape; roadmap "Now" row says "Closed beta ·
  proprietary"; Apache-2030 row removed; commercial-license row
  rephrased to acknowledge that source remains proprietary.
- `pyproject.toml`: header comment rewritten; "License classifier"
  comment simplified; `License :: Other/Proprietary License`
  classifier kept (already correct per PEP 639).

Effect on prior public versions
- Anyone who legitimately obtained the software under MIT (very
  early) or BUSL-1.1 (PRs #27 → #45) keeps the rights granted by
  *that* licence on *those* snapshots. Going forward, every commit
  is governed by the new proprietary licence.



### Architectural pivot — `AUTO_TRADING` mode authorised

The owner has authorised an architectural pivot: in addition to the
existing `NO_WALLET` / `WATCH_ONLY` / `MANUAL_SIGNING` modes, the
project will support a fourth mode, `AUTO_TRADING`, in which the
software signs and submits transactions on behalf of the operator
within hard limits.

This is an authorised relaxation of the previous "never auto-execute"
constitution. The pivot is being landed in two phases:

**Step 1 (this PR) — public framing only, no code yet:**

- `LICENSE`: Additional Use Grant rewritten with two parts. Part (A)
  preserves Non-Production Use as before. Part (B) explicitly permits
  *Personal Single-User Automated Trading* on assets the operator
  themselves owns; multi-user / hosted / managed-fund use still
  requires a commercial licence.
- `DISCLAIMER.md`: rewritten with a new "Operating modes" section
  (4 modes, default safest), a new "Auto-trading risks" section, and
  expanded compliance / no-warranty language for trading-specific
  failure modes (key exfiltration, slippage, regulatory).
- `CLAUDE.md`: "Non-negotiable safety rules" replaced by the layered
  "Safety architecture" matrix (per-mode capabilities) plus
  always-on rules (never store seeds, never store coldkey private
  keys) and auto-trading-mode-only rules (gate-protected execution,
  kill switch, position cap, daily-loss-limit).
- `README.md`: top banner rewritten ("autonomes Multi-Agenten-System"
  instead of "read-only Multi-Agentensystem"). Lizenz-Section reflects
  the new "Personal Single-User Auto-Trading allowed" grant.
- `landing/index.html` + `landing/de.html`: hero copy, "Was/What"
  card 02 + 04, roadmap "Will not do" list, all rewritten to
  reflect that auto-trading is an opt-in mode (not a forbidden one).
  The "no managed funds, no token, no telemetry" promises stay.

**Step 2 — code (landed across PRs 2A–2J):**

The audited execution path under `tao_swarm.trading/` is now
complete. Paper-trading is the default; live execution requires
the operator to opt in at three independent layers (env var,
keystore, per-strategy `live_trading=True`) and pass the executor's
four-guard chain (kill switch, mode, position cap, daily loss).
Bittensor's `stake` / `unstake` / `transfer` extrinsics are signed
on-chain when (and only when) all gates consent.

- **2A — Skeleton** (PR #47). `tao_swarm.trading/` package:
  `WalletMode`, `KillSwitch`, `PositionCap`, `DailyLossLimit`,
  `PaperLedger` (SQLite WAL), `Strategy` ABC + `TradeProposal`
  + `StrategyMeta`, paper-default `Executor`. Live signing path
  raises `NotImplementedError` until 2E.
- **2B — Gate routing** (PR #48). `ApprovalGate.auto_trading_status(
  executor)` returns `(True, "")` only when wallet_mode==AUTO_TRADING,
  executor present + AUTO_TRADING, kill switch off, daily loss not
  breached. Position-cap deferred to per-call executor check.
- **2C — Encrypted keystore** (PR #49). Argon2id (OWASP 2024
  baseline: t=3, m=64MiB, p=4) + AES-256-GCM. Atomic write
  (tmp → fsync → rename), `chmod 0o600`. `SignerHandle` is
  context-managed; seed bytes are zeroed via `ctypes.memset`
  on exit. Same exception type for wrong password and tampered
  ciphertext (anti-timing).
- **2D — Strategy + Backtester** (PR #50). First concrete
  strategy `MomentumRotationStrategy` (re-stake into rising
  `tao_in`, unstake from falling). Deterministic backtester
  computes total P&L, win rate, max drawdown, pseudo-Sharpe over
  historical snapshot streams.
- **2E — Live signing** (PR #51). `BittensorSigner` connects
  `SignerHandle` → `bittensor.Subtensor.add_stake / unstake /
  transfer`. Three-step authorisation: `TAO_LIVE_TRADING=1` env
  var + signer factory wired into Executor + strategy's
  `StrategyMeta.live_trading=True`. Failed live attempts get
  `action="<verb>_failed"` audit rows; the broadcast itself is
  surfaced as `BroadcastError`.
- **2F — Runner + CLI + operator guide** (PR #52).
  `TradingRunner` is the tick-driven loop: snapshot → strategy →
  executor; tracks open positions for `current_total_tao`
  arithmetic; runner-local circuit breaker on consecutive errors.
  CLI gets `tao-swarm keystore init/info/verify` and
  `tao-swarm trade backtest/run/status` with a typed-confirmation
  walkthrough before any live extrinsic is broadcast. New
  `docs/auto_trading.md` operator setup guide.
- **2G — Cold-start reconciliation** (PR #53). On the first tick,
  `TradingRunner` reads on-chain stake for the configured coldkey
  via `BittensorChainPositionReader` (mirrors the SDK's
  `get_stake_info_for_coldkey`) and rewrites the in-memory
  position book. Without this, a process restart would see
  `current_total_tao=0` and overshoot the cap by the entire
  already-staked balance. Reconciliation failure halts the runner
  rather than trade with an unverified book.
- **2H — Slippage + chain-truth verification** (PR #54).
  `TradeProposal` grows optional `rate_tolerance` and
  `allow_partial`; the signer threads them as
  `safe_staking` / `safe_unstaking` / `allow_partial_stake`
  kwargs. Optional post-broadcast verification re-reads the
  chain to confirm the observed delta matches the proposal
  direction within tolerance; mismatches are recorded as
  `<verb>_verification_failed` audit rows but do NOT abort
  the broadcast.
- **2I — Dashboard + status dump** (PR #55). `TradingRunner.dump_status(
  path)` writes the current state atomically as JSON each tick.
  Streamlit "Trading" page replaces the old placeholder: live
  KPIs, halt/error banners, open positions, last reconcile,
  ledger summary. Discovery via `TAO_RUNNER_STATUS_FILE` /
  `TAO_LEDGER_DB` env vars.
- **2J — Plug-in framework + mean-reversion** (PR #56).
  `StrategyRegistry` + `load_strategy_plugins(paths=,
  entry_point_group="tao.strategies")` mirror the existing agent
  plug-in surface for strategies. Built-in
  `MeanReversionStrategy` is the inverse-momentum complement to
  `MomentumRotationStrategy`. Operators drop a `*_strategy.py`
  file in any directory listed via `TAO_STRATEGY_PATHS` and the
  CLI picks it up. New `docs/strategy_plugins.md` guide.

What stayed true across all 10 PRs: paper-trade is still the
default; loading a plug-in does NOT raise its trust level; every
live attempt — success, refusal, or error — is recorded in the
SQLite ledger as a non-paper row so the audit trail is complete
regardless of outcome.



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
- **CricketCouncil demo plug-in** — end-to-end worked example of an
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
