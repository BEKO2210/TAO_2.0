<div align="center">

# Komplette Anleitung — TAO Swarm

**Von `git clone` bis "Bot läuft im Paper-Mode auf Mainnet" in 10 Minuten.**

</div>

---

## TL;DR

```bash
# 1) Install
git clone https://github.com/BEKO2210/TAO_2.0.git && cd TAO_2.0
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2) Live Mainnet Read-Only Check
tao-swarm --live --network finney subnets --limit 5

# 3) Paper-Run Adaptive Ensemble (ohne Wallet, ohne Risk)
tao-swarm --live --network finney trade run \
    --strategy ensemble:all \
    --paper \
    --tick-interval-s 60 \
    --status-file data/runner_status.json

# 4) Dashboard (in zweitem Terminal)
tao-swarm dashboard
```

Du tradest paper auf 129 echten Bittensor-Subnets, der Bot wählt
adaptiv zwischen `momentum_rotation` und `mean_reversion`, und du
schaust im Dashboard zu.

---

## Voraussetzungen

| Tool | Version | Wofür |
|---|---|---|
| Python | 3.10+ | Core |
| pip | aktuell | Install |
| git | aktuell | Clone |
| (optional) bittensor SDK | 10.x | Live mainnet reads |
| (optional) Streamlit | aktuell | Dashboard UI |
| (optional) argon2-cffi | 23.1+ | Keystore (für Live-Trading) |

`pip install -e .` zieht die Pflicht-Deps. Live-Trading braucht
zusätzlich `pip install argon2-cffi cryptography bittensor`.

---

## Schritt 1 — Setup

```bash
git clone https://github.com/BEKO2210/TAO_2.0.git
cd TAO_2.0
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Sanity-Check:

```bash
tao-swarm version
```

Erwartet:

```
=== TAO Swarm ===
  Version:    1.0.0
  Python:     3.11.x
  Platform:   linux
  Mode:       READ-ONLY (SAFE)
  MODE: mock (offline fixtures)  — pass --live for real data
```

---

## Schritt 2 — Mainnet-Read verifizieren

```bash
tao-swarm --live --network finney subnets --limit 5
```

Du solltest 129 reale Subnets sehen (Apex, DSperse, Targon, …) mit
echten `tao_in`-Werten und Volumen. Falls Fehlermeldung → bittensor
SDK ist nicht installiert; `pip install bittensor`.

---

## Schritt 3 — Backtest first

Backtest gegen historische Snapshots **bevor** du den Runner
startest:

```bash
# Beispiel-Snapshot-Datei (du baust deine eigene aus echten Chain-Reads)
tao-swarm trade backtest \
    --strategy momentum_rotation \
    --snapshots ./data/historical_snapshots.json \
    --threshold-pct 0.05 \
    --slot-size-tao 1.0
```

Wenn der Backtest sinnvolle Zahlen bringt (P&L, Win-Rate, Sharpe),
geh weiter. Wenn nicht: Parameter ändern, oder anderer Strategy-
Typ.

---

## Schritt 4 — Paper-Run gegen Live-Daten

Das ist der "ich schau nur Dashboard"-Modus:

```bash
# Adaptive Ensemble: Momentum + Mean-Reversion mit auto-shifting Weights
tao-swarm --live --network finney trade run \
    --strategy ensemble:all \
    --paper \
    --tick-interval-s 60 \
    --threshold-pct 0.05 \
    --slot-size-tao 1.0 \
    --max-position-tao 5.0 \
    --max-total-tao 50.0 \
    --max-daily-loss-tao 100.0 \
    --status-file data/runner_status.json \
    --kill-switch-path data/.kill
```

Was passiert pro Tick:

1. Runner zieht 129 Subnets von Mainnet
2. EnsembleStrategy ruft `momentum_rotation` UND `mean_reversion`
3. Tracker liest die letzten 14 Tage P&L pro Strategy aus dem Ledger
4. `inverse_loss_weights` allokiert mehr Kapital zum Winner
5. Beide Strategien können auf jedem Subnet emittieren
6. Executor 4-Guard-Chain (KillSwitch/Mode/PositionCap/DailyLoss)
7. Audit-Row landet im SQLite-Ledger
8. Status-File wird atomisch geschrieben → Dashboard liest es

Stop: `Ctrl-C` oder `touch data/.kill`.

---

## Schritt 5 — Dashboard öffnen

In einem zweiten Terminal:

```bash
tao-swarm dashboard
```

Browser öffnet auf `http://localhost:8501`. Linke Sidebar →
**Trading**.

Was du siehst:

- **Runner-Status:** State-Badge, Strategy, Mode, Last Tick
- **Counters:** Ticks / Executed / Refused / Errors
- **Halt-Runner Button** (touched die kill-switch Datei)
- **Open Positions** (per-netuid size + entry)
- **Per-Strategy Performance Tabelle** (P&L, Win-Rate, Sharpe pro Base)
- **Suggested Ensemble Weights** (horizontale Bars)
- **Equity Curves Overlay** (alle Strategien als Linien-Chart)
- **Backtest Mini-Panel** (Snapshots-Upload + Run)

---

## Schritt 6 — Live-Trading (optional, RISKANT)

> **WARNUNG:** Ab hier bewegt der Bot echtes Geld auf Bittensor.
> Mach das **nur** mit einer dedizierten Trading-Coldkey, die nur
> den Cap-Betrag enthält den du zu verlieren bereit bist.

