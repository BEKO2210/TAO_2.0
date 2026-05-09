<div align="center">
  <img src="Logo.png" alt="TAO Swarm" width="160">
  <h1>TAO / Bittensor Multi-Agent Intelligence System</h1>
</div>

> Ein lokales, **read-only** Multi-Agentensystem zur Recherche, Analyse und Entscheidungsunterstützung im Bittensor (TAO)-Ökosystem. 15 spezialisierte Agenten arbeiten als Schwarm unter zentraler Governance — und du kannst eigene Agenten als **Plug-ins** hinzufügen.

> **WICHTIG:** Dieses System führt **KEINE automatischen Transaktionen** durch, speichert **KEINE Private Keys oder Seed Phrases**, und gibt **KEINE Finanzberatung**. Jede DANGER-Aktion (Trade, Stake, Sign) wird vor der Ausführung blockiert und nur als Plan ausgegeben.
>
> **Lizenz & Nutzung:** Diese Software steht unter der [Business Source License 1.1](LICENSE) — **freie Nutzung nur für Non-Production**. Vor jeder Installation **bitte [DISCLAIMER.md](DISCLAIMER.md) und [LICENSE](LICENSE) lesen**. Production / kommerzielle Nutzung erfordert eine separate kommerzielle Lizenz.

[![Tests](https://img.shields.io/badge/tests-547%20passing-brightgreen)]() [![License](https://img.shields.io/badge/license-BUSL--1.1-orange)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%2B-blue)]() [![Status](https://img.shields.io/badge/status-Beta-yellow)]()

---

## Inhaltsverzeichnis

- [Lizenz & rechtlicher Status](#lizenz--rechtlicher-status)
- [Schnellüberblick](#schnellüberblick)
- [Architektur](#architektur)
- [Die 15 Agenten](#die-15-agenten)
- [Plug-ins (eigene Agenten)](#plug-ins-eigene-agenten)
- [Projektstruktur](#projektstruktur)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI-Modi: --mock vs --live](#cli-modi---mock-vs---live)
- [ApprovalGate (Safety-Layer)](#approvalgate-safety-layer)
- [Bittensor-spezifische Sicherheits-Detektoren](#bittensor-spezifische-sicherheits-detektoren)
- [Subnet-Scoring (15 Kriterien)](#subnet-scoring-15-kriterien)
- [Wallet-Sicherheit](#wallet-sicherheit)
- [Benchmarks](#benchmarks)
- [Tests entwickeln](#tests-entwickeln)
- [Sicherheitshinweise](#sicherheitshinweise)
- [Disclaimer](#disclaimer)

---

## Lizenz & rechtlicher Status

Dieses Projekt steht unter der **Business Source License 1.1 (BUSL-1.1)** —
nicht unter MIT, GPL oder einer anderen Open-Source-Lizenz. Du darfst die
Software **kostenlos** nutzen, kopieren, modifizieren und weitergeben,
solange deine Nutzung als **Non-Production Use** im Sinne der [LICENSE](LICENSE)
gilt:

- **Erlaubt** (ohne kommerzielle Lizenz):
  - persönliche, schulische, Forschungs- und Evaluations-Nutzung
  - Teams bis 5 Personen
  - Read-only Recherche und Analyse, Mock-Mode für Entwicklung
  - Eigene Plug-ins entwickeln und testen

- **Nicht erlaubt** (braucht separate Lizenz vom Lizenzgeber):
  - Hosting als Service für Dritte (gegen Bezahlung oder anderweitig)
  - Automatisierte Trading-, Staking- oder Signing-Entscheidungen
  - Einbettung in ein verkauftes / lizensiertes / gehostetes Produkt
  - Production-Deployments jeder Art

**Change Date: 2030-01-01.** An diesem Datum konvertiert die Software
automatisch zur **Apache License 2.0** und wird vollständig Open Source.

**Vor der Nutzung lesen:**
- [LICENSE](LICENSE) — die Lizenz selbst inkl. "Additional Use Grant"
- [DISCLAIMER.md](DISCLAIMER.md) — Risiko-, Haftungs- und Compliance-Hinweise

> Wenn du irgendeinen Teil dieser Lizenz oder des Disclaimers nicht akzeptierst, **installiere und benutze diese Software nicht.**

---

## Schnellüberblick

| Bereich | Stand |
|---|---|
| **Agenten** | 15 deterministische Python-Agenten (kein LLM intern). 5 davon konsumieren Live-Chain-/Marktdaten; die restlichen sind absichtlich Template-Emitter. Plus benutzerdefinierte **Plug-ins** aus deinem eigenen Repo. |
| **Orchestrator** | Zentraler `SwarmOrchestrator` mit ApprovalGate (gate-before-route), TaskRouter, AgentContext-Bus, optionaler paralleler Task-Ausführung. |
| **Chain-Daten** | Echtes Bittensor SDK 10.x (`SubtensorApi`) — auf Mainnet finney verifiziert: 129 Subnets, rich `DynamicInfo` mit owner / identity / github_repo / TAO_in / volume. Per-Network-Cache. `BT_READ_ONLY=1` als Default. |
| **Live-Pfade** | Mainnet finney (Bittensor SDK), Subscan (Wallet), CoinGecko (Markt), GitHub (Repo-Metadata) — alle mit graceful Fallback und `_meta.fallback_reason`-Tagging. |
| **Sicherheit** | DANGER-Actions geblockt vor Routing. Watch-only SS58-Validierung über `scalecodec`. Bittensor-spezifische Detektoren: PyPI-Typosquats, Coldkey-Swap-Social-Engineering, Validator-Risiko. Externe Texte sanitisiert am Collector-Boundary (OWASP-Agentic-2026 #1). |
| **Scoring** | 10 Personal-Fit-Kriterien plus chain-derived Competition (basierend auf live `tao_in`-Stake, nicht hardcoded Listen). |
| **Tests** | **547 default tests grün** + **10 Live-Smoke-Tests** gegen echte Endpoints (`pytest -m network`). |
| **Distribution** | `pip install -e .` mit Console-Script `tao-swarm`. Lokal-only, kein Cloud-Telemetry. Optional Streamlit-Dashboard. |
| **Lizenz** | BUSL-1.1, Change Date 2030-01-01 → Apache 2.0. |

---

## Architektur

```
┌──────────────────────────────────────────────────────────────────────┐
│                          User CLI / Dashboard                        │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │ tasks
                                  ▼
                  ┌────────────────────────────────┐
                  │      SwarmOrchestrator         │
                  │  ┌──────────────────────────┐  │
                  │  │  ApprovalGate (SAFE/     │  │ ← blocks DANGER
                  │  │  CAUTION/DANGER)         │  │   before any agent
                  │  └──────────────────────────┘  │   runs
                  │  ┌──────────────────────────┐  │
                  │  │  TaskRouter              │  │
                  │  └──────────────────────────┘  │
                  │  ┌──────────────────────────┐  │
                  │  │  AgentContext (pull-bus) │  │ ← agents pull
                  │  └──────────────────────────┘  │   each other's
                  │  ┌──────────────────────────┐  │   reports
                  │  │  ThreadPoolExecutor      │  │   (parallel=True)
                  │  └──────────────────────────┘  │
                  └─────────────────┬──────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────────┐
        ▼                           ▼                               ▼
  ┌───────────┐               ┌───────────┐                  ┌───────────┐
  │ 15 built- │               │ Collectors│                  │ Plug-ins  │
  │ in Agents │               │  (chain,  │                  │ (your     │
  │           │               │   market, │                  │  repo —   │
  │           │               │   wallet, │                  │  loaded   │
  │           │               │   github) │                  │  via path │
  │           │               │           │                  │  or pip)  │
  └───────────┘               └─────┬─────┘                  └───────────┘
                                    │
                                    ▼
                              ┌──────────┐
                              │ bittensor│
                              │   SDK    │
                              │  v10+    │
                              └──────────┘
```

### Kernprinzipien

| Prinzip | Garantie |
|---------|----------|
| **Read-only by construction** | `chain_readonly._WRITE_METHODS_DENYLIST` + Source-Scan-Test → nie ein Write-Call. |
| **Safety first** | Keine Seeds, keine Private Keys, keine Auto-Trades. ApprovalGate blockt vor Routing. |
| **Mock-first** | Alle Collectors / Agents laufen im Default offline mit deterministischen Fixtures. `--live` opt-in. |
| **Audit trail** | Jeder Run produziert ein `_meta`-Block (`mode: mock|live`, `source`, optionaler `fallback_reason`). |
| **Local-only** | Keine Cloud-Telemetrie. SQLite. |
| **Erweiterbar** | Plug-in-System für eigene Agenten — gleicher Sicherheits-Layer, kein Privilege-Escalation. |

---

## Die 15 Agenten

Alle Agenten in `tao_swarm/agents/` folgen dem SPEC.md-Kontrakt: `run` / `get_status` / `validate_input` + `AGENT_NAME` / `AGENT_VERSION` (Modul-Konstanten).

| # | Agent | Zweck |
|---|-------|-------|
| 1 | `system_check_agent` | Hardware/Software-Readiness. Ruft `nvidia-smi` für VRAM, Treiber, CUDA-Version, Compute-Capability. |
| 2 | `protocol_research_agent` | Bittensor-Protokoll-Wissen (Yuma-Konsens, Subnets, Validator-Permits, …). |
| 3 | `subnet_discovery_agent` | Subnet-Liste mit Kategorisierung & Hardware-Anforderungen. |
| 4 | `subnet_scoring_agent` | Score-Berechnung über `SubnetScorer` (15 Kriterien). |
| 5 | `wallet_watch_agent` | **Watch-only** Adress-Tracking. Nimmt nur SS58, niemals Seed/Key. |
| 6 | `market_trade_agent` | TAO/USD-Analyse, Trade-Ideen mit Reasoning + Risk-Plan. **Paper-Trading-only.** |
| 7 | `risk_security_agent` | Veto-Power. Scant Scam-Indikatoren, **PyPI-Typosquats**, **Coldkey-Swap-Pattern**, Validator-Risiko. |
| 8 | `miner_engineering_agent` | Miner-Setup-Plan. Pullt `system_check.hardware_report` aus Context-Bus. |
| 9 | `validator_engineering_agent` | Validator-Readiness (gleiches Pattern wie Miner). |
| 10 | `training_experiment_agent` | Training-Pläne mit Hardware-Schätzungen. |
| 11 | `infra_devops_agent` | Infra-Empfehlungen (Docker, systemd, Backups). |
| 12 | `dashboard_design_agent` | UX-Vorschläge fürs Streamlit-Dashboard. |
| 13 | `fullstack_dev_agent` | Modul-/Feature-Pläne. |
| 14 | `qa_test_agent` | Secret-Scans, Test-Run, Coverage. |
| 15 | `documentation_agent` | Doku-Audit. |

### Agent-Interaktionsmuster

Agenten lesen und schreiben über den **AgentContext-Bus** (Pull-Modell):

```python
class MyAgent:
    def run(self, task):
        # Pull system_check report from context (set automatically
        # by orchestrator after the first run)
        report = self.context.get(
            "system_check_agent.hardware_report",
            default={},
        )
```

Der Orchestrator publiziert die Agent-Ausgabe nach jedem erfolgreichen Run unter `<agent_name>` ins Context-Objekt. Failed runs (`status: error`) werden übersprungen, damit kein partieller Report gecached wird.

---

## Plug-ins (eigene Agenten)

Du kannst eigene Agenten **außerhalb dieses Repos** schreiben und zur Laufzeit einklinken. Volle Anleitung: `docs/plugins.md`.

### Schnellster Weg: drop-in

```bash
mkdir ~/my-tao-plugins
cd ~/my-tao-plugins

# Generiere ein Skelett (lebt OUTSIDE the swarm repo!)
npx hygen plugin new
# → ~/my-tao-plugins/<name>_agent.py
#   ~/my-tao-plugins/test_<name>_agent.py
#   ~/my-tao-plugins/README.md

# Dem Swarm sagen, wo dein Plug-in liegt
export TAO_PLUGIN_PATHS=~/my-tao-plugins
```

Oder programmatisch:

```python
from src.orchestrator import SwarmOrchestrator, load_plugins

orch = SwarmOrchestrator({"use_mock_data": True})
summary = load_plugins(orch, paths=["/home/user/my-tao-plugins"])
print(summary.as_dict())
# → {"loaded": ["<your_agent>"], "skipped": [], "errors": []}
```

### Production-Weg: pip-installierbar

In deinem eigenen Repo (`pyproject.toml`):

```toml
[project.entry-points."tao.agents"]
my_agent = "my_plugins.my_agent:MyAgent"
```

```bash
pip install -e .
```

Dann:

```python
load_plugins(orch, entry_point_group="tao.agents")
```

### Sicherheits-Garantie

Plug-ins durchlaufen die **gleiche** ApprovalGate wie Built-ins. Loading ändert kein Trust-Level. DANGER-Tasks werden vor dem Plug-in-Code geblockt — eine Regression-Suite (`tests/test_plugin_loader.py::test_plugin_does_not_get_special_classification_treatment`) lockt das ein.

Vollständige Doku: [`docs/plugins.md`](docs/plugins.md).

---

## Projektstruktur

```
TAO_2.0/
├── README.md                        # ← du bist hier
├── KIMI.md                          # Swarm-Verfassung
├── CLAUDE.md                        # Entwickler-Leitfaden für KI-Agenten
├── SPEC.md                          # Architektur-Spezifikation
├── Dockerfile / docker-compose.yml  # Container
├── Makefile                         # make test|lint|bench|run-cli|run-dashboard
├── pytest.ini                       # network-Marker (opt-in via -m network)
├── requirements.txt                 # bittensor>=8,<11; requests; click; pytest; …
├── package.json + .hygen.js         # Hygen-Scaffolding (Node nur fürs Generieren)
│
├── src/
│   ├── orchestrator/
│   │   ├── orchestrator.py          # SwarmOrchestrator (parallel=True opt-in)
│   │   ├── approval_gate.py         # SAFE/CAUTION/DANGER + DANGER additions
│   │   │                            #   (schedule_coldkey_swap, swap_coldkey, …)
│   │   ├── task_router.py           # task_type → agent_name
│   │   ├── context.py               # AgentContext (thread-safe pull-bus)
│   │   └── plugin_loader.py         # NEU: load_plugins(paths|entry_points)
│   │
│   ├── agents/                      # 15 agents — alle SPEC.md-konform
│   │   ├── _hardware.py             # Shared adapter: system_check → hw_profile
│   │   ├── system_check_agent.py
│   │   ├── protocol_research_agent.py
│   │   ├── subnet_discovery_agent.py
│   │   ├── subnet_scoring_agent.py
│   │   ├── wallet_watch_agent.py
│   │   ├── market_trade_agent.py
│   │   ├── risk_security_agent.py   # +Bittensor-Detektoren (PyPI typosquat,
│   │   │                            #  coldkey_swap, validator risk)
│   │   ├── miner_engineering_agent.py
│   │   ├── validator_engineering_agent.py
│   │   ├── training_experiment_agent.py
│   │   ├── infra_devops_agent.py
│   │   ├── dashboard_design_agent.py
│   │   ├── fullstack_dev_agent.py
│   │   ├── qa_test_agent.py
│   │   └── documentation_agent.py
│   │
│   ├── collectors/
│   │   ├── _base.py                 # BaseCollector (use_mock_data + _meta)
│   │   ├── chain_readonly.py        # Real bittensor SDK v10 (SubtensorApi,
│   │   │                            #  metagraph(lite=True), recycle, …)
│   │   ├── market_data.py           # CoinGecko (mock-default)
│   │   ├── wallet_watchonly.py      # Watch-only, deterministische Mocks
│   │   ├── github_repos.py          # GitHub API
│   │   └── subnet_metadata.py
│   │
│   ├── scoring/
│   │   ├── subnet_score.py          # 15 Kriterien (10 personal + 5 chain)
│   │   ├── risk_score.py
│   │   ├── trade_risk_score.py
│   │   ├── miner_readiness_score.py
│   │   └── validator_readiness_score.py
│   │
│   ├── dashboard/
│   │   └── app.py                   # Streamlit (optional, importable ohne dep)
│   │
│   └── cli/
│       └── tao_swarm.py             # CLI mit --live/--mock/--network flags
│
├── _templates/                      # Hygen scaffolds
│   ├── agent/                       # npx hygen agent new
│   ├── collector/                   # npx hygen collector new
│   ├── scoring/                     # npx hygen scoring new
│   ├── test/                        # npx hygen test new
│   ├── doc/                         # npx hygen doc new
│   └── plugin/                      # NEU: npx hygen plugin new
│                                    #   (für Plug-ins außerhalb dieses Repos)
│
├── tests/                           # 368 passing, 1 deselected (live)
│   ├── test_approval_gate.py
│   ├── test_orchestrator_bugfixes.py
│   ├── test_quick_win_fixes.py
│   ├── test_risk_security_agent.py
│   ├── test_risk_bittensor_detectors.py    # PyPI typosquat / coldkey-swap / validator
│   ├── test_task_param_routing.py
│   ├── test_return_shape_consistency.py
│   ├── test_agent_context_bus.py
│   ├── test_validator_context_uptake.py
│   ├── test_cuda_detection.py              # nvidia-smi mock-driven
│   ├── test_base_collector.py
│   ├── test_chain_readonly_collector.py
│   ├── test_chain_readonly_sdk_v10.py      # SubtensorApi v10 path
│   ├── test_collector_mock_paths.py
│   ├── test_concurrent_execution.py
│   ├── test_dashboard_helpers.py
│   ├── test_cli.py
│   ├── test_subnet_score.py
│   ├── test_subnet_score_chain_criteria.py # 5 chain criteria
│   ├── test_plugin_loader.py               # NEU: Plug-in system
│   ├── test_bench_scripts.py
│   ├── test_risk_score.py
│   └── test_wallet_safety.py
│
├── scripts/                         # Benchmark-Suite
│   ├── _bench.py                    # Shared harness (Benchmark, dump_results)
│   ├── bench_approval_gate.py       # 95/4/1, 80/15/5, adversarial mixes
│   ├── bench_agents.py              # cold / warm_same / warm_varied per agent
│   ├── bench_orchestrator.py        # Researcher / Operator / Watcher Personas
│   └── bench_live.py                # Opt-in via TAO_BENCH_LIVE=1
│
├── docs/
│   ├── plugins.md                   # NEU: Plug-in-Guide
│   ├── agent_architecture.md
│   ├── bittensor_basics.md
│   ├── wallet_safety.md
│   ├── risk_model.md
│   ├── subnet_research_method.md
│   ├── trade_research_method.md
│   ├── miner_readiness.md
│   ├── validator_readiness.md
│   └── run_log.md
│
└── bench/
    ├── README.md                    # Realismus-Begründung der Benchmarks
    └── results/                     # Per-Run JSON snapshots (gitignored)
```

---

## Installation

> Mit der Installation akzeptierst du [LICENSE](LICENSE) (BUSL-1.1) und
> [DISCLAIMER.md](DISCLAIMER.md). **Bitte vorher lesen.**

### Voraussetzungen

- Python 3.10+
- Optional: Node.js (nur für Hygen-Scaffolding)
- Optional: NVIDIA GPU + Treiber (für volle CUDA-Detection)
- Optional: Bittensor SDK 10.x — wird lazy importiert, ohne fällt der
  Chain-Collector auf Mock-Fixtures zurück

### Option A: Lokal als pip-Package (empfohlen)

```bash
git clone https://github.com/BEKO2210/TAO_2.0.git
cd TAO_2.0
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt
pip install -e .                        # installiert das Package + Console-Script

cp .env.example .env
pytest -q                               # 547 passing, 11 deselected (network)
tao-swarm --help
```

Das `pip install -e .` legt den `tao-swarm`-Console-Script auf den
PATH. Ab sofort funktionieren Aufrufe wie `tao-swarm subnets`,
`tao-swarm --live market`, `tao-swarm run --task '{"type":"..."}'`.

### Option B: Docker

```bash
git clone https://github.com/BEKO2210/TAO_2.0.git
cd TAO_2.0
make docker-up
```

### Option C: Makefile

```bash
make setup    # erstellt venv, installiert deps, initialisiert DB
make test     # alle Tests ausführen
make bench    # alle Benchmarks (mock-only — netzfrei)
make lint
```

### Live-Smoke-Tests (opt-in, mit Netz)

```bash
# bittensor SDK installieren falls nicht schon vorhanden
pip install bittensor

# Smoke-Tests gegen echte Endpoints (Mainnet, Subscan, CoinGecko)
pytest -m network tests/test_live_smoke.py -v
# → 10 passed in ~30s
```

---

## Quick Start

```bash
# 1) System-Check (mock — keine Netz-Calls)
tao-swarm check

# 2) Live-Subnet-Liste von Mainnet (129 reale Subnets)
tao-swarm --live subnets --limit 10
#   ID  Name                 Sym     TAO_in       Volume  Description
# ----  -------------------- --- ---------- ------------  ------------------
#    1  Apex                   α     28,580      776,968  Open competitions for…
#    4  Targon                 δ    133,782    2,011,066  Incentivized Compute…
#    8  Vanta                  θ     85,632    1,307,691  The first decentral…
# …
# Total: 129 subnets

# 3) Live-Markt (CoinGecko)
tao-swarm --live market

# 4) Subnet 1 (Apex) gegen Live-Chain scoren
tao-swarm --live score 1

# 5) Wallet beobachten (watch-only, SS58 prefix-42 verifiziert)
tao-swarm watch 5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy --label cold1

# 6) Risk-Review eines Texts (Social-Engineering-Detector)
tao-swarm risk --content "Schedule_coldkey_swap to 5XYZ... within 5 days"
# → DANGER: coldkey_swap_social_engineering CRITICAL

# 7) Vollständigen Orchestrator-Run gegen Live-Chain
tao-swarm --live run --task '{"type": "subnet_discovery"}'
# Status: success | Agent: subnet_discovery_agent | output: 129 subnets

# 8) DANGER-Action testen — wird gate-blockiert, nicht ausgeführt
tao-swarm --live run --task '{"type": "execute_trade", "amount": 100}'
# Status: blocked | Classification: DANGER | output: plan only

# 9) Dashboard starten (Streamlit optional)
tao-swarm dashboard
```

---

## CLI-Modi: `--mock` vs `--live`

| Flag | Wirkung |
|------|---------|
| (default) | Mock-Daten, keine Netzwerk-Calls. |
| `--mock` | Explizit Mock, auch wenn `TAO_USE_MOCK=0` gesetzt ist. |
| `--live` | Live-Daten von realen Endpoints (CoinGecko, GitHub, finney). |
| `--network finney` | Implies `--live`, default-Netzwerk für SDK. |
| `--network test` | Implies `--live`, Bittensor testnet. |
| `--network mock` | Forces mock. |

Jedes Command zeigt einen **Mode-Banner** in der Ausgabe:

```
=== Bittensor Subnets ===
  MODE: live (network=finney)  — pass --mock for offline fixtures
```

Wenn der Live-Pfad fehlschlägt (z.B. bittensor SDK nicht installiert), gibt's einen klaren Fallback-Hinweis:

```
  fallback: bittensor SDK not installed; install via `pip install bittensor`
```

---

## ApprovalGate (Safety-Layer)

Jede Action wird klassifiziert vor jedem Routing:

| Klasse | Beispiele | Verhalten |
|--------|-----------|-----------|
| **SAFE** | `read`, `analyze`, `subnet_discovery`, `wallet_watch`, `paper_trade` | Sofortige Ausführung. |
| **CAUTION** | `install_deps`, `connect_api`, `write_file` | Loggt Warnung, läuft. Manuelle Override möglich. |
| **DANGER** | `sign_transaction`, `stake`, `unstake`, `transfer`, `execute_trade`, `create_wallet`, `show_mnemonic`, **`schedule_coldkey_swap`**, **`swap_coldkey`**, **`swap_hotkey`** | Geblockt. Liefert Plan-only Output. |

DANGER-Tasks erreichen niemals den TaskRouter — die Klassifikation läuft **vor** dem Routing.

```python
out = orch.execute_task({"type": "execute_trade", "amount": 100})
# {"status": "blocked",
#  "classification": "DANGER",
#  "executed": False,
#  "output": {"plan": {...}, "note": "This is a DANGER action..."}}
```

---

## Bittensor-spezifische Sicherheits-Detektoren

Drei real-incident-driven Detektoren in `RiskSecurityAgent` (alle in `general_review` automatisch aktiv):

### 1. PyPI-Typosquat / poisoned-version

Catches:
- **Mai 2024:** `bittensor==6.12.2` (drainte ~$8M / 32k TAO via patched stake_extrinsic)
- **Aug 2025:** `bitensor`, `bittenso`, `bittenso-cli`, `qbittensor`, `bittensor_cli` (Underscore-Variante), `bittensoor`, `bittensr`
- `--index-url` nicht-pypi.org → CRITICAL (sideload-Vektor der Aug 2025 Kampagne)

### 2. Coldkey-Swap Social Engineering

`schedule_coldkey_swap` ist 5-day-arbitrierter, **irreversibler** Swap. OTF/Latent kann nicht eingreifen. Detector:
- Marker (`schedule_coldkey_swap` o.ä.) + neue Destination-SS58 + Urgency-Phrasing → **CRITICAL**
- Marker + watchlist-Adresse → **HIGH** (kann legit sein)
- Nur Marker, keine Adresse → **MEDIUM** (Vorbote für Follow-up)

```python
agent.scan_coldkey_swap_pattern(
    "schedule_coldkey_swap to 5DAA... within 5 days",
    watchlist_addresses={"5DAA..."},   # downgrade
)
```

### 3. Validator Risk Score

0..100 Score + verdict für Delegations-Entscheidungen:
- Hotkey-Alter < ~28 Tage (kein Slashing-Track-Record)
- Kein Axon serving (publiziert nichts)
- `vtrust = 0` auf Subnets mit Permit (likely weight-copying)
- Take-Spike (bait-then-raise)
- Take > 18%
- Pending coldkey-swap → automatisch **STOP**

---

## Subnet-Scoring (15 Kriterien)

`SubnetScorer` produziert einen 0–100 Score über **15 gewichtete Kriterien**:

### Personal-fit (50% Gesamtgewicht)
| Kriterium | Gewicht |
|-----------|--------:|
| `technical_fit` | 8% |
| `hardware_fit` | 8% |
| `competition` | 7% |
| `reward_realism` | 6% |
| `doc_quality` | 6% |
| `setup_complexity` | 5% |
| `maintenance` | 5% |
| `security_risk` | 3% |
| `learning_value` | 1% |
| `long_term` | 1% |

### Chain-derived (50% Gesamtgewicht — neu in PR C)
| Kriterium | Gewicht | Quelle |
|-----------|--------:|--------|
| `taoflow_health` | 15% | Net stake flow EMA (post-Nov-2025 Taoflow regime) |
| `validator_concentration` | 10% | `1 - HHI` auf Validator-Stake |
| `weight_consensus_divergence` | 10% | `1 - mean pairwise cosine` weight matrix; +20 für commit-reveal |
| `miner_slot_liveness` | 8% | `active / registered` ratio |
| `owner_liveness` | 7% | Tage seit letztem Commit/Hparam-Change (Decay) |

Output:

```python
scorer.score_subnet({"netuid": 12, "metagraph": {...}, "taoflow": {...}})
# {
#   "netuid": 12,
#   "total_score": 87.4,
#   "breakdown": {"technical_fit": 75.0, ..., "taoflow_health": 95.2, ...},
#   "weights": {...},
#   "recommendation": {"label": "Validator-Kandidat", ...}
# }
```

---

## Wallet-Sicherheit

### Modi

| Modus | Verhalten |
|-------|-----------|
| **`NO_WALLET`** (default) | Kein Wallet-Kontext. Pure Read-Only. |
| **`WATCH_ONLY`** | Public SS58-Adressen, keine Keys. Nur read-Operationen. |
| **`MANUAL_SIGNING`** | Keys liegen außerhalb des Systems. User signiert manuell. **Wir signieren niemals.** |

### Was das System NIEMALS tut

- ❌ Seed Phrases anfordern, speichern, loggen, übertragen
- ❌ Private Keys anfordern, speichern, loggen, übertragen
- ❌ Trades, Stakes, Unstakes, Transfers automatisch ausführen
- ❌ Transactions auto-signen
- ❌ `schedule_coldkey_swap` ohne explizite manuelle Bestätigung

### Strukturelle Garantie

`tao_swarm/collectors/chain_readonly.py` enthält `_WRITE_METHODS_DENYLIST` (`add_stake`, `unstake`, `transfer`, `set_weights`, `commit_weights`, …). Ein Source-Scan-Test (`test_collector_source_does_not_call_any_write_method`) failt den Build, wenn ein Write-Call jemals reinrutscht.

---

## Benchmarks

```bash
make bench           # alle (mock — keine Netz-Calls)
make bench-live      # opt-in: hits real upstreams (CoinGecko, finney, GitHub)
```

Vier Workload-Profile in `scripts/bench_*.py`:

| Workload | Was wird gemessen |
|----------|-------------------|
| **`bench_approval_gate`** | Mixe: research_session (95/4/1 SAFE/CAUTION/DANGER), operator_setup (80/15/5), adversarial DANGER-only |
| **`bench_agents`** | Per-Agent: cold (1× fresh) + warm_same + warm_varied |
| **`bench_orchestrator`** | 3 Personas: Researcher / Operator / Watcher + DANGER-blocked + bare overhead |
| **`bench_live`** (opt-in) | Echte Round-Trip-Latenz gegen finney / CoinGecko / GitHub |

Baseline (Python 3.11, kein GPU):

```
ApprovalGate: 600k–2.1M classifications/sec (no bottleneck)
Agents:       most < 50µs warm; system_check ~30ms (subprocess-bound)
Orchestrator: researcher 78µs/task, watcher 61µs/task warm
DANGER block: 5.8µs/task (gate is essentially free)
```

JSON snapshots werden nach `bench/results/<category>-<timestamp>.json` geschrieben (gitignored).

---

## Tests entwickeln

```bash
pytest -q                            # 368 passing, 1 deselected
pytest tests/test_approval_gate.py
pytest -m network                    # opt-in: live integration tests
pytest -k coldkey_swap               # focused
```

**Convention für neue Agenten / Collectors / Scorer:** generiere via Hygen, nie hand-rollen.

```bash
npx hygen agent new        # built-in agent (in-tree)
npx hygen collector new
npx hygen scoring new
npx hygen test new
npx hygen doc new
npx hygen plugin new       # external plug-in (out-of-tree, dein Repo)
```

---

## Sicherheitshinweise

### Kritische Regeln (von ApprovalGate erzwungen)

1. **NIEMALS** Seed Phrases anfordern / speichern / loggen / übertragen
2. **NIEMALS** Private Keys anfordern / speichern / loggen / übertragen
3. **NIEMALS** Trades, Stakes, Transfers automatisch ausführen
4. **NIEMALS** Transactions auto-signen
5. DANGER-Aktionen geben nur Pläne aus, niemals Ausführung
6. Default-Modus ist `NO_WALLET`. WATCH_ONLY akzeptiert nur public SS58-Adressen.
7. Keine Cloud-Telemetrie. Alles lokal.

### Bittensor-spezifische Regeln (in `RiskSecurityAgent` enkodiert)

- Bekannte malicious PyPI-Pakete (May 2024 + Aug 2025 Vorfälle) werden CRITICAL geflaggt
- `schedule_coldkey_swap` Social-Engineering wird CRITICAL geflaggt
- Validator-Delegation-Risiko wird in 6 Faktoren bewertet
- Pending coldkey-swap auf einem Validator → automatischer STOP

### Wenn dir das nicht passt

Plug-in schreiben, das deine eigenen Detektoren / Heuristiken implementiert. Plug-ins durchlaufen die gleiche Gate — du kannst die Sicherheits-Layer nicht umgehen, aber du kannst sie ergänzen.

---

## Disclaimer

> **Dies ist eine Zusammenfassung. Die volle, rechtsverbindliche Fassung steht in [DISCLAIMER.md](DISCLAIMER.md). Vor der Nutzung lesen.**

Dieses System ist **kein Finanzberatungstool**, **keine Trading-Plattform**, und **kein Wallet-Manager**. Es ist ein lokales Recherche-Tool, das Daten aus öffentlichen Quellen aggregiert und Entscheidungs-Pläne (nicht Entscheidungen) produziert.

- **Keine Finanz-, Investment-, Steuer- oder Rechtsberatung.** Outputs sind maschinengeneriert und unkuratiert.
- **Use at your own risk.** Bittensor- und Kryptowährungs-Investments können dein gesamtes Kapital kosten. Märkte sind volatil, Smart Contracts können Bugs haben, Endpoints können falsche Daten liefern, Off-Chain-Daten können stale oder manipuliert sein.
- **Verify everything.** Daten aus Live-Collectors (`--live`) werden gecached, können stale sein, und durch Upstream-Bugs / Rate-Limits / SSL-Fehler verfälscht werden.
- **No warranty.** Die Software wird "AS IS" bereitgestellt. Siehe [LICENSE](LICENSE) und [DISCLAIMER.md](DISCLAIMER.md). Keine Haftung für direkte, indirekte, zufällige, Folge- oder Strafschäden.
- **Compliance ist deine Verantwortung.** Du bist verantwortlich für die Einhaltung aller Gesetze und Regelungen in deiner Jurisdiktion (Wertpapierrecht, AML/KYC, Steuern, Sanktionen, Datenschutz, Terms-of-Service der Drittanbieter-Endpoints).

Die in `RiskSecurityAgent` codierten Bittensor-spezifischen Detektoren basieren auf real dokumentierten Vorfällen (Mai 2024, Aug 2025, Apr 2026 Covenant AI Exit). Sie sind **nicht erschöpfend** — neue Angriffsvektoren entstehen ständig. Treat the swarm's verdicts as **input to** your decision, never as **the** decision.

---

## Lizenz

**Business Source License 1.1** — siehe [`LICENSE`](LICENSE) für den
vollständigen Text inklusive *Additional Use Grant* (Non-Production
Use frei) und Change Date (2030-01-01 → Apache 2.0).

Production-, kommerzielle oder Hosting-Nutzung erfordert eine separate
schriftliche Lizenz. Anfragen über GitHub Issues.

## Beiträge

Issues und PRs willkommen. Bitte vor dem Einreichen:

```bash
make test                          # 368 passing minimum
make lint                          # ruff check
npx hygen <kind> new               # für neue Module — KEIN Hand-Roll
```

Sicherheitskritische Änderungen (ApprovalGate, RiskSecurityAgent, chain_readonly write-deny): bitte ausführlich im PR-Body begründen + Regressions-Test mitliefern.
