# Wallet-Sicherheit

> Dieses Dokument beschreibt die Wallet-Sicherheitskonzepte des TAO/Bittensor Multi-Agent Systems. Es erklaert die drei Wallet-Modi, Sicherheitsregeln und Best Practices fuer den sicheren Umgang mit Krypto-Wallets.

**WARNUNG: Dieses System speichert NIEMALS Private Keys oder Seed Phrases. Jede Transaktion erfordert manuelle Bestaetigung.**

---

## Inhaltsverzeichnis

- [Wallet-Modi im Ueberblick](#wallet-modi-im-ueberblick)
- [Modus 1: NO_WALLET](#modus-1-no_wallet)
- [Modus 2: WATCH_ONLY](#modus-2-watch_only)
- [Modus 3: MANUAL_SIGNING](#modus-3-manual_signing)
- [Was ist erlaubt und was ist verboten](#was-ist-erlaubt-und-was-ist-verboten)
- [Seed Phrase Regeln](#seed-phrase-regeln)
- [Private Key Regeln](#private-key-regeln)
- [Checkliste fuer Wallet-Sicherheit](#checkliste-fuer-wallet-sicherheit)
- [Wie man Public Addresses sicher eingibt](#wie-man-public-addresses-sicher-eingibt)
- [Notfall-Verfahren](#notfall-verfahren)

---

## Wallet-Modi im Ueberblick

Das System unterstuetzt drei Wallet-Modi, die ueber die Umgebungsvariable `WALLET_MODE` in der `.env` Datei konfiguriert werden:

```
+------------------------------------------------------------------+
|                      WALLET-MODI                                 |
+------------------+-------------+------------------+--------------+
|                  | NO_WALLET   | WATCH_ONLY       | MANUAL_SIGN  |
+------------------+-------------+------------------+--------------+
| Balance anzeigen |     X       |      Ja          |     Ja       |
| History anzeigen |     X       |      Ja          |     Ja       |
| Transaktion      |     X       |      Ja          |     Ja       |
| vorbereiten      |             | (vorbereitet)    | (vorbereitet)|
| Transaktion      |     X       |      X           |      X       |
| signieren        |             |                  | (extern)     |
| Stake-Empfehlung | Theoretisch |      Ja          |     Ja       |
| Unstake-Empfehl. | Theoretisch |      Ja          |     Ja       |
| Subnet-Analyse   |     Ja      |      Ja          |     Ja       |
+------------------+-------------+------------------+--------------+
| Sicherheits-     | Maximal     |      Hoch        |    Hoch      |
| niveau           | (kein       |      (read-only) | (manuell)    |
|                  |  Wallet)    |                  |              |
+------------------+-------------+------------------+--------------+
| Empfohlen fuer   | Einsteiger  |    Beobachter    |  Aktive      |
|                  | Recherche   |    Ueberwacher   |  Nutzer      |
+------------------+-------------+------------------+--------------+
```

---

## Modus 1: NO_WALLET

**Standard-Modus. Keine Wallet-Verbindung.**

### Beschreibung

Im NO_WALLET-Modus hat das System **keinerlei Zugriff** auf Wallet-Daten. Es kann ausschliesslich Recherche und Analyse durchfuehren.

### Was funktioniert

- Allgemeine Bittensor-Recherche
- Subnet-Analysen
- Trade- und Marktdaten
- Mining- und Validator-Informationen
- Paper-Trading-Simulationen

### Was NICHT funktioniert

- Balance-Anzeige
- Transaktionsvorbereitung
- Stake-/Unstake-Empfehlungen mit persoenlichen Daten
- Wallet-spezifische Informationen

### Konfiguration

```bash
# .env
WALLET_MODE=NO_WALLET
# Keine weiteren Wallet-Variablen benoetigt
```

### Wann verwenden

- Erste Tests mit dem System
- Recherche-Only-Nutzung
- Wenn man keine Wallet-Adresse eingeben moechte
- In unsicheren Umgebungen
- Fuer oeffentliche/gedeelte Installationen

### Sicherheitsbewertung: **MAXIMAL**

Kein Wallet-Datenfluss = Kein Wallet-Risiko.

---

## Modus 2: WATCH_ONLY

**Wallet-Beobachtung ohne Signatur-Befugnis.**

### Beschreibung

Im WATCH_ONLY-Modus gibt der Nutzer seine **Public Address** (oeffentliche Adresse) an. Das System kann damit:
- Balances auf der Blockchain abfragen
- Transaktionshistorie anzeigen
- Transaktionen vorbereiten (als JSON)
- Aber NIEMALS signieren

### Was funktioniert

- Balance-Anzeige (TAO, Stake)
- Transaktionshistorie anzeigen
- Transaktionen vorbereiten (JSON-Output)
- Stake- und Unstake-Empfehlungen
- Explorer-Links generieren

### Was NICHT funktioniert

- Transaktionen signieren
- Private Keys verarbeiten
- Automatische Transaktionen

### Konfiguration

```bash
# .env
WALLET_MODE=WATCH_ONLY

# Public Address (COLDKEY — nur die oeffentliche Adresse!)
# Format: 5xxxx... (SS58 Bittensor Format)
WALLET_COLDKEY_ADDRESS=5F3sa2TJ... (Beispiel)

# Optional: Hotkey Public Address
WALLET_HOTKEY_ADDRESS=5Gn8mL2... (Beispiel)

# Anzeigename (optional)
WALLET_NAME=Mein-Wallet
```

### Wichtig

- **NUR Public Addresses eingeben** (beginnen mit "5")
- **NIEMALS Private Keys oder Seed Phrases**
- Die Adresse ist oeffentlich auf der Blockchain sichtbar
- Das System kann nur lesen, nie schreiben

### Wann verwenden

- Taegliche Ueberwachung des Wallets
- Analyse ohne Transaktionsbedarf
- Wenn man Transaktionen extern signieren moechte

### Sicherheitsbewertung: **HOCH**

Read-Only Zugriff = Kein Signatur-Risiko.

---

## Modus 3: MANUAL_SIGNING

**Transaktionsvorbereitung mit manueller externer Signatur.**

### Beschreibung

Im MANUAL_SIGNING-Modus bereitet das System Transaktionen vor. Der Nutzer muss die vorbereitete Transaktion in einer **externen Wallet** manuell signieren.

### Ablauf einer Transaktion

```
Schritt 1: Nutzer gibt Transaktionswunsch ein
       |
       v
Schritt 2: System bereitet Transaktion als JSON vor
       |
       v
Schritt 3: System zeigt Transaktions-JSON an
       |
       v
Schritt 4: Nutzer kopiert JSON und oeffnet externe Wallet
       |
       v
Schritt 5: Nutzer signiert Transaktion in externer Wallet
       |
       v
Schritt 6: Transaktion wird auf Blockchain eingereicht
       |
       v
Schritt 7: System zeigt Transaktionsstatus an
```

### Transaktions-JSON Format

```json
{
  "transaction": {
    "version": "1.0",
    "network": "bittensor_mainnet",
    "type": "transfer",
    "from": "5F3sa2TJ... (Coldkey Public)",
    "to": "5Gn8mL2... (Zieladresse)",
    "amount": "1.5",
    "token": "TAO",
    "memo": "Optional: Beschreibung",
    "prepared_by": "tao-bittensor-agents v0.1.0",
    "prepared_at": "2025-01-15T10:30:00Z",
    "warning": "Diese Transaktion muss manuell in einer externen Wallet signiert werden."
  },
  "risk_assessment": {
    "risk_score": 25,
    "level": "CAUTION",
    "warnings": ["Bitte Zieladresse nochmals pruefen"]
  }
}
```

### Was funktioniert

- Alle Features von WATCH_ONLY
- Transaktionsvorbereitung
- Transaktionskosten-Schaetzung
- Adressvalidierung

### Was NICHT funktioniert

- Transaktionen automatisch signieren
- Private Keys verarbeiten
- Transaktionen automatisch senden

### Konfiguration

```bash
# .env
WALLET_MODE=MANUAL_SIGNING

# Public Address (COLDKEY)
WALLET_COLDKEY_ADDRESS=5F3sa2TJ... (Beispiel)

# Optional: Hotkey
WALLET_HOTKEY_ADDRESS=5Gn8mL2... (Beispiel)
```

### Empfohlene externe Wallets

- **Polkadot.js Extension** (Browser-Extension)
- **Talisman** (Browser-Extension)
- **SubWallet** (Browser-Extension)
- **bittensor-cli** (Kommandozeile, Offline-Modus)

### Wann verwenden

- Wenn man gelegentlich Transaktionen durchfuehren moechte
- Bei aktiver Teilnahme im Netzwerk
- Fuer Stake/Unstake-Operationen

### Sicherheitsbewertung: **HOCH**

Private Keys bleiben extern = Kein Signatur-Risiko im System.

---

## Was ist erlaubt und was ist verboten

### ERLAUBT (in allen Modi)

| Aktion | Beschreibung |
|--------|-------------|
| Balance abfragen | TAO-Balance und Stake anzeigen |
| Transaktionshistorie | Vergangene Transaktionen anzeigen |
| Transaktion vorbereiten | JSON mit Transaktionsdaten erstellen |
| Adresse validieren | Format einer Adresse pruefen |
| Recherche | Alle Analyse- und Recherche-Funktionen |
| Explorer-Link | Link zum Blockchain-Explorer generieren |
| Paper Trading | Simulierte Handelsanalysen |

### VERBOTEN (in jedem Modus)

| Aktion | Konsequenz |
|--------|-----------|
| Private Key speichern | SOFORTIGES SYSTEM-SHUTDOWN |
| Seed Phrase verarbeiten | SOFORTIGES SYSTEM-SHUTDOWN |
| Transaktion automatisch signieren | VETO + System-Warnung |
| Private Key in Logs speichern | SOFORTIGES SYSTEM-SHUTDOWN |
| Hot Wallet direkt verbinden | VETO + Warnung |
| Automatische Order platzieren | VETO + Warnung |

### Modus-spezifische Einschraenkungen

```
+------------------+-------------+------------------+--------------+
| Aktion           | NO_WALLET   | WATCH_ONLY       | MANUAL_SIGN  |
+------------------+-------------+------------------+--------------+
| Balance anzeigen |      X      |      Ja          |     Ja       |
| History anzeigen |      X      |      Ja          |     Ja       |
| Transaktion      |      X      |      Ja          |     Ja       |
| vorbereiten      |             | (JSON)           | (JSON)       |
| Transaktion      |      X      |      X           |      X       |
| signieren        |             |                  | (extern)     |
| Explorer-Link    |      Ja     |      Ja          |     Ja       |
| Adresse valid.   |      Ja     |      Ja          |     Ja       |
+------------------+-------------+------------------+--------------+
```

---

## Seed Phrase Regeln

### ABSOLUTE REGELN

```
REGEL S-1: KEINE ABFRAGE
Das System fragt NIEMALS nach einer Seed Phrase.
Wenn ein Dialog nach einer Seed Phrase fragt:
-> ABBRECHEN und melden

REGEL S-2: KEINE SPEICHERUNG
Die Seed Phrase wird NIEMALS in irgendeiner Form gespeichert.
Nicht in Variablen, nicht in Logs, nicht in der Datenbank.

REGEL S-3: KEINE VERARBEITUNG
Die Seed Phrase wird NIEMALS verarbeitet.
Keine Ableitung, keine Validierung, keine Weitergabe.

REGEL S-4: KEINE ANZEIGE
Die Seed Phrase wird NIEMALS angezeigt.
Auch nicht maskiert oder teilweise.

REGEL S-5: KEIN TRANSFER
Die Seed Phrase wird NIEMALS uebertragen.
Nicht an externe APIs, nicht an andere Agenten.
```

### Was tun, wenn ein Agent nach einer Seed Phrase fragt

1. **SOFORT ABBRECHEN**
2. Den Vorgang protokollieren
3. Den Vorfall melden (GitHub Issue)
4. Das System im NO_WALLET-Modus neustarten

Das System ist so konzipiert, dass es NIEMALS eine Seed Phrase benoetigt. Jede Anfrage ist ein Fehler oder ein Sicherheitsvorfall.

---

## Private Key Regeln

### ABSOLUTE REGELN

```
REGEL P-1: KEINE ABFRAGE
Das System fragt NIEMALS nach einem Private Key.

REGEL P-2: KEINE SPEICHERUNG
Private Keys werden NIEMALS gespeichert.
Weder in Dateien, Datenbanken, Umgebungsvariablen noch Logs.

REGEL P-3: KEINE VERARBEITUNG
Private Keys werden NIEMALS verarbeitet.
Keine Signatur-Operation im System.

REGEL P-4: KEINE ANZEIGE
Private Keys werden NIEMALS angezeigt.
Nicht einmal in maskierter Form.

REGEL P-5: KEIN TRANSFER
Private Keys werden NIEMALS uebertragen.
Weder an APIs noch an andere Dienste.
```

### Private Key Schutz

```python
# Beispiel: Wie das System Private Keys blockiert

class SecurityFilter:
    """
    Filtert alle Eingaben auf Private Keys.
    """

    PRIVATE_KEY_PATTERNS = [
        r"0x[a-fA-F0-9]{64}",      # Ethereum-Style
        r"[5KL][1-9A-HJ-NP-Za-km-z]{50,51}",  # Bitcoin-Style
        r"^-----BEGIN.*PRIVATE KEY",  # PEM-Format
        r"mnemonic", r"seed", r"private",
    ]

    def scan_input(self, user_input: str) -> SecurityResult:
        """
        Prueft jede Nutzereingabe auf Private Key Patterns.
        """
        for pattern in self.PRIVATE_KEY_PATTERNS:
            if re.search(pattern, user_input):
                return SecurityResult(
                    safe=False,
                    action="BLOCK",
                    reason="Moeglicher Private Key erkannt",
                    alert_level="CRITICAL",
                )

        return SecurityResult(safe=True)
```

---

## Checkliste fuer Wallet-Sicherheit

### Vor der ersten Nutzung

- [ ] `.env.example` zu `.env` kopiert
- [ ] `WALLET_MODE` auf gewuenschten Modus gesetzt
- [ ] BEI WATCH_ONLY/MANUAL_SIGNING: Nur Public Address eingetragen
- [ ] Keine Private Keys in der `.env` Datei
- [ ] Keine Seed Phrases im System
- [ ] `.env` in `.gitignore` geprueft
- [ ] Log-Verzeichnis geprueft (keine sensitiven Daten)

### Taegliche Pruefung

- [ ] System laeuft im erwarteten Wallet-Modus
- [ ] Keine Warnungen zu sensitiven Daten im Log
- [ ] Transaktionen nur im MANUAL_SIGNING vorbereitet
- [ ] Externe Wallet fuer Signierung bereit
- [ ] Keine unerwarteten System-Meldungen

### Vor jeder Transaktion

- [ ] Zieladresse doppelt geprueft
- [ ] Betrag korrekt
- [ ] Transaktionsgebuehr akzeptabel
- [ ] Risk-Bewertung gelesen
- [ ] Approval Gate bestaetigt
- [ ] Externe Wallet bereit zum Signieren
- [ ] Kein Zeitdruck (Betrueger nutzen oft Eile)

### Notfall-Checkliste

- [ ] System im NO_WALLET-Modus neustarten
- [ ] Logs auf verdaechtige Aktivitaeten pruefen
- [ ] Externe Wallet auf unerwartete Transaktionen pruefen
- [ ] Eventuell Coldkey in neuer Umgebung erstellen
- [ ] GitHub Issue fuer Sicherheitsvorfall erstellen

---

## Wie man Public Addresses sicher eingibt

### Schritt-fuer-Schritt

**Schritt 1: Adresse finden**
- Oeffne deine externe Wallet (Polkadot.js, Talisman, SubWallet)
- Kopiere die Public Address (beginnt mit "5")
- NICHT den Private Key kopieren!

**Schritt 2: Adresse validieren**
- Pruefe, dass die Adresse mit "5" beginnt
- Pruefe die Laenge (ca. 47-48 Zeichen)
- Vergleiche mit der Anzeige im Explorer

**Schritt 3: In .env eintragen**

```bash
# .env Datei oeffnen
nano .env

# Nur diese Zeilen bearbeiten:
WALLET_COLDKEY_ADDRESS=5DeG... (deine echte Adresse)
# NIEMALS Private Key eintragen!
```

**Schritt 4: Verifizieren**

```bash
# System starten und pruefen, ob Adresse korrekt angezeigt wird
make run-cli
> wallet: show
# Balance sollte korrekt angezeigt werden
```

### Adress-Validierung im System

```python
class AddressValidator:
    """
    Validiert Bittensor-Addresses.
    """

    @staticmethod
    def is_valid_ss58(address: str) -> bool:
        """
        Prueft, ob eine Adresse ein gueltiges SS58-Format hat.
        """
        if not address:
            return False
        if not address.startswith("5"):
            return False
        if len(address) < 47 or len(address) > 48:
            return False
        # Zusaetzliche Checks koennen hier erfolgen
        return True

    @staticmethod
    def is_private_key(value: str) -> bool:
        """
        Erkennt potenzielle Private Keys.
        BLOCKIERT die Eingabe!
        """
        # Private Key Patterns erkennen
        dangerous_patterns = [
            r"0x[a-fA-F0-9]{64}",
            r"[0-9a-fA-F]{64}",
        ]
        for pattern in dangerous_patterns:
            if re.match(pattern, value):
                return True
        return False
```

---

## Notfall-Verfahren

### Falls ein Private Key kompromittiert wurde

1. **SOFORT** alle Verbindungen trennen
2. **Keine Panik** — Handeln, nicht reagieren
3. Neues Wallet erstellen (mit neuer Seed Phrase)
4. Assets auf neues Wallet transferieren (so schnell wie moeglich)
5. Altes Wallet als kompromittiert markieren

### Falls das System unerwartetes Verhalten zeigt

1. System im NO_WALLET-Modus neustarten
2. Logs pruefen (`logs/agents.log`)
3. `.env` Datei auf Manipulation pruefen
4. GitHub Issue mit Logs erstellen

### Falls eine Seed Phrase abgefragt wird

1. **NICHTS eingeben**
2. System sofort beenden
3. Vorfall melden
4. System aus offiziellem Repository neu aufsetzen

---

**WICHTIG: Dieses System wurde mit maximaler Sicherheit entworfen. Jede Abweichung von den beschriebenen Verhaltensweisen ist ein Warnsignal. Melden Sie verdächtiges Verhalten sofort.**

---

*Letzte Aktualisierung: 2025-01-15*
