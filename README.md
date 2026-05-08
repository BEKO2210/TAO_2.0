# TAO / Bittensor Multi-Agent Intelligence System

> Ein dezentrales Multi-Agentensystem zur Recherche, Analyse und Entscheidungsunterstuetzung im Bittensor-Oekosystem. 15 spezialisierte Agenten arbeiten als Schwarm unter zentraler Governance.

**WARNUNG: Dieses System fuehrt KEINE automatischen Transaktionen durch, speichert KEINE Private Keys und erteilt KEINE Finanzberatung.**

---

## Inhaltsverzeichnis

- [Systemuebersicht](#systemuebersicht)
- [Die 15 Agenten](#die-15-agenten)
- [Projektstruktur](#projektstruktur)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Wallet-Sicherheit](#wallet-sicherheit)
- [Approval Gate](#approval-gate)
- [Technischer Stack](#technischer-stack)
- [Sicherheitshinweise](#sicherheitshinweise)
- [Disclaimer](#disclaimer)

---

## Systemuebersicht

Das TAO/Bittensor Multi-Agent System ist ein Python-basiertes Framework, das 15 spezialisierte KI-Agenten als koordinierten Schwarm betreibt. Jedes Mitglied des Schwarms hat eine klar definierte Rolle, Kompetenzen und Einschraenkungen. Ein zentraler **Orchestrator** koordiniert alle Aktionen, ein **Risk Agent** ueberwacht jede Entscheidung, und ein **Approval Gate** stellt sicher, dass keine kritische Aktion ohne explizite Zustimmung erfolgt.

### Kernprinzipien

| Prinzip | Beschreibung |
|---------|-------------|
| **Safety First** | Keine Private Keys im System, keine automatischen Transaktionen |
| **Governance** | Jede Aktion muss durch das Approval Gate |
| **Transparenz** | Alle Entscheidungen werden dokumentiert und nachvollziehbar |
| **Dezentralitaet** | Jeder Agent ist autonom, aber dem Schwarm verantwortlich |
| **Verifizierbarkeit** | Alle Datenquellen werden protokolliert und ueberpruefbar |

---

## Die 15 Agenten

| # | Agent | Rolle | Kuerzel |
|---|-------|-------|---------|
| 1 | **Orchestrator** | Zentrale Koordination, Task-Routing, Entscheidungsaggregation | ORCH |
| 2 | **Risk & Safety Agent** | Bewertet jede Aktion auf Risiko, kann Veto einlegen, Safety-Enforcer | RISK |
| 3 | **Wallet Agent** | Wallet-Status anzeigen, Transaktionen vorbereiten (NICHT signieren) | WALL |
| 4 | **Research Agent** | Allgemeine Recherche zu Bittensor, Protokoll-Upgrades, oekosystemweite News | RES |
| 5 | **Subnet Research Agent** | Tiefe Analyse einzelner Subnets, Miner-Performance, Deregistration-Risiken | SUB |
| 6 | **Trade Research Agent** | Marktanalyse, Preis-Trends, Handelsideen mit Risikobewertung | TRD |
| 7 | **Stake/Unstake Agent** | Staking-Opportunitaeten analysieren, Unstake-Risiken bewerten | STK |
| 8 | **Transfer Agent** | TAO-Transfer-Vorschlaege erstellen, Adressvalidierung | XFR |
| 9 | **Mempool Monitor Agent** | Beobachtet das Bittensor-Mempool auf unbestaetigte Transaktionen | MEMP |
| 10 | **Subnet Entry Agent** | Analysiert Subnet-Entry-Kosten, Chancen, Wettbewerb | SNE |
| 11 | **Miner Agent** | Evaluiert Mining-Moeglichkeiten, Hardware-Anforderungen, Rentabilitaet | MIN |
| 12 | **Validator Agent** | Prueft Validator-Anforderungen, Stake-Bedarf, Belohnungsstruktur | VAL |
| 13 | **Code Review Agent** | Prueft alle Code-Aenderungen, Sicherheitspruefung, Audit-Trail | CODE |
| 14 | **Data Validator Agent** | Validiert alle externen Daten auf Konsistenz und Quellenqualitaet | DATA |
| 15 | **Meta-Agent** | Verbessert das System selbst: Prompt-Optimierung, Prozess-Reviews, Lernen | META |

### Agent-Interaktionsmodell

```
                    +------------------+
                    |   Orchestrator   |
                    |    (ORCH)        |
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v------+ +-----v------+ +----v---------+
     |  Risk Agent   | |  Meta-     | |  Code Review |
     |  (Veto-Recht) | |  Agent     | |  Agent       |
     +---------------+ +------------+ +--------------+
              |
   +----------+-----------+----------+----------+----------+
   |          |          |          |          |          |
+--v---+ +---v----+ +---v----+ +-v-------+ +-v------+ +-v-------+
|Research| |Subnet  | |Trade   | |Stake/  | |Transfer| |Mempool |
|Agent   | |Research| |Research| |Unstake | |Agent   | |Monitor |
+--------+ +--------+ +--------+ +--------+ +--------+ +--------+
                                              |
                              +---------------+---------------+
                              |               |               |
                         +----v-----+   +-----v----+   +------v-----+
                         |Subnet    |   |Miner     |   |Validator   |
                         |Entry     |   |Agent     |   |Agent       |
                         |Agent     |   |          |   |            |
                         +----------+   +----------+   +------------+
```

---

## Projektstruktur

```
tao-bittensor-agents/
├── README.md                  # Diese Datei
├── KIMI.md                    # Swarm-Verfassung und Systemregeln
├── .env.example               # Umgebungsvariablen-Template
├── .gitignore                 # Git-Ausschlussregeln
├── docker-compose.yml         # Docker-Compose Konfiguration
├── Dockerfile                 # Container-Definition
├── Makefile                   # Build- und Run-Targets
├── requirements.txt           # Python-Abhaengigkeiten
├── pyproject.toml             # Projekt-Metadaten
│
├── src/                       # Quellcode
│   ├── __init__.py
│   ├── orchestrator.py        # Zentrale Steuerung
│   ├── agents/                # Agent-Implementierungen
│   │   ├── __init__.py
│   │   ├── base_agent.py      # Abstrakte Basisklasse
│   │   ├── risk_agent.py
│   │   ├── wallet_agent.py
│   │   ├── research_agent.py
│   │   ├── subnet_research_agent.py
│   │   ├── trade_research_agent.py
│   │   ├── stake_agent.py
│   │   ├── transfer_agent.py
│   │   ├── mempool_agent.py
│   │   ├── subnet_entry_agent.py
│   │   ├── miner_agent.py
│   │   ├── validator_agent.py
│   │   ├── code_review_agent.py
│   │   ├── data_validator_agent.py
│   │   └── meta_agent.py
│   ├──
│   ├── core/                  # Kernkomponenten
│   │   ├── __init__.py
│   │   ├── config.py          # Konfigurationsmanagement
│   │   ├── logger.py          # Logging-Infrastruktur
│   │   ├── database.py        # SQLite-Persistenz
│   │   ├── approval_gate.py   # Approval-Gate-Logik
│   │   ├── risk_model.py      # Risikobewertung
│   │   └── exceptions.py      # Custom Exceptions
│   ├──
│   ├── wallet/                # Wallet-Integration
│   │   ├── __init__.py
│   │   ├── wallet_manager.py  # Wallet-Verwaltung (Watch-Only)
│   │   ├── address_book.py    # Adressverzeichnis
│   │   └── transaction_builder.py  # Tx-Bau (ohne Signing)
│   ├──
│   ├── bittensor/             # Bittensor-Interface
│   │   ├── __init__.py
│   │   ├── subtensor_client.py
│   │   ├── subnet_explorer.py
│   │   └── chain_queries.py
│   ├──
│   ├── data/                  # Datenlayer
│   │   ├── __init__.py
│   │   ├── sources.py         # Datenquellen-Adapter
│   │   ├── cache.py           # Caching-Layer
│   │   └── validators.py      # Datenvalidierung
│   └──
│   └── utils/                 # Hilfsfunktionen
│       ├── __init__.py
│       ├── formatters.py
│       ├── validators.py
│       └── helpers.py
│
├── dashboard/                 # Streamlit-Dashboard (optional)
│   ├── app.py
│   ├── pages/
│   │   ├── overview.py
│   │   ├── agents.py
│   │   ├── wallet.py
│   │   ├── subnets.py
│   │   └── reports.py
│   └── components/
│       ├── sidebar.py
│       ├── metrics.py
│       └── charts.py
│
├── docs/                      # Dokumentation
│   ├── bittensor_basics.md
│   ├── agent_architecture.md
│   ├── wallet_safety.md
│   ├── risk_model.md
│   ├── subnet_research_method.md
│   ├── trade_research_method.md
│   ├── miner_readiness.md
│   ├── validator_readiness.md
│   └── run_log.md
│
├── data/                      # Laufzeitdaten
│   ├── agents.db              # SQLite-Datenbank
│   ├── wallet_state.json      # Wallet-Cache (nur Public)
│   └── reports/               # Generierte Reports
│
├── scripts/                   # Hilfsskripte
│   ├── setup.sh
│   ├── backup.sh
│   └── health_check.sh
│
├── tests/                     # Test-Suite
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_agents/
│   ├── test_core/
│   ├── test_wallet/
│   └── integration/
│
├── logs/                      # Log-Dateien
├── config/                    # Konfigurationsdateien
│   ├── agents.yaml
│   └── thresholds.yaml
└── tmp/                       # Temporaere Dateien
```

---

## Installation

### Option A: Lokale Installation (pip)

**Voraussetzungen:**
- Python 3.11 oder hoeher
- pip oder uv
- Git

```bash
# Repository klonen
git clone <repository-url>
cd tao-bittensor-agents

# Virtuelle Umgebung erstellen (empfohlen)
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate  # Windows

# Abhaengigkeiten installieren
pip install -r requirements.txt

# Umgebungsvariablen konfigurieren
cp .env.example .env
# .env mit Editor oeffnen und anpassen

# Datenbank initialisieren
python -m src.core.database migrate

# System starten
python -m src.orchestrator --mode cli
```

**requirements.txt** (Auszug der wichtigsten Pakete):
```
bittensor>=8.0.0
asyncio>=3.4.3
aiohttp>=3.9.0
sqlite3-python
pydantic>=2.5.0
pyyaml>=6.0.1
requests>=2.31.0
streamlit>=1.28.0
plotly>=5.18.0
pandas>=2.1.0
numpy>=1.26.0
python-dotenv>=1.0.0
structlog>=23.2.0
pytest>=7.4.0
pytest-asyncio>=0.21.0
mypy>=1.7.0
ruff>=0.1.6
```

### Option B: Docker (empfohlen)

**Voraussetzungen:**
- Docker Engine 24.0+
- Docker Compose 2.20+

```bash
# Repository klonen
git clone <repository-url>
cd tao-bittensor-agents

# Environment konfigurieren
cp .env.example .env
# .env anpassen

# Container bauen und starten
make docker-up

# Oder manuell:
docker compose build
docker compose up -d

# Logs anzeigen
docker compose logs -f app

# Dashboard oeffnen (wenn aktiviert)
# http://localhost:8501
```

### Option C: Makefile (schnellster Weg)

```bash
# Komplettes Setup
make setup

# System starten
make run-cli

# Dashboard starten
make run-dashboard

# Alle verfuegbaren Targets anzeigen
make help
```

---

## Quick Start

### Schritt 1: System ohne Wallet starten (empfohlen fuer den Einstieg)

```bash
# Im .env File: WALLET_MODE=NO_WALLET
python -m src.orchestrator --mode cli

# Der Orchestrator startet alle Agenten im Beobachtungsmodus.
# Es werden keine Wallet-Daten benoetigt.
```

### Schritt 2: Mit Watch-Only Wallet

```bash
# Public Address in .env eintragen
# WALL
python -m src.orchestrator --mode cli --wallet-mode watch_only

# Das System zeigt Balancen und History an,
# kann aber keine Transaktionen signieren.
```

### Schritt 3: Research-Abfragen

```bash
# Bittensor-Allgemeinrecherche starten
> orchestrator: research "latest Bittensor protocol upgrades"

# Subnet-Analyse
> orchestrator: analyze subnet 1

# Trade-Marktanalyse
> orchestrator: trade_analysis TAO/USDT

# Alle Befehle sind interaktiv und zeigen Ergebnisse sofort.
```

### Schritt 4: Mit Dashboard

```bash
make run-dashboard
# Oeffnet Streamlit auf http://localhost:8501
```

---

## Wallet-Sicherheit

Das System unterstuetzt **drei Wallet-Modi**, die ueber die Umgebungsvariable `WALLET_MODE` konfiguriert werden:

### Modus 1: NO_WALLET (Standard)
- Keine Wallet-Verbindung
- Reine Recherche und Analyse
- Keine Transaktionsvorbereitung moeglich
- **Empfohlen fuer: Erste Tests, Recherche-Only-Nutzung**

### Modus 2: WATCH_ONLY
- Public Address wird ueberwacht
- Balance, Stake, History werden angezeigt
- Transaktionen werden vorbereitet, aber NICHT signiert
- **Empfohlen fuer: Tae gliche Ueberwachung, Analyse**

### Modus 3: MANUAL_SIGNING
- Transaktionen werden im System vorbereitet
- Der Nutzer muss die Transaktion MANUELL in einer externen Wallet signieren
- Kein Private Key verlaesst jemals die externe Wallet
- **Empfohlen fuer: Aktive Teilnahme mit hoechster Sicherheit**

### Was DAS SYSTEM NIEMALS tut:
- **NIEMALS** Private Keys speichern
- **NIEMALS** Seed Phrases speichern oder abfragen
- **NIEMALS** automatisch Transaktionen signieren
- **NIEMALS** Private Keys in Logs oder Datenbank speichern
- **NIEMALS** eine Verbindung zu Hot Wallets herstellen

### Was DAS SYSTEM tut:
- Public Addresses anzeigen und validieren
- Transaktionen als JSON vorbereiten (fuer manuelles Signing)
- Balances und Stakes anzeigen
- Explorer-Links generieren
- Paper-Trading-Simulation durchfuehren

---

## Approval Gate

Jede vom System vorgeschlagene Aktion durchlaeuft das **Approval Gate**. Es gibt drei Stufen:

### SAFE (Autonome Ausfuehrung)
- Recherche-Abfragen
- Datenanalysen
- Paper-Trading-Simulationen
- Status-Abfragen
- **Keine manuelle Genehmigung erforderlich**

### CAUTION (Nutzer-Bestaetigung erforderlich)
- Transaktionsvorschlaege (vorbereitet, nicht signiert)
- Stake/Unstake-Empfehlungen
- Subnet-Entry-Vorschlaege
- Konfigurationsaenderungen
- **Nutzer muss explizit mit "ja" bestaetigen**

### DANGER (Doppel-Bestaetigung + Risk Agent Veto)
- Mainnet-Registrierungen
- Transfers ueber konfigurierten Schwellenwert
- Unstake mit Deregistration-Risiko
- Alle Aktionen mit Risk-Score > 70
- **Erfordert: Risk Agent Review + Nutzer-Bestaetigung + Zeitverzoegerung**

### Approval Gate Fluss

```
Agent schlaegt Aktion vor
         |
         v
+------------------+
|  Risk Agent      |
|  bewertet Aktion |
+--------+---------+
         |
   +-----v------+
   | Risk-Score |
   | berechnen  |
   +-----+------+
         |
    +----v----+---------+----------+
    |         |         |          |
    v         v         v          v
  SAFE     CAUTION   DANGER   VETO
    |         |         |          |
    v         v         v          v
 Autonom  Nutzer    Nutzer +   Aktion
 ausf.   bestaet.   Zeit +     BLOCKIERT
                    Risk
```

---

## Technischer Stack

| Komponente | Technologie | Zweck |
|------------|-------------|-------|
| **Sprache** | Python 3.11+ | Hauptentwicklungssprache |
| **Framework** | Bittensor SDK 8.0+ | Blockchain-Interface |
| **Datenbank** | SQLite 3 | Lokale Persistenz |
| **Dashboard** | Streamlit | Web-UI |
| **Visualisierung** | Plotly | Charts und Graphen |
| **Datenverarbeitung** | Pandas, NumPy | Analyse und Statistik |
| **HTTP-Client** | aiohttp | Asynchrone API-Calls |
| **Config** | Pydantic, PyYAML | Konfigurationsmanagement |
| **Logging** | structlog | Strukturiertes Logging |
| **Testing** | pytest, pytest-asyncio | Test-Suite |
| **Linting** | ruff, mypy | Code-Qualitaet |
| **Container** | Docker, Docker Compose | Deployment |
| **Orchestrierung** | Eigenimplementierung | Agent-Koordination |

---

## Sicherheitshinweise

### KRITISCHE REGELN

**1. Private Keys**
> **Dieses System fragt NIE nach Private Keys. Geben Sie NIEMALS einen Private Key in das System ein.**

**2. Automatische Transaktionen**
> **Dieses System fuehrt KEINE automatischen Transaktionen durch. Jede Transaktion erfordert manuelle Bestaetigung.**

**3. Mainnet-Registrierung**
> **Eine Mainnet-Registrierung erfolgt NUR nach expliziter Doppel-Bestaetigung und Risk Agent Review.**

**4. Seed Phrases**
> **Seed Phrases werden NIEMALS abgefragt, gespeichert oder verarbeitet.**

**5. Finanzberatung**
> **Dieses System erteilt KEINE Finanzberatung. Alle Ausgaben sind Recherche-Ergebnisse.**

### Zusaetzliche Sicherheitsmassnahmen

- Alle externen Daten werden durch den Data Validator Agent geprueft
- Der Code Review Agent prueft jede Code-Aenderung
- Alle Aktionen werden in der SQLite-Datenbank protokolliert
- Das System laeuft standardmaessig im NO_WALLET-Modus
- Logs enthalten niemals sensitive Daten
- Die Datenbank enthaelt niemals Private Keys oder Seed Phrases

---

## Disclaimer

> **HAFTUNGSAUSSCHLUSS**
>
> Dieses System dient ausschliesslich zu Recherche- und Analysezwecken im Bittensor-Oekosystem. Es stellt **keine Finanzberatung** dar und sollte nicht als Grundlage fuer Anlageentscheidungen verwendet werden.
>
> - Der Autor uebernimmt keine Haftung fuer finanzielle Verluste
 - Alle Informationen werden ohne Gewaehr bereitgestellt
 - Kryptowaehrungen sind hochspekulativ und koennen zu Totalverlust fuehren
 - Die Nutzung erfolgt auf eigenes Risiko
 - Es werden keine Garantien fuer die Richtigkeit der Daten gegeben
>
> **Bitte konsultieren Sie einen qualifizierten Finanzberater, bevor Sie Anlageentscheidungen treffen.**

---

## Lizenz

MIT License - Siehe [LICENSE](LICENSE) fuer Details.

---

## Kontakt und Beitraege

- **Issues:** Bitte ueber GitHub Issues melden
- **Beitraege:** Pull Requests sind willkommen (siehe CONTRIBUTING.md)
- **Fragen:** Diskussionen im GitHub Discussions-Tab

**Letzte Aktualisierung:** 2025-01-15
**Version:** 0.1.0-alpha
