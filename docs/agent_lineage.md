# Agent data-lineage

The TAO Swarm has 15 agents and an `AgentContext` pull-bus. After
each successful `run()`, the orchestrator publishes the agent's
output under its `AGENT_NAME` so downstream agents can `self.context.get(...)`.

For a long time the swarm had a hidden problem: only **5 of 15
agents** actually consumed any real data — the rest emitted static
plan templates that ignored upstream context entirely. PR 2S
closes that gap. This doc is the source of truth for what every
agent reads, what it writes, and how the dependencies form a DAG.

## The contract

Every agent must have either:

1. **A collector dependency** — uses
   `tao_swarm.collectors.*` to read live (or mock-fallback) data.
2. **An upstream-context dependency** — pulls the output of at
   least one other agent via `self.context.get("<other_agent>")`.

A test (`tests/test_agent_data_lineage.py`) enforces this. An
agent that reads neither real data nor upstream context is a
template emitter, and the test fails the build.

The constructor must still work without context (for unit tests
and ad-hoc invocations). Agents call `self.context.get(...)` in
`run()` and gracefully fall back when the upstream isn't present —
either with a default, or by stamping `_meta.upstream_seen=[]` on
their output so the operator can tell the run was un-contextualised.

## The lineage table

Reads from upstream agents flow downward. Live-data reads are
external (chain, market, wallet, github) and don't show in this
table.

| # | Agent | Reads (live) | Reads (context) | Writes | Why |
|---|---|---|---|---|---|
| 1 | `system_check_agent` | hardware probes | — | `hardware_report`, `software_report`, `readiness_scores` | foundation: every other agent that cares about machine capacity reads from here |
| 2 | `protocol_research_agent` | `chain_readonly` | — | `network_health` (subnet count, total stake, validator count) | independent observation of chain state |
| 3 | `subnet_discovery_agent` | `chain_readonly` | — | `subnets[]` with rich `tao_in` / `volume` / identity | base for everything subnet-flavoured |
| 4 | `subnet_scoring_agent` | `chain_readonly` + `tao_swarm.scoring` | `subnet_discovery_agent` | per-subnet scores + recommendations | scores depend on the freshly-discovered list |
| 5 | `wallet_watch_agent` | `wallet_watchonly` | — | balance + stake reports for the configured addresses | independent — operator's own portfolio view |
| 6 | `market_trade_agent` | `market_data` | `subnet_scoring_agent` | market overview tied to top-scored subnets | the "what's hot" report should mirror what scoring thinks is hot |
| 7 | `risk_security_agent` | text input | (`task["content"]`) | DANGER classification + reason | text-pattern detector, no upstream needed |
| 8 | `miner_engineering_agent` | — | `system_check_agent.hardware_report` + `subnet_scoring_agent` (top subnet) | mining setup plan tailored to actual hardware + the subnet scoring recommends | template was static; now matches reality |
| 9 | `validator_engineering_agent` | — | `system_check_agent.hardware_report` + `subnet_scoring_agent` | validator setup plan tailored to actual hardware + recommended subnet | parallel structure to miner-engineering |
| 10 | `training_experiment_agent` | — | `system_check_agent.hardware_report` + `miner_engineering_agent` | training plan sized for the available GPU/RAM + the chosen miner role | parameters depend on hardware AND the miner's chosen subnet |
| 11 | `infra_devops_agent` | — | `system_check_agent.hardware_report` + best of `{miner,validator}_engineering_agent` | deployment plan tuned to the inferred role | container limits / replica counts depend on role + machine |
| 12 | `fullstack_dev_agent` | — | `subnet_scoring_agent` + `market_trade_agent` | UI / CLI mock-ups for the recommended subnet | the demo product centres on the recommended subnet |
| 13 | `qa_test_agent` | — | every other agent's keys | per-agent test plan focused on what's actually published | template was generic; now scopes tests to the agents that ran |
| 14 | `documentation_agent` | self-introspection | every agent's `_meta` | live system doc with upstream coverage stats | already pulls agent list; now also reports lineage health |
| 15 | `dashboard_design_agent` | — | `subnet_scoring_agent` + `market_trade_agent` + (optional) trading-runner status file | dashboard panel layouts tailored to current data | designs should reflect what the dashboard would actually show |

## Why this matters

Before the fix:
- Operator runs the swarm. 5 agents do real work. 10 emit identical
  output every time, regardless of what the chain shows or what
  hardware they're running on.
- The operator who reads `qa_test_agent`'s plan and `infra_devops_agent`'s
  plan back-to-back gets the same generic template — they could be
  on a Raspberry Pi or an 8-GPU rack and the output wouldn't change.
- "5 of 15 read live data" is in the README — that's an honest
  admission of debt, not a feature.

After the fix:
- The orchestrator's recommended task ordering puts `system_check_agent`
  and `subnet_discovery_agent` first, then `subnet_scoring_agent`,
  then everything else.
- Downstream agents pull what they need. If they don't get it (cold
  run, single-agent invocation), they say so via
  `_meta.upstream_seen` and fall back gracefully.
- The CI test asserts every agent has at least one data-lineage
  source. Adding a new template-only agent to the repo will fail
  the build.

## Adding a new agent

For a new agent:

1. Decide which upstream agents it depends on. Add the wiring in
   the agent's `run()`:
   ```python
   def _pull_upstream(self) -> dict:
       ctx = getattr(self, "context", None)
       if ctx is None:
           return {}
       return {
           "hw": ctx.get("system_check_agent.hardware_report"),
           "scores": ctx.get("subnet_scoring_agent"),
       }
   ```
2. Use the result in your output. If `hw is None`, fall back; but
   condition on what you got when you got it.
3. Stamp `_meta = {"upstream_seen": [k for k, v in upstream.items() if v]}`
   so the operator can see what was wired.
4. Add an entry to the table above.
5. The data-lineage test will pick up your agent automatically as
   long as it lives under `tao_swarm/agents/*_agent.py` and
   declares `AGENT_NAME`.