### 6a) Dedizierte Trading-Coldkey erstellen

```bash
btcli wallet new_coldkey --wallet.name tao-swarm-live
```

Funde sie mit einem kleinen Betrag (z.B. 10 TAO).

### 6b) Keystore initialisieren

```bash
tao-swarm keystore init \
    --path ~/.tao-swarm/live.keystore \
    --label live-finney
```

Du wirst gefragt nach:
- **Seed (hex)** — der Trading-Coldkey-Seed (32 bytes hex), zweimal
- **Password** — ≥8 Zeichen, zweimal

Datei wird mit `0o600` (owner-only) geschrieben, Argon2id+AES-GCM
encrypted. Verifizieren:

```bash
tao-swarm keystore verify --path ~/.tao-swarm/live.keystore
```

### 6c) Live-Run mit Drei-Stage-Authorisation

```bash
export TAO_LIVE_TRADING=1                   # Stage 1: Env-Var

tao-swarm --live --network finney trade run \
    --strategy ensemble:all \
    --live --live-trading \                  # Stage 2 + 3
    --keystore-path ~/.tao-swarm/live.keystore \
    --reconcile-from-coldkey 5YourTradingColdkeySS58 \
    --verify-broadcasts \
    --max-position-tao 1.0 \
    --max-daily-loss-tao 5.0 \
    --max-total-tao 10.0 \
    --tick-interval-s 60 \
    --status-file data/runner_status.json \
    --kill-switch-path /run/tao-swarm.kill
```

CLI fragt nach Keystore-Passwort und verlangt dann eine getippte
Bestätigung **`I UNDERSTAND`** bevor irgendein Extrinsic geschickt
wird.

---

## Stop / Restart / Halt

| Aktion | Wie |
|---|---|
| Sauber beenden | `Ctrl-C` im Runner-Terminal |
| Halt am nächsten Tick | `touch data/.kill` (oder Dashboard-Button) |
| Resume nach Halt | `rm data/.kill` (manuell — kein Auto-Reset) |
| Process restart | Cold-Start-Reconciliation rebuild Position-Book aus Chain |

---

## Lerneffekt beobachten

Nach 1-2 Wochen Paper-Run hast du Daten. Dann:

```bash
tao-swarm trade learning-report \
    --ledger-db data/trades.db \
    --window-days 14
```

Output zeigt:
- P&L pro Strategy
- Win-Rate pro Strategy
- Suggested Ensemble Weights (was läuft Live)

Wenn `momentum_rotation` z.B. 95% Win-Rate hat und `mean_reversion`
30%, sieht das so aus:

```
strategy            attempts closes  pnl_tao  win_rate sharpe  data
-----------------   -------- ------  -------- -------- ------  ----
momentum_rotation         15     15  +37.5560   100.0% +2.674   ok
mean_reversion            15     15  -13.6778    26.7% -0.589   ok

Suggested ensemble weights:
  momentum_rotation       ████████████████████████████··   95.5%
  mean_reversion          █·····························    4.5%
```

Der Runner allokiert automatisch dahin. Du machst nichts.

---

## Eigene Strategy schreiben

Drop ein `*_strategy.py` File in irgendeinen Ordner, dann:

```bash
TAO_STRATEGY_PATHS=/path/to/your/strategies \
tao-swarm trade run --strategy ensemble:all
```

Vollständige Doku: [`docs/strategy_plugins.md`](strategy_plugins.md).

---

## Wenn was nicht klappt

| Problem | Wahrscheinliche Ursache | Fix |
|---|---|---|
| `bittensor SDK not installed` | Nicht installiert | `pip install bittensor` |
| `argon2-cffi not installed` | Live-Trading-Deps fehlen | `pip install argon2-cffi cryptography` |
| Runner haltet sofort | Cold-Start-Reconcile failed | Coldkey-SS58 falsch oder Subtensor unerreichbar |
| 0 proposals pro Tick | Tick-Interval ≤ Block-Time | `--tick-interval-s 60` (oder höher) |
| Dashboard zeigt "offline" | Status-File fehlt | Runner mit `--status-file` starten |
| `wrong password` beim Keystore | Tippfehler oder vergessen | **Es gibt KEINE Recovery.** Neuen Keystore mit neuer Coldkey machen |

---

## Source-Map

| Was | Wo |
|---|---|
| CLI | [`tao_swarm/cli/tao_swarm.py`](../tao_swarm/cli/tao_swarm.py) |
| Trading-Skeleton | [`tao_swarm/trading/`](../tao_swarm/trading/) |
| Built-in Strategien | [`tao_swarm/trading/strategies/`](../tao_swarm/trading/strategies/) |
| Learning-Layer | [`tao_swarm/trading/learning/`](../tao_swarm/trading/learning/) |
| Dashboard | [`tao_swarm/dashboard/`](../tao_swarm/dashboard/) |
| Tests (877 default + 12 live) | [`tests/`](../tests/) |

Vertiefung:
- Auto-Trading-Setup-Guide: [`docs/auto_trading.md`](auto_trading.md)
- Strategy-Plug-ins: [`docs/strategy_plugins.md`](strategy_plugins.md)
- Learning-Layer: [`docs/learning.md`](learning.md)
