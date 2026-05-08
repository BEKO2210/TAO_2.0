# Miner-Readiness

> Dieses Dokument beschreibt, was zum Betrieb eines Bittensor-Miners benoetigt wird. Es deckt Hardware-Anforderungen, Software-Setup, Testumgebung und die Mainnet-Registrierung ab.

**WARNUNG: Mainnet-Registrierung erfordert DANGER-Level Approval. Zuerst auf Testnet ueben!**

---

## Inhaltsverzeichnis

- [Voraussetzungen](#voraussetzungen)
- [Hardware-Anforderungen](#hardware-anforderungen)
- [Software-Setup](#software-setup)
- [Lokale Testumgebung](#lokale-testumgebung)
- [Mainnet-Registrierung](#mainnet-registrierung)
- [Checkliste](#checkliste)
- [Kostenuebersicht](#kostenuebersicht)
- [Risiken](#risiken)

---

## Voraussetzungen

### Was man zum Minen braucht

| Komponente | Beschreibung | Status |
|------------|-------------|--------|
| Wallet | Bittensor-Wallet (Coldkey + Hotkey) | Erforderlich |
| TAO | Registrierungsgebuehr + Stake | Erforderlich |
| Hardware | Server/PC mit ausreichend Leistung | Erforderlich |
| Software | Bittensor SDK, Python, Dependencies | Erforderlich |
| Internet | Stabile Verbindung, oeffentliche IP | Erforderlich |
| Zeit | Monitoring und Wartung | Erforderlich |
| Know-how | Python, Linux, KI/ML Grundlagen | Empfohlen |

### Vor dem Start

1. **Verstehen**, was ein Bittensor-Miner tut
2. **Subnet auswaehlen**, das zu deiner Hardware/Kompetenz passt
3. **Testnet** ausprobieren (kostenlos)
4. **Kosten** kalkulieren (Registrierung + Hardware + Strom)
5. **Risiken** verstehen (Deregistration, Hardware-Ausfall)

---

## Hardware-Anforderungen

### Minimum (fuer einfache Subnets)

| Komponente | Minimum | Empfohlen |
|------------|---------|-----------|
| CPU | 4 Cores | 8+ Cores |
| RAM | 16 GB | 32+ GB |
| Speicher | 100 GB SSD | 500+ GB SSD |
| GPU | Optional | Je nach Subnet |
| Internet | 10 MBit/s | 100+ MBit/s |
| Uptime | 80% | 95%+ |

### Empfohlen (fuer komplexe Subnets)

| Komponente | Spec |
|------------|------|
| CPU | 8+ Cores (AMD Ryzen / Intel i7) |
| RAM | 32-64 GB DDR4/DDR5 |
| Speicher | 1 TB NVMe SSD |
| GPU | NVIDIA RTX 3060+ (fuer ML-Subnet) |
| Internet | 1 GBit/s symmetrisch |
| Uptime | 99%+ (24/7 Betrieb) |

### GPU-Anforderungen pro Subnet-Typ

| Subnet-Typ | GPU-Anforderung | Beispiel |
|------------|-----------------|----------|
| Text/Sprache | Optional, CPU ausreichend | - |
| Bild | GPU empfohlen | RTX 3060 12GB |
| Code | GPU empfohlen | RTX 3060 |
| Datenanalyse | GPU optional | RTX 3060 |
| Multimodal | GPU erforderlich | RTX 4090 / A100 |

### Hardware-Setup-Beispiel

```
Empfohlener Mining-Server:
+----------------------------------+
| CPU: AMD Ryzen 9 5900X (12 Cores) |
| RAM: 64 GB DDR4-3200              |
| SSD: 1 TB NVMe (Samsung 980 Pro)  |
| GPU: NVIDIA RTX 3060 12GB         |
| Netz: 1 GBit/s Ethernet           |
| OS: Ubuntu 22.04 LTS              |
+----------------------------------+
Schaetzung: ~1500-2000 EUR
```

---

## Software-Setup

### Schritt 1: System vorbereiten

```bash
# System aktualisieren
sudo apt update && sudo apt upgrade -y

# Grundlegende Pakete
sudo apt install -y git curl wget build-essential python3-dev \
    python3-pip python3-venv htop tmux

# Python 3.11+ installieren (falls nicht vorhanden)
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

### Schritt 2: Bittensor installieren

```bash
# Virtuelle Umgebung erstellen
python3 -m venv ~/.bittensor-venv
source ~/.bittensor-venv/bin/activate

# Bittensor SDK installieren
pip install --upgrade bittensor

# Installation pruefen
btcli --version
```

### Schritt 3: Wallet erstellen

```bash
# Coldkey erstellen (sicher aufbewahren!)
btcli wallet new_coldkey --wallet.name mein_wallet

# Hotkey erstellen
btcli wallet new_hotkey --wallet.name mein_wallet --wallet.hotkey miner_1

# Wallet anzeigen
btcli wallet list
```

**WARNUNG:**
- Coldkey Seed Phrase SICHER aufbewahren (nicht digital!)
- Coldkey auf separatem, sicherem Geraet erstellen
- NIEMALS Coldkey auf Mining-Server speichern

### Schritt 4: Subnet auswaehlen

```bash
# Verfuegbare Subnets anzeigen
btcli subnets list

# Subnet-Details anzeigen
btcli subnets show --netuid [SUBNET_ID]

# Registrierungskosten pruefen
btcli subnets registration_cost --netuid [SUBNET_ID]
```

---

## Lokale Testumgebung

### Warum Testnet?

- **Kostenlos:** Keine echten TAO benoetigt
- **Risikofrei:** Fehler haben keine finanziellen Konsequenzen
- **Lernen:** Protokoll und Tools verstehen
- **Testen:** Eigenen Code testen

### Testnet-Setup

```bash
# Testnet-Config
btcli config set --network test

# Testnet-Wallet erstellen
btcli wallet new_coldkey --wallet.name test_wallet
btcli wallet new_hotkey --wallet.name test_wallet --wallet.hotkey test_miner

# Testnet-Subnet anzeigen
btcli subnets list --network test
```

### Testnet-Registrierung

```bash
# Auf Testnet registrieren (kostenlos)
btcli subnets register \
    --wallet.name test_wallet \
    --wallet.hotkey test_miner \
    --netuid [SUBNET_ID] \
    --network test
```

### Testnet-Miner starten

```bash
# Beispiel-Miner starten (spezifisch pro Subnet)
# Hier: Generischer Beispiel-Miner
python -m neurons.miner \
    --wallet.name test_wallet \
    --wallet.hotkey test_miner \
    --netuid [SUBNET_ID] \
    --subtensor.network test \
    --logging.debug
```

### Testnet-Checkliste

- [ ] Wallet auf Testnet erstellt
- [ ] Auf Testnet-Subnet registriert
- [ ] Miner laeuft stabil
- [ ] Logs zeigen keine Fehler
- [ ] Performance wird erkannt
- [ ] Verbindung zum Netzwerk stabil
- [ ] Mind. 24h Testbetrieb ohne Probleme

---

## Mainnet-Registrierung

### VOR der Registrierung

**ACHTUNG:** Diese Aktion kostet echte TAO und kann NICHT rueckgaengig gemacht werden!

1. **DANGER-Level Approval** einholen (ueber das Multi-Agent System)
2. **Registrierungskosten** pruefen (taeglich veraenderlich)
3. **Subnet sorgfaeltig auswaehlen**
4. **Hardware bereit** haben
5. **Miner-Code** vorbereitet haben
6. **Backup-Plan** haben

### Registrierungsprozess

```bash
# 1. Zu Mainnet wechseln
btcli config set --network finney

# 2. Registrierungskosten pruefen
btcli subnets registration_cost --netuid [SUBNET_ID]

# 3. Registrieren (kostet TAO!)
btcli subnets register \
    --wallet.name mein_wallet \
    --wallet.hotkey miner_1 \
    --netuid [SUBNET_ID]

# 4. Registrierung bestaetigen
btcli subnets show --netuid [SUBNET_ID]
```

### Nach der Registrierung

```bash
# 1. Miner starten
python -m neurons.miner \
    --wallet.name mein_wallet \
    --wallet.hotkey miner_1 \
    --netuid [SUBNET_ID] \
    --subtensor.network finney

# 2. Logs ueberwachen
tail -f ~/.bittensor/miner.log

# 3. Performance pruefen
btcli wallet overview --wallet.name mein_wallet
```

---

## Checkliste

### Vor der Registrierung

- [ ] Hardware ist bereit und getestet
- [ ] Software ist installiert und konfiguriert
- [ ] Wallet ist erstellt (Coldkey + Hotkey)
- [ ] Coldkey Seed Phrase ist sicher aufbewahrt (offline)
- [ ] Testnet-Registrierung erfolgreich
- [ ] Testnet-Miner laeuft stabil (> 24h)
- [ ] Subnet ist sorgfaeltig analysiert
- [ ] Registrierungskosten sind akzeptabel
- [ ] Finanzielles Risiko ist verstanden
- [ ] Deregistration-Risiko ist akzeptabel
- [ ] Monitoring ist eingerichtet
- [ ] Backup-Plan existiert

### Nach der Registrierung

- [ ] Miner laeuft auf Mainnet
- [ ] Logs zeigen keine kritischen Fehler
- [ ] Performance wird erkannt (Scores > 0)
- [ ] Verbindung zum Subnet ist stabil
- [ ] Rewards werden empfangen
- [ ] Monitoring funktioniert
- [ ] Backup laeuft regelmaessig

### Taegliche Ueberwachung

- [ ] Miner laeuft (Uptime-Check)
- [ ] Keine kritischen Fehler in Logs
- [ ] Performance-Scores sind stabil
- [ ] Rewards kommen regelmaessig
- [ ] Hardware-Temperaturen sind normal
- [ ] Internet-Verbindung ist stabil

---

## Kostenuebersicht

### Einmalkosten

| Posten | Schaetzung (EUR) | Hinweis |
|--------|-----------------|---------|
| Hardware (Server) | 1000-3000 | Je nach Subnet-Anforderung |
| Registrierungsgebuehr | 50-500 TAO | Je nach Subnet |
| Erstinstallation | 0 (Eigenarbeit) | Oder Dienstleister |
| **Gesamt** | **1000-3000 EUR + TAO** | |

### Laufende Kosten (monatlich)

| Posten | Schaetzung (EUR) | Hinweis |
|--------|-----------------|---------|
| Strom | 50-200 | Je nach Hardware |
| Internet | 20-50 | Geschaeftsanschluss |
| Server-Housing | 0-100 | Wenn extern |
| Wartung | 0 (Eigenarbeit) | Monitoring, Updates |
| **Gesamt** | **70-350 EUR/Monat** | |

### Kosten-Nutzen-Schaetzung

```
Monatliche Kosten:     70-350 EUR
+ Registrierung:       50-500 TAO (Einmalig)
= Gesamtkosten erster Monat: 70-350 EUR + 50-500 TAO

Geschaezte Rewards:
- Einfaches Subnet:    0.1-1 TAO/Tag = 3-30 TAO/Monat
- Gutes Subnet:        1-5 TAO/Tag = 30-150 TAO/Monat
- Top Subnet:          5+ TAO/Tag = 150+ TAO/Monat

Break-Even: Abhaengig von TAO-Preis und Subnet!
```

**Wichtig:** Rewards sind Schaetzungen und keine Garantien!

---

## Risiken

| Risiko | Wahrscheinlichkeit | Auswirkung | Mitigation |
|--------|-------------------|------------|------------|
| **Deregistration** | Mittel | Hoch | Gute Performance aufrechterhalten |
| **Hardware-Ausfall** | Niedrig | Mittel | Monitoring, Backup-Hardware |
| **Netzwerk-Probleme** | Niedrig | Mittel | Redundante Verbindung |
| **Software-Bugs** | Mittel | Mittel | Regelmaessige Updates |
| **Registrierungskosten steigen** | Hoch | Mittel | Fruehe Registrierung |
| **Subnet wird geschlossen** | Niedrig | Hoch | Diversifikation |
| **TAO-Preis sinkt** | Unbekannt | Hoch | Diversifikation |
| **Wettbewerbsintensitaet steigt** | Hoch | Mittel | Bessere Hardware/Software |

---

*Letzte Aktualisierung: 2025-01-15*
