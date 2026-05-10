# TradingBrain — die 15 Agenten als Experten-Team

PR 2S hat jeder Agent eine echte Datenquelle gegeben. PR 2T baut
darauf den nächsten Layer: ein **TradingBrain** der die
spezialisierten Sichten der 15 Agenten in **eine** koordinierte
Trading-Entscheidung fusioniert.

## Wer beiträgt was

Jeder Agent hat eine *Spezialität* — die spezifische Sicht die
nur er liefern kann. Das Brain liest die published Reports im
`AgentContext`, extrahiert pro Agent ein typed `AgentSignal`,
und aggregiert alles.

| # | Agent | Beitrag (sein Signal) | Default-Weight |
|---|---|---|---|
| 1 | `subnet_scoring_agent` | "Beste Subnet-Conviction" — `final_score / 100` der Top-Subnet | **1.5** |
| 2 | `risk_security_agent` | **VETO** bei DANGER · CAUTION → bearish · SAFE → bullish | **1.4** |
| 3 | `market_trade_agent` | TAO-Macro-Trend aus 7d/30d-Preisbewegung | **1.3** |
| 4 | `wallet_watch_agent` | **Concentration-Risk** — Top-Position-Anteil bestimmt direction | **1.2** |
| 5 | `subnet_discovery_agent` | Aktivitäts-Barometer aus total `tao_in` aller Subnets | **1.0** |
| 6 | `protocol_research_agent` | Netzwerk-Health (Subnet-Count, Validator-Count) | **1.0** |
| 7 | `qa_test_agent` | **VETO** bei kritischen Compliance-Issues · sonst Code-Hygiene-Bonus | **1.0** |
| 8 | `system_check_agent` | Hardware-Fitness (RAM, CPUs) — kann diese Maschine zuverlässig traden? | **0.8** |
| 9 | `miner_engineering_agent` | Mining-Viability bei den vorhandenen Specs | **0.7** |
| 10 | `validator_engineering_agent` | Validator-Slot-Opportunity | **0.7** |
| 11 | `training_experiment_agent` | Operator als Netzwerk-Participant → Info-Edge | **0.4** |
| 12 | `infra_devops_agent` | Deployment-Readiness aus Docker/Compose-Plänen | **0.4** |
| 13 | `fullstack_dev_agent` | UX-Maturity-Proxy für die Top-Subnets | **0.3** |
| 14 | `documentation_agent` | Swarm Self-Coverage-Health (meta) | **0.2** |
| 15 | `dashboard_design_agent` | (ehrlicher Stub — UI-Work, kein Trading-Signal) | **0.0** |

## Aggregation — wie das Brain entscheidet

```python
from tao_swarm.orchestrator import SwarmOrchestrator
from tao_swarm.trading import TradingBrain

orch = SwarmOrchestrator(config)
orch.execute_task({"type": "general_review"})  # populates AgentContext

brain = TradingBrain(orch.context)
decision = brain.aggregate()

print(decision.decision)  # "bullish" | "bearish" | "neutral" | "halt"
print(decision.score)     # [0, 1] — None when halted
print(decision.reason)    # human-readable
for sig in decision.signals:
    print(sig.name, sig.direction, sig.score, sig.evidence)
```

### Algorithm

1. **Collect** — frage jeden Extraktor nach seinem `AgentSignal`.
   Extraktoren returnen `None` wenn der Agent noch nicht
   published hat — das ist OK, das Brain läuft mit partiellem
   Wissen.

2. **Veto-Check** — wenn ein Signal `direction == "veto"` UND
   `confidence >= veto_confidence` (default 0.8) ist, **halt**.
   Die Entscheidung wird sofort `"halt"` mit `score=None` und
   einer klaren `reason`. Aktuell liefern `risk_security_agent`
   (DANGER) und `qa_test_agent` (kritische Findings) Veto-Signale.

3. **Weighted Average** — sonst aggregiere alle non-veto Signale:

   ```
   score = Σ (weight_i × confidence_i × score_i) / Σ (weight_i × confidence_i)
   ```

   Confidence multipliziert sich in das effektive Gewicht — ein
   Agent mit 0.3 Confidence beeinflusst weniger als einer mit
   0.9 selbst wenn beide die gleiche Default-Weight haben.

