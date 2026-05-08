# Risk-Modell

> Dieses Dokument beschreibt das Risikobewertungssystem des TAO/Bittensor Multi-Agent Systems. Es definiert die Risk-Scores, Kategorien, Klassifikationen und Veto-Bedingungen.

---

## Inhaltsverzeichnis

- [Risk-Score-Definition](#risk-score-definition)
- [Risk-Kategorien](#risk-kategorien)
- [SAFE / CAUTION / DANGER Klassifikation](#safe--caution--danger-klassifikation)
- [Veto-Bedingungen](#veto-bedingungen)
- [Risikobewertungsmatrix](#risikobewertungsmatrix)
- [Berechnungsmethodik](#berechnungsmethodik)
- [Beispiele](#beispiele)

---

## Risk-Score-Definition

Der **Risk-Score** ist eine Zahl von **0 bis 100**, die das Gesamtrisiko einer Aktion quantifiziert.

### Score-Bereiche

| Bereich | Level | Farbe | Bedeutung |
|---------|-------|-------|-----------|
| 0-25 | SAFE | Gruen | Automatische Ausfuehrung |
| 26-50 | CAUTION | Gelb | Nutzer-Bestaetigung erforderlich |
| 51-70 | DANGER | Orange | Erweitertes Verfahren + Verzoegerung |
| 71-85 | CRITICAL | Rot | Doppel-Bestaetigung + Risk Review |
| 86-100 | VETO | Dunkelrot | Automatische Blockierung |

### Score-Bereiche (visuell)

```
0    10    20    30    40    50    60    70    80    90   100
|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|
[  SAFE  ] [   CAUTION   ] [ DANGER  ] [CRITICAL ] [ VETO ]
[========= OK ==========] [==== WARN ====] [==== BLOCK ====]

Gruen        Gruen-Gelb       Orange        Rot         Dunkelrot
Automatisch  Bestaetigung     Verzoegerung  Doppel-      Blockiert
             erforderlich     + Review      Bestaetigung
```

---

## Risk-Kategorien

Der Gesamt-Risk-Score setzt sich aus vier Kategorien zusammen:

### 1. Technisches Risiko (0-30 Punkte)

| Faktor | Punkte | Beschreibung |
|--------|--------|-------------|
| Protokoll-Komplexitaet | 0-10 | Wie komplex ist die Aktion technisch? |
| Fehlerwahrscheinlichkeit | 0-10 | Wie wahrscheinlich ist ein technischer Fehler? |
| Rueckgaengigkeit | 0-10 | Kann die Aktion rueckgaengig gemacht werden? |

**Beispiele:**
- Balance abfragen: 0 Punkte (kein Risiko)
- Subnet-Analyse: 2 Punkte (gering)
- Transaktion vorbereiten: 5 Punkte (mittel)
- Subnet-Registrierung: 10 Punkte (hoch, nicht rueckgaengig)

### 2. Finanzielles Risiko (0-30 Punkte)

| Faktor | Punkte | Beschreibung |
|--------|--------|-------------|
| Betrag in TAO | 0-15 | Wie viel TAO ist im Spiel? |
| Preisvolatilitaet | 0-10 | Wie volatil ist TAO aktuell? |
| Opportunity Cost | 0-5 | Was ist der Verlust bei falscher Entscheidung? |

**Betrags-Skalierung:**

| TAO-Betrag | Punkte |
|------------|--------|
| 0 TAO | 0 |
| < 1 TAO | 2 |
| 1-5 TAO | 5 |
| 5-10 TAO | 8 |
| 10-50 TAO | 12 |
| > 50 TAO | 15 |

### 3. Wallet-Risiko (0-20 Punkte)

| Faktor | Punkte | Beschreibung |
|--------|--------|-------------|
| Private Key benoetigt | 20 | Automatisches VETO |
| Signatur benoetigt | 10 | Erhoehtes Risiko |
| Wallet-Modus | 0-5 | NO_WALLET=0, WATCH_ONLY=2, MANUAL_SIGNING=5 |
| Deregistration-Risiko | 0-10 | Risk of losing subnet position |

### 4. Reputationsrisiko (0-20 Punkte)

| Faktor | Punkte | Beschreibung |
|--------|--------|-------------|
| Subnet-Reputation | 0-10 | Beeinflusst die Aktion die Subnet-Reputation? |
| Oeffentlichkeit | 0-5 | Ist die Aktion oeffentlich sichtbar? |
| Wiederrufbarkeit | 0-5 | Kann die Aktion rueckgaengig gemacht werden? |

---

## SAFE / CAUTION / DANGER Klassifikation

### SAFE (0-25 Punkte)

**Automatische Ausfuehrung ohne Bestaetigung.**

| Kriterium | Bedingung |
|-----------|-----------|
| Keine finanziellen Auswirkungen | 0 TAO im Spiel |
| Keine Wallet-Interaktion | Nur Read-Operationen |
| Keine technische Komplexitaet | Einfache Abfragen |
| Kein Reputationsrisiko | Keine sichtbaren Aktionen |

**Beispiele:**
- Balance anzeigen
- Transaktionshistorie abrufen
- Subnet-Informationen anzeigen
- Paper-Trading-Simulation
- Explorer-Link generieren

### CAUTION (26-50 Punkte)

**Nutzer-Bestaetigung erforderlich.**

| Kriterium | Bedingung |
|-----------|-----------|
| Geringe finanzielle Auswirkungen | < 1 TAO |
| Transaktionsvorbereitung | Ohne Signatur |
| Empfehlungen | Stake/Unstake-Empfehlungen |
| Konfigurationsaenderungen | Aenderungen an Einstellungen |

**Benoetigt:**
```
Orchestrator: "Aktion X vorschlagen. Risk-Score: Y (CAUTION). Bestaetigen? (ja/nein)"
Nutzer: "ja"
-> Aktion wird ausgefuehrt
```

**Beispiele:**
- Transaktion vorbereiten (kleiner Betrag)
- Stake-Empfehlung anzeigen
- Subnet-Entry-Analyse
- Konfigurationsaenderung

### DANGER (51-70 Punkte)

**Erweitertes Verfahren mit Verzoegerung.**

| Kriterium | Bedingung |
|-----------|-----------|
| Erhoehte finanzielle Auswirkungen | 1-10 TAO |
| Irreversible Aktionen | Nicht rueckgaengig machbar |
| Mainnet-Registrierung | Neuer Eintrag im Mainnet |
| Hohes technisches Risiko | Komplexe Operationen |

**Benoetigt:**
```
1. Risk Agent Review (detailliert)
2. Nutzer-Bestaetigung (mit Warnung)
3. Zeitverzoegerung (Standard: 300 Sekunden)
4. Finale Bestaetigung nach Verzoegerung
```

**Beispiele:**
- Transfer > 1 TAO vorbereiten
- Unstake mit Deregistration-Risiko
- Subnet-Entry im Mainnet
- Stake > 5 TAO

### VETO (71-100 Punkte)

**Automatische Blockierung.**

| Kriterium | Bedingung |
|-----------|-----------|
| Private Key benoetigt | IMMER VETO |
| Automatische Transaktion | IMMER VETO |
| Betrag > konfigurierter Maximalwert | VETO |
| Unbekannte, nicht-reviewte Aktion | VETO |

**Konsequenz:**
```
Risk Agent: "VETO — Aktion blockiert. Grund: [Begruendung]"
-> Aktion wird NICHT ausgefuehrt
-> Protokollierung im Audit-Log
-> Benachrichtigung des Nutzers
```

**Beispiele:**
- Private Key abfragen
- Automatische Signatur
- Seed Phrase verarbeiten
- Transfer > 100 TAO

---

## Veto-Bedingungen

### Automatisches Veto (keine Abweichung moeglich)

| Bedingung | Veto-Code | Konsequenz |
|-----------|-----------|------------|
| Private Key wird verarbeitet | V-PK-001 | System-Alarm |
| Seed Phrase wird verarbeitet | V-SP-001 | System-Alarm |
| Automatische Signatur erkannt | V-SIG-001 | Warnung |
| Automatische Order-Platzierung | V-ORD-001 | Warnung |
| Hot Wallet direkte Verbindung | V-HW-001 | Warnung |

### Risk-basiertes Veto

| Bedingung | Veto-Code | Konsequenz |
|-----------|-----------|------------|
| Risk-Score > 85 | V-RISK-001 | Blockierung |
| Unbekannte Aktion ohne Review | V-UNK-001 | Blockierung |
| Daten ohne Validierung | V-DAT-001 | Warnung |
| Konfigurationsaenderung ohne Log | V-CFG-001 | Warnung |

### Wallet-basiertes Veto

| Bedingung | Veto-Code | Konsequenz |
|-----------|-----------|------------|
| Transaktion > MAX_ABSOLUTE_TAO | V-WAL-001 | Blockierung |
| Wallet-Modus NO_WALLET, aber Transaktion erwuenscht | V-WAL-002 | Hinweis |
| Adressvalidierung fehlgeschlagen | V-WAL-003 | Blockierung |

### Veto-Protokoll

```
+------------------------------------------------+
|              VETO-PROTOKOLL                      |
+------------------------------------------------+
| 1. Veto wird durch Risk Agent ausgeloest       |
| 2. Aktion wird sofort blockiert                |
| 3. Grund wird protokolliert                    |
| 4. Audit-Log wird aktualisiert                 |
| 5. Nutzer wird benachrichtigt                  |
| 6. Bei kritischen Vetos: Eskalation            |
+------------------------------------------------+
```

---

## Risikobewertungsmatrix

### Matrix: Betrag vs. Komplexitaet

```
                    Komplexitaet
               Niedrig    Mittel    Hoch
            +----------+----------+----------+
  Niedrig   |   SAFE   |   SAFE   | CAUTION  |
Betrag      |  (0-15)  |  (5-20)  | (10-30)  |
            +----------+----------+----------+
  Mittel    |   SAFE   | CAUTION  |  DANGER  |
            |  (5-20)  | (15-35)  | (25-50)  |
            +----------+----------+----------+
  Hoch      | CAUTION  |  DANGER  |  DANGER  |
            | (10-30)  | (25-50)  | (35-65)  |
            +----------+----------+----------+
  Sehr Hoch | CAUTION  |  DANGER  |   VETO   |
            | (15-35)  | (35-55)  | (50-100) |
            +----------+----------+----------+
```

### Matrix: Irreversibilitaet vs. Wahrscheinlichkeit

```
                    Wahrscheinlichkeit
               Niedrig    Mittel    Hoch
            +----------+----------+----------+
  Keine     |   SAFE   |   SAFE   |   SAFE   |
Irrevers.   |   (0-5)  |   (5-10) |  (10-15) |
            +----------+----------+----------+
  Teilweise |   SAFE   | CAUTION  | CAUTION  |
            |  (5-15)  | (15-25)  | (20-35)  |
            +----------+----------+----------+
  Vollstaen.| CAUTION  |  DANGER  |  DANGER  |
            | (10-25)  | (25-40)  | (35-55)  |
            +----------+----------+----------+
```

---

## Berechnungsmethodik

### Schritt-fuer-Schritt

```python
class RiskCalculator:
    """
    Berechnet den Risk-Score fuer eine geplante Aktion.
    """

    def calculate(self, action: Action) -> RiskAssessment:
        """
        1. Technisches Risiko berechnen
        2. Finanzielles Risiko berechnen
        3. Wallet-Risiko berechnen
        4. Reputationsrisiko berechnen
        5. Gesamt-Score berechnen
        6. Klassifikation bestimmen
        """

        # Schritt 1: Technisches Risiko (0-30)
        tech_risk = self._calc_technical_risk(action)

        # Schritt 2: Finanzielles Risiko (0-30)
        fin_risk = self._calc_financial_risk(action)

        # Schritt 3: Wallet-Risiko (0-20)
        wallet_risk = self._calc_wallet_risk(action)

        # Schritt 4: Reputationsrisiko (0-20)
        rep_risk = self._calc_reputation_risk(action)

        # Schritt 5: Gesamt-Score
        total_score = tech_risk + fin_risk + wallet_risk + rep_risk

        # Schritt 6: Klassifikation
        level = self._classify(total_score)

        return RiskAssessment(
            total_score=total_score,
            level=level,
            breakdown={
                "technical": tech_risk,
                "financial": fin_risk,
                "wallet": wallet_risk,
                "reputation": rep_risk,
            },
            veto_applicable=(total_score > 85),
        )

    def _calc_technical_risk(self, action: Action) -> int:
        """0-30 Punkte fuer technisches Risiko."""
        score = 0
        score += action.complexity * 2  # 0-10
        score += action.error_probability * 2  # 0-10
        score += (10 - action.reversibility_score)  # 0-10
        return min(score, 30)

    def _calc_financial_risk(self, action: Action) -> int:
        """0-30 Punkte fuer finanzielles Risiko."""
        score = 0
        # Betrag
        if action.amount_tao == 0:
            score += 0
        elif action.amount_tao < 1:
            score += 2
        elif action.amount_tao < 5:
            score += 5
        elif action.amount_tao < 10:
            score += 8
        elif action.amount_tao < 50:
            score += 12
        else:
            score += 15

        # Volatilitaet (0-10)
        score += action.current_volatility_score

        # Opportunity Cost (0-5)
        score += action.opportunity_cost_score

        return min(score, 30)

    def _calc_wallet_risk(self, action: Action) -> int:
        """0-20 Punkte fuer Wallet-Risiko."""
        if action.requires_private_key:
            return 100  # Automatisches VETO

        score = 0
        if action.requires_signature:
            score += 10
        score += action.deregistration_risk * 2  # 0-10
        return min(score, 20)

    def _calc_reputation_risk(self, action: Action) -> int:
        """0-20 Punkte fuer Reputationsrisiko."""
        score = 0
        score += action.subnet_reputation_impact * 2  # 0-10
        score += action.public_visibility * 5  # 0-5
        score += (5 - action.reversibility_score)  # 0-5
        return min(score, 20)

    def _classify(self, score: int) -> str:
        """Bestimmt die Risk-Klasse."""
        if score <= 25:
            return "SAFE"
        elif score <= 50:
            return "CAUTION"
        elif score <= 70:
            return "DANGER"
        elif score <= 85:
            return "CRITICAL"
        else:
            return "VETO"
```

### Konfigurierbare Schwellenwerte

Die Schwellenwerte sind in der `.env` konfigurierbar:

```bash
# .env
RISK_SAFE_THRESHOLD=25
RISK_CAUTION_THRESHOLD=50
RISK_DANGER_THRESHOLD=70
RISK_VETO_THRESHOLD=85

RISK_DANGER_DELAY=300        # Sekunden Wartezeit fuer DANGER
RISK_MAX_SAFE_TAO=1.0        # Max. TAO ohne DANGER-Approval
RISK_MAX_ABSOLUTE_TAO=100.0  # Max. TAO ueberhaupt
```

---

## Beispiele

### Beispiel 1: Balance abfragen

```
Aktion: Balance anzeigen
Technisches Risiko: 0 (einfache Abfrage)
Finanzielles Risiko: 0 (kein TAO im Spiel)
Wallet-Risiko: 0 (Read-Only)
Reputationsrisiko: 0 (keine sichtbare Aktion)

Gesamt: 0/100 -> SAFE
Ausfuehrung: Automatisch
```

### Beispiel 2: Subnet-Analyse

```
Aktion: Subnet 5 analysieren
Technisches Risiko: 2 (Datenabfrage)
Finanzielles Risiko: 0 (kein TAO im Spiel)
Wallet-Risiko: 0 (keine Wallet-Interaktion)
Reputationsrisiko: 0 (Analyse ist privat)

Gesamt: 2/100 -> SAFE
Ausfuehrung: Automatisch
```

### Beispiel 3: Transaktion vorbereiten (2 TAO)

```
Aktion: Transfer 2 TAO vorbereiten
Technisches Risiko: 5 (Transaktionsvorbereitung)
Finanzielles Risiko: 8 (2 TAO = 5 Punkte + Volatilitaet 3)
Wallet-Risiko: 10 (Signatur erforderlich)
Reputationsrisiko: 2 (Transaktion ist oeffentlich)

Gesamt: 25/100 -> CAUTION (Grenze zu SAFE)
Ausfuehrung: Nach Nutzer-Bestaetigung
```

### Beispiel 4: Stake 10 TAO

```
Aktion: Stake 10 TAO in Subnet 3
Technisches Risiko: 8 (komplex, Bindung)
Finanzielles Risiko: 15 (10 TAO = 8 + Volatilitaet 5 + Opportunity 2)
Wallet-Risiko: 15 (Signatur + Deregistration-Risiko)
Reputationsrisiko: 5 (Subnet-Reputation)

Gesamt: 43/100 -> CAUTION
Ausfuehrung: Nach Nutzer-Bestaetigung
```

### Beispiel 5: Mainnet-Registrierung

```
Aktion: Miner in Subnet 1 registrieren
Technisches Risiko: 15 (komplex, nicht rueckgaengig)
Finanzielles Risiko: 20 (Registrierungskosten + Stake)
Wallet-Risiko: 18 (Signatur + Deregistration-Risiko)
Reputationsrisiko: 10 (oeffentliche Registrierung)

Gesamt: 63/100 -> DANGER
Ausfuehrung: Risk Review + 300s Verzoegerung + Bestaetigung
```

### Beispiel 6: Private Key verarbeiten

```
Aktion: Private Key fuer automatische Signatur
Technisches Risiko: 30 (kritisch)
Finanzielles Risiko: 30 (Totalverlust moeglich)
Wallet-Risiko: 20 (Private Key!)
Reputationsrisiko: 20 (kritischer Sicherheitsvorfall)

Gesamt: 100/100 -> VETO
Ausfuehrung: BLOCKIERT + System-Alarm
```

---

*Letzte Aktualisierung: 2025-01-15*
