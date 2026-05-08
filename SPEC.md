# SPEC.md — TAO / Bittensor Multi-Agent Intelligence System

## Overview
A locally-run, read-only multi-agent intelligence system for researching, monitoring, and analyzing Bittensor (TAO). 15 specialized agents coordinated by a central orchestrator with strict safety rules. No automated trading, no wallet signing, no mainnet actions without manual approval.

## Architecture
- Central Orchestrator routes tasks, enforces approval gates, resolves conflicts
- 15 specialized agents (see agent list below)
- Approval Gate: SAFE / CAUTION / DANGER classification for every action
- Wallet modes: NO_WALLET (default), WATCH_ONLY, MANUAL_SIGNING
- Tech stack: Python, SQLite, Docker, optional FastAPI + React/Streamlit

## Project Structure
```
tao-bittensor-swarm/
  README.md                         # Project overview
  KIMI.md                           # Swarm constitution / master prompt
  .gitignore                        # Git ignore rules
  .env.example                      # Environment variable template
  docker-compose.yml                # Docker composition
  Makefile                          # Build automation

  docs/
    bittensor_basics.md             # Bittensor protocol basics
    agent_architecture.md           # Agent architecture documentation
    wallet_safety.md                # Wallet safety rules
    risk_model.md                   # Risk model documentation
    subnet_research_method.md       # Subnet research methodology
    trade_research_method.md        # Trade research methodology
    miner_readiness.md              # Miner readiness guide
    validator_readiness.md          # Validator readiness guide
    run_log.md                      # Run log

  src/
    orchestrator/
      orchestrator.py               # Main orchestrator
      task_router.py                # Task routing logic
      approval_gate.py              # Approval gate with SAFE/CAUTION/DANGER

    agents/
      system_check_agent.py         # Agent 1: System environment check
      protocol_research_agent.py    # Agent 2: Bittensor protocol research
      subnet_discovery_agent.py     # Agent 3: Subnet discovery
      subnet_scoring_agent.py       # Agent 4: Subnet scoring
      wallet_watch_agent.py         # Agent 5: Wallet watch-only
      market_trade_agent.py         # Agent 6: Market & trade analysis
      risk_security_agent.py        # Agent 7: Risk & security
      miner_engineering_agent.py    # Agent 8: Miner engineering
      validator_engineering_agent.py # Agent 9: Validator engineering
      training_experiment_agent.py  # Agent 10: Training & experiments
      infra_devops_agent.py         # Agent 11: Infrastructure & DevOps
      dashboard_design_agent.py     # Agent 12: Dashboard design
      fullstack_dev_agent.py        # Agent 13: Fullstack developer
      qa_test_agent.py              # Agent 14: QA & testing
      documentation_agent.py        # Agent 15: Documentation

    collectors/
      chain_readonly.py             # Read-only chain data collector
      subnet_metadata.py            # Subnet metadata collector
      market_data.py                # Market data collector
      wallet_watchonly.py           # Wallet watch-only collector
      github_repos.py               # GitHub repository collector

    scoring/
      subnet_score.py               # Subnet scoring algorithm
      risk_score.py                 # Risk scoring algorithm
      trade_risk_score.py           # Trade risk scoring
      miner_readiness_score.py      # Miner readiness scoring
      validator_readiness_score.py  # Validator readiness scoring

    dashboard/
      app.py                        # Dashboard application

    cli/
      tao_swarm.py                  # Main CLI entry point

  tests/
    test_approval_gate.py           # Approval gate tests
    test_subnet_score.py            # Subnet scoring tests
    test_risk_score.py              # Risk scoring tests
    test_wallet_safety.py           # Wallet safety tests

  reports/
    subnet_reports/                 # Subnet analysis reports
    wallet_reports/                 # Wallet watch reports
    trade_reports/                  # Trade analysis reports
    system_reports/                 # System check reports
    run_reports/                    # Run reports
```

## Agent Interface Contract
Every agent MUST implement:
- `class <AgentName>Agent:` with `__init__(self, config: dict)`
- `def run(self, task: dict) -> dict:` — executes task, returns result dict
- `def get_status(self) -> dict:` — returns agent status
- `def validate_input(self, task: dict) -> tuple[bool, str]:` — validates input
- Module-level constant: `AGENT_NAME = "<name>"` and `AGENT_VERSION = "1.0.0"`

## Approval Gate Interface
```python
class ApprovalGate:
    def classify_action(self, action_type: str, action_params: dict) -> str:
        """Returns: 'SAFE', 'CAUTION', or 'DANGER'"""
    
    def can_execute(self, classification: str, mode: str = 'default') -> bool:
        """Returns True only for SAFE; CAUTION/DANGER need manual override"""
    
    def validate_plan(self, plan: dict) -> dict:
        """Validates a plan and returns {valid: bool, classification: str, reasons: list}"""
```

## Safety Rules (Non-negotiable)
1. NEVER request or store seed phrases
2. NEVER request or store private keys
3. NEVER auto-execute trades
4. NEVER auto-stake/unstake
5. NEVER auto-sign transactions
6. DANGER-classified actions output plans/checklists only
7. All modes default to NO_WALLET
8. Public wallet addresses only for WATCH_ONLY mode

## Dependency Standards
- Python 3.10+
- Core: requests, sqlite3, click (CLI), pytest, python-dotenv
- Optional: fastapi, uvicorn, streamlit
- No cloud/telemetry dependencies
