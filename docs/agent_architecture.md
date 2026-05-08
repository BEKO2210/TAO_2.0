# Agent-Architektur

> Dieses Dokument beschreibt die technische Architektur des Multi-Agent Systems. Es erklaert den Aufbau des Orchestrators, das Agent-Interface, den Datenfluss und die Konfliktloesungsmechanismen.

---

## Inhaltsverzeichnis

- [Orchestrator-Komponenten](#orchestrator-komponenten)
- [Agent-Interface](#agent-interface)
- [Datenfluss zwischen Agenten](#datenfluss-zwischen-agenten)
- [Task-Routing](#task-routing)
- [Konfliktloesung](#konfliktloesung)
- [Agent-Kommunikationsdiagramm](#agent-kommunikationsdiagramm)
- [Datenpersistenz](#datenpersistenz)
- [Fehlerbehandlung](#fehlerbehandlung)

---

## Orchestrator-Komponenten

Der **Orchestrator** ist das zentrale Steuerungselement des gesamten Systems. Er besteht aus mehreren Komponenten:

### Architektur-Uebersicht

```
+-----------------------------------------------------------+
|                      ORCHESTRATOR                         |
+-----------------------------------------------------------+
|                                                           |
|  +------------------+    +-----------------------------+  |
|  |  Input Parser    |    |  Task Router                |  |
|  |  - CLI Input     |--->|  - Bestimmt Ziel-Agent      |  |
|  |  - API Input     |    |  - Parallelisierung         |  |
|  |  - File Input    |    |  - Priorisierung            |  |
|  +------------------+    +-------------+---------------+  |
|                                         |                 |
|  +------------------+                   v                 |
|  |  Result          |    +-----------------------------+  |
|  |  Aggregator      |<---|  Execution Engine            |  |
|  |  - Merge Results |    |  - Agent ausfuehren         |  |
|  |  - Format Output |    |  - Timeout ueberwachen      |  |
|  |  - Risk Check    |    |  - Retry-Logik              |  |
|  +--------+---------+    +-----------------------------+  |
|           |                                               |
|  +--------v---------+    +-----------------------------+  |
|  |  Approval Gate   |    |  Safety Layer               |  |
|  |  - SAFE/CAUTION/ |<---|  - Risk Agent Integration   |  |
|  |    DANGER/VETO   |    |  - Veto-Pruefung            |  |
|  |  - Nutzer-Abfrage|    |  - Compliance-Check         |  |
|  +--------+---------+    +-----------------------------+  |
|           |                                               |
|  +--------v---------+                                     |
|  |  Output Handler  |                                     |
|  |  - CLI Output    |                                     |
|  |  - Log Output    |                                     |
|  |  - Dashboard     |                                     |
|  +------------------+                                     |
|                                                           |
+-----------------------------------------------------------+
```

### Komponenten im Detail

#### 1. Input Parser

```python
class InputParser:
    """Parsed und validiert alle Eingaben an das System."""

    def parse(self, raw_input: str) -> ParsedTask:
        """
        Erkennt den Task-Typ und extrahiert Parameter.

        Returns:
            ParsedTask mit:
            - task_type: RESEARCH | TRADE | STAKE | TRANSFER | ...
            - target_agent: Empfohlener Ziel-Agent
            - parameters: Extrahierte Parameter
            - priority: LOW | NORMAL | HIGH | CRITICAL
        """

    def validate(self, task: ParsedTask) -> ValidationResult:
        """
        Prueft, ob die Eingabe valide ist.
        Keine sensiblen Daten enthalten.
        """
```

#### 2. Task Router

```python
class TaskRouter:
    """Entscheidet, welcher Agent fuer eine Aufgabe zustaendig ist."""

    ROUTING_TABLE = {
        "research":        ["research_agent", "subnet_research_agent"],
        "analyze_subnet":  ["subnet_research_agent", "subnet_entry_agent"],
        "trade":           ["trade_research_agent"],
        "stake":           ["stake_agent"],
        "unstake":         ["stake_agent"],
        "transfer":        ["transfer_agent"],
        "wallet_info":     ["wallet_agent"],
        "mempool":         ["mempool_agent"],
        "mining":          ["miner_agent", "subnet_entry_agent"],
        "validator":       ["validator_agent"],
        "code_review":     ["code_review_agent"],
        "data_validation": ["data_validator_agent"],
        "meta_review":     ["meta_agent"],
    }

    def route(self, task: ParsedTask) -> List[str]:
        """
        Bestimmt die Liste der Agenten fuer eine Aufgabe.
        Kann mehrere Agenten zurueckgeben fuer parallele Ausfuehrung.
        """

    def parallelize(self, agents: List[str]) -> bool:
        """
        Entscheidet, ob die Agenten parallel oder sequentiell ausgefuehrt werden.
        """
```

#### 3. Execution Engine

```python
class ExecutionEngine:
    """Fuehrt Agenten aus und verwaltet deren Lebenszyklus."""

    async def execute(self, agent: BaseAgent, task: Task) -> Result:
        """
        Fuehrt einen Agenten mit einer Aufgabe aus.

        Features:
        - Asynchrone Ausfuehrung
        - Timeout-Management (Standard: 30 Sekunden)
        - Retry-Logik (max. 3 Versuche)
        - Fehlerbehandlung
        """

    async def execute_parallel(
        self, agents: List[BaseAgent], task: Task
    ) -> List[Result]:
        """Fuehrt mehrere Agenten parallel aus."""
```

#### 4. Result Aggregator

```python
class ResultAggregator:
    """Aggregiert Ergebnisse mehrerer Agenten."""

    def merge(self, results: List[Result]) -> AggregatedResult:
        """
        Fuehrt mehrere Ergebnisse zusammen.

        Strategies:
        - Union: Alle einzigartigen Informationen beibehalten
        - Intersection: Nur uebereinstimmende Informationen
        - Weighted: Nach Quellenqualitaet gewichten
        """

    def format_output(self, aggregated: AggregatedResult) -> str:
        """
        Formatiert das Ergebnis fuer die Ausgabe.
        Markdown-Formatierung fuer CLI/Dashboard.
        """
```

#### 5. Approval Gate

```python
class ApprovalGate:
    """
    Entscheidet ueber die Ausfuehrung von Aktionen.
    Zentrale Sicherheitskomponente.
    """

    def evaluate(self, action: Action, risk_score: int) -> ApprovalLevel:
        """
        Bestimmt den Approval-Level einer Aktion.

        Returns: SAFE | CAUTION | DANGER | VETO
        """

    async def request_approval(self, level: ApprovalLevel, action: Action) -> bool:
        """
        Fragt den Nutzer um Bestaetigung (bei CAUTION/DANGER).
        """
```

---

## Agent-Interface

Alle Agenten implementieren ein standardisiertes Interface:

### BaseAgent Klasse

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()


class AgentResult(BaseModel):
    """Standardisiertes Ergebnis eines Agenten."""
    agent_id: str
    task_type: str
    status: str  # "success" | "error" | "partial" | "vetoed"
    data: Dict[str, Any]
    risk_score: int
    approval_required: bool
    sources: List[str]
    execution_time_ms: int
    timestamp: str  # ISO-8601
    errors: List[str] = []
    warnings: List[str] = []


class BaseAgent(ABC):
    """
    Abstrakte Basisklasse fuer alle Agenten.
    Jedes Agenten-Mitglied muss diese Methoden implementieren.
    """

    def __init__(self):
        self.agent_id = self.__class__.__name__
        self.logger = logger.bind(agent=self.agent_id)
        self.enabled = True
        self.capabilities = []
        self.risk_level = "low"  # low | medium | high

    @abstractmethod
    async def execute(self, task: Dict[str, Any]) -> AgentResult:
        """
        Fuehrt die Hauptaufgabe des Agenten aus.

        Args:
            task: Dictionary mit Task-Parametern

        Returns:
            AgentResult mit dem Ergebnis

        Raises:
            AgentError: Bei Ausfuehrungsfehlern
            VetoError: Wenn Risk Agent ein Veto einlegt
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """
        Gibt die Faehigkeiten des Agenten zurueck.

        Returns:
            Liste von Capability-Strings
        """
        pass

    @abstractmethod
    def validate_input(self, task: Dict[str, Any]) -> bool:
        """
        Prueft, ob die Eingabe fuer diesen Agenten valide ist.

        Args:
            task: Zu pruefende Eingabe

        Returns:
            True wenn valide, False sonst
        """
        pass

    async def pre_execute(self, task: Dict[str, Any]) -> None:
        """
        Wird VOR execute() aufgerufen.
        Kann fuer Setup, Logging, Validierung verwendet werden.
        """
        self.logger.info("agent.execute.start", task_type=task.get("type"))

    async def post_execute(self, result: AgentResult) -> AgentResult:
        """
        Wird NACH execute() aufgerufen.
        Kann fuer Nachbearbeitung, Logging, Cleanup verwendet werden.
        """
        self.logger.info(
            "agent.execute.end",
            status=result.status,
            risk_score=result.risk_score,
            execution_time_ms=result.execution_time_ms,
        )
        return result

    def report_status(self) -> Dict[str, Any]:
        """
        Gibt den aktuellen Status des Agenten zurueck.
        Wird fuer Health-Checks und Monitoring verwendet.
        """
        return {
            "agent_id": self.agent_id,
            "enabled": self.enabled,
            "capabilities": self.get_capabilities(),
            "risk_level": self.risk_level,
            "last_execution": None,  # Wird zur Laufzeit gefuellt
        }
```

### Konkrete Agent-Implementierung (Beispiel)

```python
class ResearchAgent(BaseAgent):
    """
    Agent fuer allgemeine Bittensor-Recherche.
    """

    def __init__(self):
        super().__init__()
        self.capabilities = [
            "bittensor_protocol_research",
            "ecosystem_news",
            "upgrade_analysis",
        ]
        self.data_sources = DataSources()

    async def execute(self, task: Dict[str, Any]) -> AgentResult:
        """Fuehrt Recherche-Aufgaben aus."""
        await self.pre_execute(task)

        query = task.get("query", "")
        topic = task.get("topic", "general")

        # Daten abrufen
        data = await self.data_sources.search(query, topic)

        # Ergebnis validieren
        validated_data = await self.validate_data(data)

        result = AgentResult(
            agent_id=self.agent_id,
            task_type="research",
            status="success",
            data=validated_data,
            risk_score=0,  # Recherche ist immer SAFE
            approval_required=False,
            sources=[d.source for d in data],
            execution_time_ms=0,
            timestamp=datetime.utcnow().isoformat(),
        )

        return await self.post_execute(result)

    def get_capabilities(self) -> List[str]:
        return self.capabilities

    def validate_input(self, task: Dict[str, Any]) -> bool:
        return "query" in task or "topic" in task

    async def validate_data(self, data: List[DataPoint]) -> Dict[str, Any]:
        """Validiert alle externen Daten."""
        validated = {}
        for point in data:
            if point.source in TRUSTED_SOURCES:
                validated[point.key] = point.value
            else:
                validated[f"{point.key}_unverified"] = point.value
        return validated
```

---

## Datenfluss zwischen Agenten

### Sequentieller Fluss

```
Nutzer -> Orchestrator -> Agent A -> Agent B -> Nutzer
```

Beispiel: Subnet-Analyse
1. Nutzer fragt nach Subnet-Analyse
2. Orchestrator leitet an SubnetResearchAgent
3. SubnetResearchAgent fragt DataValidatorAgent um Datenvalidierung
4. Ergebnis geht zurueck an Orchestrator
5. Orchestrator zeigt Ergebnis dem Nutzer

### Paralleler Fluss

```
                    +--> Agent A --+
Nutzer -> Orchestrator +--> Agent B +--> ResultAggregator -> Nutzer
                    +--> Agent C --+
```

Beispiel: Umfassende Recherche
1. Nutzer fragt nach "Bittensor Oekosystem"
2. Orchestrator startet parallel:
   - ResearchAgent (allgemeine Info)
   - SubnetResearchAgent (Subnet-Daten)
   - TradeResearchAgent (Marktdaten)
3. ResultAggregator fasst Ergebnisse zusammen
4. Orchestrator zeigt aggregiertes Ergebnis

### Conditional Fluss

```
Nutzer -> Orchestrator -> Risk Agent -> (Veto?) -> Agent -> Nutzer
```

Beispiel: Transaktionsvorschlag
1. Nutzer will Transfer analysieren
2. Orchestrator prueft Risk Agent
3. Risk Agent gibt SAFE -> Weiter an TransferAgent
4. Oder Risk Agent gibt VETO -> Abbruch mit Begruendung

### Datenfluss-Diagramm (vollstaendig)

```
+------------------+        +-------------------+
|      Nutzer      |------->|    Orchestrator   |
|                  |<-------|                   |
+--------+---------+        +---------+---------+
                                     |
                    +----------------+----------------+
                    |                                 |
           +--------v--------+               +-------v--------+
           |   Risk Agent    |               |  Task Router   |
           |  (Veto-Recht)   |               |                |
           +--------+--------+               +-------+--------+
                    |                                 |
           +--------v--------+               +-------v--------+
           |  Safety Layer   |               | Agent Queue    |
           |  (Compliance)   |               +-------+--------+
           +-----------------+                       |
                                                     |
                    +----------------+----------------+
                    |                |                |
           +--------v----+  +--------v----+  +--------v----+
           |  Agent A    |  |  Agent B    |  |  Agent C    |
           | (Research)  |  |  (Subnet)   |  |   (Trade)   |
           +------+------+  +------+------+  +------+------+
                  |                |                |
                  +----------------+----------------+
                                   |
                          +--------v--------+
                          | Result Aggreg.  |
                          | + Data Valid.   |
                          +--------+--------+
                                   |
                          +--------v--------+
                          |  Approval Gate  |
                          | (if required)   |
                          +--------+--------+
                                   |
                          +--------v--------+
                          |  Output Handler |
                          +--------+--------+
                                   |
                          +--------v--------+
                          |      Nutzer     |
                          +-----------------+
```

---

## Task-Routing

### Routing-Logik

```python
class TaskRouter:
    """
    Entscheidet basierend auf dem Task-Typ,
    welche Agenten ausgefuehrt werden.
    """

    # Primaere Routing-Tabelle
    PRIMARY_ROUTES = {
        # Forschung & Analyse
        "research": {
            "agents": ["ResearchAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },
        "analyze_subnet": {
            "agents": ["SubnetResearchAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },
        "analyze_all_subnets": {
            "agents": ["SubnetResearchAgent"],
            "parallel": True,
            "requires_risk_check": False,
        },

        # Trading
        "trade_analysis": {
            "agents": ["TradeResearchAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },
        "paper_trade": {
            "agents": ["TradeResearchAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },

        # Wallet & Transaktionen
        "wallet_info": {
            "agents": ["WalletAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },
        "transfer": {
            "agents": ["TransferAgent", "WalletAgent"],
            "parallel": False,
            "requires_risk_check": True,
        },
        "stake": {
            "agents": ["StakeAgent", "RiskAgent"],
            "parallel": False,
            "requires_risk_check": True,
        },
        "unstake": {
            "agents": ["StakeAgent", "RiskAgent"],
            "parallel": False,
            "requires_risk_check": True,
        },

        # Mining & Validierung
        "mining_opportunity": {
            "agents": ["MinerAgent", "SubnetEntryAgent"],
            "parallel": True,
            "requires_risk_check": False,
        },
        "validator_info": {
            "agents": ["ValidatorAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },

        # System
        "code_review": {
            "agents": ["CodeReviewAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },
        "data_validation": {
            "agents": ["DataValidatorAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },
        "meta_review": {
            "agents": ["MetaAgent"],
            "parallel": False,
            "requires_risk_check": False,
        },
    }

    def route(self, task: ParsedTask) -> RoutingDecision:
        """
        Bestimmt die Ausfuehrungsstrategie fuer einen Task.
        """
        task_type = task.task_type

        if task_type not in self.PRIMARY_ROUTES:
            return RoutingDecision(
                agents=["ResearchAgent"],  # Fallback
                parallel=False,
                requires_risk_check=False,
                reason="Unbekannter Task-Typ, Fallback auf ResearchAgent",
            )

        route = self.PRIMARY_ROUTES[task_type]

        # Bei finanziellen Tasks immer Risk Agent hinzufuegen
        if route["requires_risk_check"]:
            agents = route["agents"] + ["RiskAgent"]
        else:
            agents = route["agents"]

        return RoutingDecision(
            agents=agents,
            parallel=route["parallel"],
            requires_risk_check=route["requires_risk_check"],
            reason=f"Routing basierend auf Task-Typ: {task_type}",
        )
```

### Routing-Beispiele

| Nutzer-Eingabe | Task-Typ | Agent(en) | Risk-Check |
|----------------|----------|-----------|------------|
| "Zeige Wallet" | wallet_info | WalletAgent | Nein |
| "Analysiere Subnet 1" | analyze_subnet | SubnetResearchAgent | Nein |
| "TAO Transfer 5 TAO" | transfer | TransferAgent, WalletAgent, RiskAgent | Ja |
| "Stake in Subnet 5" | stake | StakeAgent, RiskAgent | Ja |
| "Mining-Chance?" | mining_opportunity | MinerAgent, SubnetEntryAgent | Nein |
| "Neue Bittensor News" | research | ResearchAgent | Nein |
| "Marktanalyse TAO" | trade_analysis | TradeResearchAgent | Nein |

---

## Konfliktloesung

### Arten von Konflikten

#### 1. Datenkonflikte

Wenn verschiedene Agenten widerspruechliche Daten liefern:

```python
class DataConflictResolver:
    """
    Loesst Konflikte zwischen Daten verschiedener Agenten.
    """

    STRATEGIES = {
        "newest": lambda data: max(data, key=lambda x: x.timestamp),
        "majority": lambda data: most_common_value(data),
        "trusted_source": lambda data: from_most_trusted_source(data),
        "conservative": lambda data: most_conservative_value(data),
    }

    def resolve(self, conflicting_data: List[DataPoint]) -> DataPoint:
        """
        Loesst einen Datenkonflikt auf.

        1. Pruefe Quellenqualitaet
        2. Waehle Strategie basierend auf Datentyp
        3. Dokumentiere den Konflikt und die Entscheidung
        """
        # Quellvertrauen bewerten
        trusted = [d for d in conflicting_data if d.source in TRUSTED_SOURCES]
        if len(trusted) == 1:
            return trusted[0]  # Vertraue der vertrauenswuerdigen Quelle

        # Bei gleichem Vertrauen: Mehrheit entscheiden
        return self.STRATEGIES["majority"](conflicting_data)
```

#### 2. Empfehlungskonflikte

Wenn Agenten unterschiedliche Empfehlungen geben:

```python
class RecommendationResolver:
    """
    Loesst Konflikte zwischen Agenten-Empfehlungen.
    """

    def resolve(self, recommendations: List[Recommendation]) -> Resolution:
        """
        Strategie:
        1. Risk Agent hat Veto-Recht -> Blockiert bei Konflikt
        2. Bei SAFE-Handlungen: Mehrheit entscheidet
        3. Bei finanziellen Handlungen: Konservativste Empfehlung gewinnt
        """

        # Pruefe auf Veto
        for rec in recommendations:
            if rec.agent_id == "RiskAgent" and rec.veto:
                return Resolution(
                    decision="VETO",
                    reason=rec.veto_reason,
                    action_blocked=True,
                )

        # Konservativste Empfehlung fuer finanzielle Aktionen
        if any(rec.has_financial_impact for rec in recommendations):
            safest = min(recommendations, key=lambda r: r.risk_score)
            return Resolution(
                decision="SAFEST_OPTION",
                reason=f"Konservativste Empfehlung von {safest.agent_id}",
                action=safest,
            )

        # Mehrheitsentscheidung
        return Resolution(
            decision="MAJORITY",
            reason="Mehrheit der Agenten stimmt ueberein",
        )
```

#### 3. Timeout-Konflikte

Wenn ein Agent nicht rechtzeitig antwortet:

```python
class TimeoutHandler:
    """
    Behandelt Timeouts bei Agent-Ausfuehrung.
    """

    DEFAULT_TIMEOUT = 30  # Sekunden
    MAX_RETRIES = 3

    async def execute_with_timeout(
        self, agent: BaseAgent, task: Task
    ) -> AgentResult:
        """
        1. Versuche Ausfuehrung mit Timeout
        2. Bei Timeout: Warte und versuche erneut
        3. Nach MAX_RETRIES: Fallback oder Fehler
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return await asyncio.wait_for(
                    agent.execute(task),
                    timeout=self.DEFAULT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                if attempt < self.MAX_RETRIES:
                    wait_time = attempt * 2  # Exponentieller Backoff
                    logger.warning(
                        "agent.timeout.retry",
                        agent=agent.agent_id,
                        attempt=attempt,
                        wait=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    return AgentResult(
                        agent_id=agent.agent_id,
                        status="error",
                        error=f"Timeout nach {self.MAX_RETRIES} Versuchen",
                        risk_score=0,
                    )
```

### Konflikt-Eskalation

```
Konflikt aufgetreten
        |
        v
+-------------------------+
| 1. Automatische         |
|    Loesung versuchen    |
+-----------+-------------+
            |
    +-------v-------+
    | Gelungen?     |
    +-------+-------+
        |        |
       Ja        Nein
        |        |
        v        v
   Erledigt  +-----------------+
              | 2. Orchestrator |
              |    eingreifen   |
              +--------+--------+
                       |
               +-------v-------+
               | Gelungen?     |
               +-------+-------+
                   |        |
                  Ja        Nein
                   |        |
                   v        v
              Erledigt  +-----------------+
                         | 3. Nutzer       |
                         |    entscheidet  |
                         +-----------------+
```

---

## Agent-Kommunikationsdiagramm

### Nachrichtenfluss (sequentiell)

```
Zeit ---->

Nutzer:     |---Request--->|
                     |
Orchestrator:       |---Route--->|
                             |
Risk Agent:                 |---Check--->|
                                     |
                                     |<---SAFE---|
                                     |
Agent X:                            |---Execute--->|
                                           |
Data Validator:                           |---Validate--->|
                                                   |
                                                   |<---OK---|
                                                   |
Agent X:                                          |<---Result---|
                                                 |
Orchestrator:                                   |---Aggregate--->|
                                                         |
                                                         |<---Done---|
                                                         |
Nutzer:                                                 |<---Response---|
```

### Nachrichtenfluss (parallel)

```
Zeit ---->

Nutzer:     |---Request---------------------------------------------------->|
                     |              |              |
Orchestrator:       |---Agent A--->|              |
                     |              |              |
                     |---Agent B------------------->|
                     |                             |
                     |---Agent C----------------------------------->|
                     |              |                             |
Aggregator:         |<---Result A--|                             |
                     |              |                             |
                     |<---Result B--------------------------------|
                     |                                            |
                     |<---Result C-------------------------------|
                     |                                            |
Nutzer:             |<---Aggregated Result-----------------------|
```

---

## Datenpersistenz

### SQLite-Datenbankschema

```sql
-- Agent-Ausfuehrungen
CREATE TABLE agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,  -- success | error | vetoed | timeout
    risk_score INTEGER,
    input TEXT,
    output TEXT,
    sources TEXT,  -- JSON-Array
    execution_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Risk-Bewertungen
CREATE TABLE risk_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    approval_level TEXT NOT NULL,  -- SAFE | CAUTION | DANGER | VETO
    veto_reason TEXT,
    agent_results TEXT,  -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Nutzer-Entscheidungen (Approval Gate)
CREATE TABLE user_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,
    approval_level TEXT NOT NULL,
    user_decision TEXT NOT NULL,  -- approved | denied
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Wallet-Cache (nur Public Data)
CREATE TABLE wallet_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coldkey_address TEXT,
    hotkey_address TEXT,
    balance_tao REAL,
    staked_tao REAL,
    subnet_id INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Subnet-Daten
CREATE TABLE subnet_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subnet_id INTEGER NOT NULL,
    name TEXT,
    emission_tao REAL,
    miner_count INTEGER,
    validator_count INTEGER,
    registration_cost_tao REAL,
    deregistration_risk TEXT,  -- low | medium | high
    data_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Logs (strukturiert)
CREATE TABLE system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,  -- DEBUG | INFO | WARNING | ERROR | CRITICAL
    agent_id TEXT,
    message TEXT NOT NULL,
    context TEXT,  -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Fehlerbehandlung

### Fehlerklassen

```python
class AgentError(Exception):
    """Basisklasse fuer Agent-Fehler."""
    pass

class VetoError(AgentError):
    """Wird geworfen, wenn Risk Agent ein Veto einlegt."""
    pass

class TimeoutError(AgentError):
    """Agent hat nicht rechtzeitig geantwortet."""
    pass

class ValidationError(AgentError):
    """Eingabedaten sind ungueltig."""
    pass

class DataSourceError(AgentError):
    """Datenquelle ist nicht erreichbar."""
    pass

class WalletError(AgentError):
    """Wallet-Operation fehlgeschlagen."""
    pass

class SecurityError(AgentError):
    """Sicherheitsverletzung erkannt."""
    pass
```

### Fehlerbehandlungsstrategie

```python
class ErrorHandler:
    """
    Zentrale Fehlerbehandlung fuer das gesamte System.
    """

    async def handle(self, error: Exception, context: Dict) -> ErrorResult:
        """
        1. Fehler klassifizieren
        2. Angemessene Reaktion waehlen
        3. Protokollieren
        4. Nutzer informieren (wenn noetig)
        """

        if isinstance(error, VetoError):
            return await self._handle_veto(error, context)

        elif isinstance(error, TimeoutError):
            return await self._handle_timeout(error, context)

        elif isinstance(error, ValidationError):
            return await self._handle_validation(error, context)

        elif isinstance(error, SecurityError):
            return await self._handle_security(error, context)

        else:
            return await self._handle_unknown(error, context)

    async def _handle_veto(self, error: VetoError, context: Dict) -> ErrorResult:
        """Veto wird immer protokolliert und dem Nutzer gemeldet."""
        logger.warning("error.veto", reason=str(error), context=context)
        return ErrorResult(
            status="vetoed",
            message=f"Aktion blockiert: {error}",
            recoverable=False,
        )

    async def _handle_security(self, error: SecurityError, context: Dict) -> ErrorResult:
        """Sicherheitsfehler erfordern sofortige Eskalation."""
        logger.critical("error.security", reason=str(error), context=context)
        # Hier koennte ein Alarm ausgeloest werden
        return ErrorResult(
            status="security_breach",
            message=f"Sicherheitsverletzung: {error}",
            recoverable=False,
        )
```

---

*Letzte Aktualisierung: 2025-01-15*
