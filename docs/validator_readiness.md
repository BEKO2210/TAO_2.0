# Validator-Readiness

> Dieses Dokument beschreibt, was zum Betrieb eines Bittensor-Validators benoetigt wird. Es deckt Stake-Anforderungen, Code-Pruefung, Monitoring und Risiken ab.

**WARNUNG: Validierung erfordert erheblichen Stake. Zuerst auf Testnet ueben!**

---

## Inhaltsverzeichnis

- [Voraussetzungen](#voraussetzungen)
- [Stake-Anforderungen](#stake-anforderungen)
- [Validator-Code pruefen](#validator-code-pruefen)
- [Monitoring-Anforderungen](#monitoring-anforderungen)
- [Risiken](#risiken)
- [Checkliste](#checkliste)
- [Kostenuebersicht](#kostenuebersicht)
- [Validator vs. Miner](#validator-vs-miner)

---

## Voraussetzungen

### Was man zum Validieren braucht

| Komponente | Beschreibung | Status |
|------------|-------------|--------|
| Wallet | Bittensor-Wallet (Coldkey + Hotkey) | Erforderlich |
| TAO-Stake | Erheblicher TAO-Stake | Erforderlich |
| Hardware | Server mit hoher Verfuegbarkeit | Erforderlich |
| Software | Bittensor SDK, Python, Validator-Code | Erforderlich |
| Internet | Sehr stabile Verbindung | Erforderlich |
| Know-how | Python, Linux, Protokoll-Verstaendnis | Erforderlich |
| Zeit | Kontinuierliches Monitoring | Erforderlich |

### Wichtige Unterschiede zum Minen

| Aspekt | Miner | Validator |
|--------|-------|-----------|
| Stake-Bedarf | Gering (nur Registrierung) | Hoch (erheblicher Stake) |
| Hauptaufgabe | KI-Dienste bereitstellen | Qualitaet bewerten |
| Hardware | Je nach Subnet variabel | Immer stabil und schnell |
| Risiko | Deregistration bei schlechter Performance | Slashing bei unfairer Bewertung |
| Einkommen | Proportional zur Performance | Proportional zum Stake + Bewertung |
| Verantwortung | Eigene Performance | Qualitaet des gesamten Subnets |

---

## Stake-Anforderungen

### Was ist Staking?

**Staking** bedeutet, TAO zu "hinterlegen", um als Validator teilnehmen zu koennen. Der Stake:
- **Bestimmt die Gewichtung** deiner Bewertungen
- **Wird eingesetzt** als Sicherheit fuer faire Bewertungen
- **Kann geslasht werden** (vermindert) bei Regelverstoessen
- **Kann entnommen werden** (mit Unbonding-Periode)

### Stake-Anforderungen pro Subnet

| Subnet-Typ | Mindest-Stake | Empfohlener Stake | Durchschnittlicher Stake |
|------------|--------------|-------------------|-------------------------|
| Kleines Subnet | 100 TAO | 500+ TAO | 300 TAO |
| Mittleres Subnet | 500 TAO | 2000+ TAO | 1000 TAO |
| Grosses Subnet | 1000 TAO | 5000+ TAO | 3000 TAO |
| Root Subnet (0) | 5000 TAO | 10000+ TAO | 5000 TAO |

**Wichtig:** Diese Werte sind Richtwerte und aendern sich. Immer aktuelle Daten pruefen!

### Stake delegieren

Wenn man nicht genug TAO hat, kann man von anderen **Stake delegieren** erhalten:

```bash
# Stake auf Hotkey eines Validators
btcli stake add \
    --wallet.name delegator_wallet \
    --wallet.hotkey validator_hotkey \
    --amount 100
```

Als Validator muss man:
- Einen guten Ruf aufbauen
- Faire Bewertungen abgeben
- Transparenz bieten

### Slashing

**Slashing** bedeutet, dass Stake verloren geht:

| Vergehen | Slashing | Beschreibung |
|----------|----------|-------------|
| Unfaire Bewertungen | 0-10% | Konsistente Abweichung vom Konsens |
| Inaktivitaet | 0-5% | Validator nicht erreichbar |
| Regelverstoss | 10-100% | Absichtliche Manipulation |

---

## Validator-Code pruefen

### Code-Quellen

Validator-Code kommt typischerweise aus:

1. **Offiziellem Subnet-Repository** (empfohlen)
2. **Eigenimplementierung** (nur mit Know-how)
3. **Community-Templates** (pruefen!)

### Was zu pruefen ist

#### 1. Vertrauenswuerdigkeit

- [ ] Code stammt vom offiziellen Subnet-Repository
- [ ] Repository ist aktiv gewartet
- [ ] Mehrere Contributor
- [ ] Regelmaessige Updates
- [ ] Gute Dokumentation

#### 2. Sicherheit

- [ ] Keine hartcodierten Keys oder Passwoerter
- [ ] Keine suspekten Netzwerkverbindungen
- [ ] Keine unnoetigen Berechtigungen
- [ ] Saubere Abhaengigkeiten (requirements.txt)
- [ ] Keine Malware-Verdaechtigen Importe

#### 3. Funktionalitaet

- [ ] Code ist verstaendlich und dokumentiert
- [ ] Tests sind vorhanden
- [ ] Konfiguration ist flexibel
- [ ] Logging ist implementiert
- [ ] Fehlerbehandlung existiert

#### 4. Performance

- [ ] Effiziente API-Calls
- [ ] Gutes Timeout-Management
- [ ] Ressourcen-Nutzung ist angemessen
- [ ] Skalierbarkeit ist gegeben

### Code-Review-Beispiel

```python
# Beispiel: Wichtige Checks beim Validator-Code

class ValidatorCodeReview:
    """
    Prueft Validator-Code auf Sicherheit und Qualitaet.
    """

    DANGEROUS_PATTERNS = [
        r"private_key",      # Private Keys im Code
        r"password\s*=",     # Passwoerter im Code
        r"subprocess\.call",  # Shell-Aufrufe
        r"os\.system",       # System-Aufrufe
        r"requests\.post.*http", # Unverschluesselte Kommunikation
        r"eval\(",           # Code-Execution
        r"exec\(",           # Code-Execution
    ]

    TRUSTED_SOURCES = [
        "github.com/opentensor",
        "github.com/bittensor",
        # Offizielle Subnet-Repositories
    ]

    def review(self, codebase: Codebase) -> ReviewResult:
        """Fuehrt vollstaendigen Code-Review durch."""
        checks = {
            "source_trust": self._check_source(codebase),
            "security": self._check_security(codebase),
            "functionality": self._check_functionality(codebase),
            "performance": self._check_performance(codebase),
        }
        return ReviewResult(checks=checks)
```

---

## Monitoring-Anforderungen

### Was ueberwacht werden muss

#### 1. Validator-Health

| Metrik | Frequenz | Alarm wenn |
|--------|----------|------------|
| Uptime | Kontinuierlich | < 99% |
| Response Time | Kontinuierlich | > 5 Sek. |
| Erreichbarkeit | Jede Minute | Nicht erreichbar |
| Stake | Taeglich | < Minimum |

#### 2. Performance

| Metrik | Frequenz | Alarm wenn |
|--------|----------|------------|
| Bewertungs-Scores | Jede Epoche | < Durchschnitt |
| Konsens-Alignment | Jede Epoche | Abweichung > 10% |
| Reward-Rate | Taeglich | Sinkt ueber 3 Tage |

#### 3. System

| Metrik | Frequenz | Alarm wenn |
|--------|----------|------------|
| CPU-Auslastung | Jede Minute | > 90% |
| RAM-Auslastung | Jede Minute | > 90% |
| Festplatte | Stuendlich | > 85% |
| Netzwerk | Jede Minute | > 100ms Latenz |

### Monitoring-Stack

```
+------------------------------------------+
|            MONITORING STACK              |
+------------------------------------------+
|                                          |
|  Metrics: Prometheus / Node Exporter    |
|  Logs:    Loki / Filebeat               |
|  Alerting: AlertManager / PagerDuty     |
|  Dashboard: Grafana                      |
|  Uptime:   Uptime Kuma / Pingdom        |
|                                          |
+------------------------------------------+
```

### Beispiel-Monitoring-Setup

```yaml
# prometheus.yml (vereinfacht)
scrape_configs:
  - job_name: 'validator'
    static_configs:
      - targets: ['localhost:8000']
    scrape_interval: 15s

  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
    scrape_interval: 30s

# alert.rules
- alert: ValidatorDown
  expr: up{job="validator"} == 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Validator ist nicht erreichbar"
```

### Alert-Kanaele

| Kanal | Empfohlen fuer | Verzoegerung |
|-------|---------------|-------------|
| E-Mail | Alle Alerts | Sofort |
| Discord Webhook | Kritische Alerts | Sofort |
| PagerDuty | Kritische Alerts | Sofort |
| Slack | Taegliche Zusammenfassungen | Taeglich |
| SMS | Nur kritische System-Ausfaelle | Sofort |

---

## Risiken

### Finanzielle Risiken

| Risiko | Wahrscheinlichkeit | Auswirkung | Mitigation |
|--------|-------------------|------------|------------|
| TAO-Preis sinkt | Unbekannt | Sehr hoch | Nicht alles investieren |
| Slashing | Niedrig | Hoch | Faire Bewertungen |
| Niedrige Rewards | Mittel | Hoch | Subnet-Auswahl |
| Unbonding-Periode | Sicher | Mittel | Liquiditaet planen |

### Technische Risiken

| Risiko | Wahrscheinlichkeit | Auswirkung | Mitigation |
|--------|-------------------|------------|------------|
| Server-Ausfall | Niedrig | Hoch | Redundanz |
| Netzwerk-Probleme | Mittel | Mittel | Backup-Verbindung |
| Software-Bugs | Mittel | Mittel | Regelmaessige Updates |
| Code-Sicherheit | Niedrig | Sehr hoch | Code-Review |

### Betriebliche Risiken

| Risiko | Wahrscheinlichkeit | Auswirkung | Mitigation |
|--------|-------------------|------------|------------|
| Inaktivitaet | Niedrig | Hoch | Monitoring |
| Unfaire Bewertungen | Niedrig | Hoch | Standard-Code verwenden |
| Subnet-Deregistration | Niedrig | Hoch | Diversifikation |
| Wettbewerbsdruck | Hoch | Mittel | Bessere Infrastruktur |

---

## Checkliste

### Vor der Registrierung als Validator

- [ ] TAO-Stake ist ausreichend (mind. Minimum des Subnets)
- [ ] Hardware ist bereit und getestet
- [ ] Software ist installiert und konfiguriert
- [ ] Validator-Code ist geprueft und sicher
- [ ] Wallet ist erstellt (Coldkey + Hotkey)
- [ ] Coldkey Seed Phrase ist sicher aufbewahrt (offline)
- [ ] Testnet-Validierung erfolgreich
- [ ] Testnet-Validator laeuft stabil (> 48h)
- [ ] Subnet ist sorgfaeltig analysiert
- [ ] Stake-Risiko ist verstanden
- [ ] Slashing-Risiken sind bekannt
- [ ] Monitoring ist eingerichtet
- [ ] Alerting ist konfiguriert
- [ ] Backup-Plan existiert
- [ ] Unbonding-Periode ist verstanden

### Nach der Registrierung

- [ ] Validator laeuft auf Mainnet
- [ ] Logs zeigen keine kritischen Fehler
- [ ] Monitoring funktioniert
- [ ] Alerts sind getestet
- [ ] Erste Rewards kommen ein
- [ ] Konsens-Alignment ist gut
- [ ] Backup laeuft regelmaessig

### Taegliche Ueberwachung

- [ ] Validator ist erreichbar (Uptime)
- [ ] Keine kritischen Fehler in Logs
- [ ] Performance-Scores sind stabil
- [ ] Rewards kommen regelmaessig
- [ ] Konsens-Alignment ist im akzeptablen Bereich
- [ ] System-Ressourcen sind ausreichend
- [ ] Keine Alert-Meldungen

### Woechentliche Ueberwachung

- [ ] Reward-Trend analysieren
- [ ] Konsens-Alignment ueber die Woche
- [ ] Subnet-Stabilitaet bewerten
- [ ] Code-Updates pruefen
- [ ] System-Updates einspielen (wenn verfuegbar)
- [ ] Backup pruefen

---

## Kostenuebersicht

### Einmalkosten

| Posten | Schaetzung (EUR) | Hinweis |
|--------|-----------------|---------|
| Hardware (Server) | 2000-5000 | Hoehere Anforderungen als Mining |
| Stake (TAO) | 500-5000+ TAO | Je nach Subnet |
| Erstinstallation | 0 (Eigenarbeit) | Oder Dienstleister |
| **Gesamt** | **2000-5000 EUR + TAO** | |

### Laufende Kosten (monatlich)

| Posten | Schaetzung (EUR) | Hinweis |
|--------|-----------------|---------|
| Strom | 100-300 | 24/7 Betrieb |
| Internet | 30-100 | Geschaeftsanschluss |
| Server-Housing | 0-200 | Wenn extern |
| Monitoring | 0-50 | Tools |
| **Gesamt** | **130-650 EUR/Monat** | |

### Rentabilitaets-Schaetzung

```
Investition:
- Hardware: 3000 EUR (Einmalig)
- Stake: 1000 TAO
- Laufend: 300 EUR/Monat

Einnahmen (geschaetzt):
- Validator-Rewards: 0.5-2 TAO/Tag
- Delegations-Rewards: Zusaetzlich
- Gesamt: 15-60 TAO/Monat

Break-Even: Stark abhaengig von TAO-Preis und Subnet!
```

**Wichtig:** Rewards sind Schaetzungen und keine Garantien!

---

## Validator vs. Miner

| Aspekt | Miner | Validator | Empfehlung |
|--------|-------|-----------|------------|
| Startkosten | Niedriger | Hoeher | Miner fuer Einsteiger |
| Technisches Know-how | Mittel | Hoch | Validator fuer Experten |
| Zeitaufwand | Mittel | Hoch | Miner fuer Nebenberuf |
| Risiko | Mittel | Hoeher | Miner fuer konservative |
| Rendite-Potenzial | Variabel | Variabel | Beides hat Potenzial |
| Verantwortung | Gering | Hoch | Validator = Verantwortung |
| Einstiegshuerde | Niedriger | Hoeher | Miner zuerst |

---

*Letzte Aktualisierung: 2025-01-15*
