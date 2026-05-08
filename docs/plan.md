# TAO / Bittensor Multi-Agent Intelligence System – Ausführungsplan

## Ziel
Baue das Grundgerüst (RUN 1) des Multi-Agenten-Systems für TAO/Bittensor.

## Skill-Verwendung
- `vibecoding-general-swarm` – Python-Projekt mit CLI, Modulen, Tests

## Stufen

### Stufe 1: Projektstruktur & Dokumentation (parallel)
- 1a: Projekt-Wurzel: README.md, KIMI.md, .gitignore, .env.example, docker-compose.yml, Makefile
- 1b: docs/: wallet_safety.md, risk_model.md, subnet_research_method.md, trade_research_method.md, miner_readiness.md, validator_readiness.md, bittensor_basics.md, agent_architecture.md, run_log.md

### Stufe 2: Kernsystem (parallel)
- 2a: Orchestrator (orchestrator.py, task_router.py, approval_gate.py)
- 2b: Alle 15 Agent-Skeletons (agents/*.py)
- 2c: Collector-Module (collectors/*.py)
- 2d: Scoring-Module (scoring/*.py)
- 2e: Dashboard (dashboard/app.py)
- 2f: CLI (cli/tao_swarm.py)

### Stufe 3: Tests & Qualitätssicherung (parallel)
- test_approval_gate.py, test_subnet_score.py, test_risk_score.py, test_wallet_safety.py

### Stufe 4: Integration & Abschluss
- Testausführung
- Run Log erstellen
- Finaler Report mit Projektstruktur, Dateienliste, Agentenbeschreibungen, Sicherheitsregeln, Teststatus, Next Run

## Ausgabe
- Komplettes Projekt unter /mnt/agents/output/tao-bittensor-swarm/
- Finaler Zusammenfassungsreport