4. **Threshold-Mapping:**
   - `score ≥ 0.6` → `"bullish"`
   - `score ≤ 0.4` → `"bearish"`
   - sonst → `"neutral"`

   Thresholds sind im Constructor konfigurierbar.

## Veto-Layer

**Risk veto** triggert wenn `risk_security_agent.classification == "DANGER"`.
Das passiert z.B. bei:
- Coldkey-Swap-Social-Engineering Patterns
- Validator-Risiko Patterns
- PyPI-Typosquats in zu installierenden Packages

**QA veto** triggert wenn `qa_test_agent.severities.critical > 0`. Das
sind compliance-Issues wie:
- Seed-Phrase committet im Source
- Wallet-Datei in Git-History

Beides halts trading **vollständig** — kein bullish-anderes-Signal
kann das überstimmen. Das ist by design: ein Trading-System mit
risk-Issues sollte gar nicht traden.

## Custom Weights

Operator kann das Brain bias-en:

```python
from tao_swarm.trading import BRAIN_DEFAULT_WEIGHTS, TradingBrain

# z.B. mehr Gewicht auf Macro-Trend (fundamentaler Trader)
weights = dict(BRAIN_DEFAULT_WEIGHTS)
weights["market_trade_agent"] = 2.5
weights["subnet_scoring_agent"] = 0.8

brain = TradingBrain(ctx, weights=weights)
```

Weight 0 = Agent komplett aus dem Brain ausschalten.

## CLI: `tao-swarm trade brain`

Zeigt die aktuelle Brain-Sicht in einer kompakten Tabelle:

```
$ tao-swarm --live --network finney trade brain

  TradingBrain — expert-team aggregate

  Decision: BULLISH   score=0.6234
  Reason:   aggregate of 14 signal(s)

    agent                         dir   score   conf  weight  evidence
    -----------------------------  ---  ------  -----  ------  ----
    subnet_scoring_agent      bullish   0.785   0.20    1.50  top subnet 'Apex' …
    market_trade_agent        bullish   0.625   0.70    1.30  TAO 7d +7.5%, 24h …
    risk_security_agent       bullish   0.700   0.85    1.40  SAFE classification
    system_check_agent        bullish   0.700   0.70    0.80  hardware: 16 GB RAM, 8 CPUs
    miner_engineering_agent   bullish   0.750   0.50    0.70  mining viability: …
    …

  Tip: rebalance weights via tao_swarm.trading.BRAIN_DEFAULT_WEIGHTS to bias the brain.
```

`--json` für maschinen-lesbares Output.

## Architektur-Hinweise

**Pull-based, nicht push.** Das Brain modifiziert keinen Agenten und
greift nicht in deren `run()` ein. Es liest nur die bereits published
Outputs aus dem Bus.

**Defensive by construction.** Jeder Extraktor ist eine pure
Funktion die `None` returned wenn der Agent nicht published oder
das Output-Schema nicht passt. Ein einzelner Extraktor-Fehler
crashed das Brain nie — `aggregate()` skippt schlecht-laufende
Extraktoren.

**Stateless.** Brain hält keinen State. Multiple Instances mit
verschiedenen Weight-Schemes sind safe (z.B. operator vergleicht
"trader-style" vs "investor-style" Brains parallel).

**Read-only.** Brain modifiziert nichts — weder Context noch Ledger.
Es ist ein read-only Aggregator den Strategien optional konsultieren.

## Was das Brain (noch) nicht ist

- **Kein Trading-Executor.** Das Brain liefert eine Empfehlung;
  ob/wie sie umgesetzt wird entscheidet die Strategy + Executor.
- **Kein State-Speicher.** Aggregat-Historie wird nicht persisted.
  Der Operator kann das selber via `decision.as_dict()` tun.
- **Kein Auto-Tuner.** Weights sind statisch. Performance-basiertes
  Re-Weighting ist eine separate Feature-Idee (vgl. Learning-Layer
  PR 2M/2N).

## Source-Map

| Was | Wo |
|---|---|
| `AgentSignal` + `BrainDecision` + `TradingBrain` | [`tao_swarm/trading/brain.py`](../tao_swarm/trading/brain.py) |
| 15 Extraktoren (per-Agent Signal-Logik) | gleiche Datei |
| CLI | [`tao_swarm/cli/tao_swarm.py`](../tao_swarm/cli/tao_swarm.py) (`trade brain`) |
| Tests | [`tests/test_trading_brain.py`](../tests/test_trading_brain.py) |
