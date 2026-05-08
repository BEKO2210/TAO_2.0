# Subnet-Recherche Methodik

> Dieses Dokument beschreibt die Methodik, nach der Subnets im Bittensor-Netzwerk recherchiert und bewertet werden. Es definiert Datenquellen, Bewertungskriterien und den Qualitaetsstandard fuer alle Subnet-Analysen.

---

## Inhaltsverzeichnis

- [Ueberblick](#ueberblick)
- [Datenquellen](#datenquellen)
- [Bewertungskriterien](#bewertungskriterien)
- [Ampel-Bewertung](#ampel-bewertung)
- [Datenvalidierung](#datenvalidierung)
- [Unsichere Informationen](#unsichere-informationen)
- [Recherche-Ablauf](#recherche-ablauf)
- [Subnet-Bericht-Template](#subnet-bericht-template)

---

## Ueberblick

Die Subnet-Recherche folgt einem standardisierten Prozess:

```
Schritt 1: Daten sammeln (aus mehreren Quellen)
Schritt 2: Daten validieren (Konsistenz pruefen)
Schritt 3: Kriterien bewerten (10 Kriterien)
Schritt 4: Ampel-Bewertung erstellen
Schritt 5: Bericht generieren
Schritt 6: Unsichere Informationen kennzeichnen
```

Alle Daten werden mit Quellenangabe und Zeitstempel dokumentiert. Nicht validierte Informationen werden explizit als solche gekennzeichnet.

---

## Datenquellen

### Offizielle Quellen (hoechste Vertrauenswuerdigkeit)

| Quelle | URL | Daten | Vertrauen |
|--------|-----|-------|-----------|
| Bittensor Dokumentation | https://docs.bittensor.com | Protokoll, APIs, Guides | Hoch |
| Bittensor GitHub | https://github.com/opentensor/bittensor | Code, Releases, Issues | Hoch |
| TaoStats Explorer | https://taostats.io | On-Chain-Daten, Subnets | Hoch |
| Bittensor Discord | Offizieller Server | Ankuendigungen, Support | Hoch |

### Semi-offizielle Quellen (mittlere Vertrauenswuerdigkeit)

| Quelle | URL | Daten | Vertrauen |
|--------|-----|-------|-----------|
| Subnet GitHub Repos | Variabel pro Subnet | Subnet-Code, Konfiguration | Mittel |
| Community-Wikis | Variabel | Zusammenfassungen, Tutorials | Mittel |
| Blog-Posts | Variabel | Analysen, Tutorials | Mittel |

### Community-Quellen (zu validieren)

| Quelle | URL | Daten | Vertrauen |
|--------|-----|-------|-----------|
| Twitter/X | Einzelne Accounts | Meinungen, News | Niedrig |
| Reddit | r/bittensor | Diskussionen, Fragen | Niedrig |
| YouTube | Einzelne Kanaele | Tutorials, Analysen | Niedrig |
| Foren | Discord-Server einzelner Subnets | Community-Meinungen | Niedrig |

### Quellen-Hierarchie

```
HOCH (immer bevorzugt)
  |
  +-- Offizielle Dokumentation
  +-- Bittensor GitHub
  +-- TaoStats Explorer
  |
MITTEL (mit Quellenangabe)
  |
  +-- Subnet GitHub Repos
  +-- Community-Wikis
  +-- Etablierte Blogs
  |
NIEDRIG (immer als "unbestaetigt" kennzeichnen)
  |
  +-- Social Media
  +-- Foren-Posts
  +-- Unbekannte Blogs
```

---

## Bewertungskriterien

Jedes Subnet wird anhand von **10 Kriterien** bewertet. Jedes Kriterium erhaelt eine Punktzahl von 0-10.

### Kriterium 1: Emissionshoehe (0-10)

**Beschreibung:** Wie viel TAO wird im Subnet pro Epoche verteilt?

| Punkte | Bewertung | Bedeutung |
|--------|-----------|-----------|
| 8-10 | Sehr hoch | > 50 TAO/Epoche |
| 6-7 | Hoch | 20-50 TAO/Epoche |
| 4-5 | Mittel | 10-20 TAO/Epoche |
| 2-3 | Niedrig | 5-10 TAO/Epoche |
| 0-1 | Sehr niedrig | < 5 TAO/Epoche |

**Datenquelle:** TaoStats Explorer, On-Chain-Daten

### Kriterium 2: Teilnehmer-Anzahl (0-10)

**Beschreibung:** Wie viele Miner und Validatoren sind aktiv?

| Punkte | Miner | Validatoren | Bewertung |
|--------|-------|-------------|-----------|
| 8-10 | > 50 | > 10 | Sehr aktiv |
| 6-7 | 20-50 | 5-10 | Aktiv |
| 4-5 | 10-20 | 3-5 | Moderat |
| 2-3 | 5-10 | 1-3 | Wenige |
| 0-1 | < 5 | < 1 | Inaktiv |

**Datenquelle:** TaoStats Explorer

### Kriterium 3: Registrierungskosten (0-10, invertiert)

**Beschreibung:** Wie teuer ist der Eintritt? (Hoehere Kosten = niedrigere Punktzahl)

| Punkte | Kosten (TAO) | Bewertung |
|--------|-------------|-----------|
| 8-10 | < 0.5 TAO | Sehr guenstig |
| 6-7 | 0.5-2 TAO | Guenstig |
| 4-5 | 2-5 TAO | Moderat |
| 2-3 | 5-10 TAO | Teuer |
| 0-1 | > 10 TAO | Sehr teuer |

**Datenquelle:** On-Chain-Registrierungsdaten

### Kriterium 4: Deregistration-Risiko (0-10)

**Beschreibung:** Wie hoch ist die Gefahr, dass das Subnet geschlossen wird?

| Punkte | Risiko | Indikatoren |
|--------|--------|-------------|
| 8-10 | Sehr niedrig | Stabil seit Langem, hohe Teilnehmerzahl |
| 6-7 | Niedrig | Stabil, gute Performance |
| 4-5 | Mittel | Durchschnittliche Stabilitaet |
| 2-3 | Hoch | Wenige Teilnehmer, niedrige Emissionen |
| 0-1 | Sehr hoch | Inaktiv, geringe Nutzung |

**Datenquelle:** Historische Daten, Trend-Analyse

### Kriterium 5: Technische Qualitaet (0-10)

**Beschreibung:** Wie gut ist der Code und die technische Umsetzung?

| Punkte | Bewertung | Indikatoren |
|--------|-----------|-------------|
| 8-10 | Exzellent | Aktive Entwicklung, gute Dokumentation, Tests |
| 6-7 | Gut | Regelmaessige Updates, Dokumentation vorhanden |
| 4-5 | Durchschnittlich | Sporadische Updates, begrenzte Doku |
| 2-3 | Schlecht | Wenig Aktivitaet, keine Doku |
| 0-1 | Inakzeptabel | Keine Aktivitaet, veralteter Code |

**Datenquelle:** GitHub-Repository des Subnets

### Kriterium 6: Community-Aktivitaet (0-10)

**Beschreibung:** Wie aktiv ist die Community?

| Punkte | Bewertung | Indikatoren |
|--------|-----------|-------------|
| 8-10 | Sehr aktiv | Taegliche Posts, aktive Entwickler |
| 6-7 | Aktiv | Regelmaessige Posts, Community vorhanden |
| 4-5 | Moderat | Gelegentliche Aktivitaet |
| 2-3 | Wenig aktiv | Seltene Posts |
| 0-1 | Inaktiv | Keine Aktivitaet |

**Datenquelle:** Discord, GitHub Issues, Social Media

### Kriterium 7: Rentabilitaet fuer Miner (0-10)

**Beschreibung:** Wie rentabel ist das Mining in diesem Subnet?

| Punkte | TAO/Tag (typisch) | Bewertung |
|--------|-------------------|-----------|
| 8-10 | > 1 TAO/Tag | Sehr rentabel |
| 6-7 | 0.5-1 TAO/Tag | Rentabel |
| 4-5 | 0.1-0.5 TAO/Tag | Moderat |
| 2-3 | 0.01-0.1 TAO/Tag | Wenig rentabel |
| 0-1 | < 0.01 TAO/Tag | Nicht rentabel |

**Datenquelle:** TaoStats, Miner-Reports (geschaetzt)

### Kriterium 8: Validator-Stake (0-10)

**Beschreibung:** Wie viel Stake ist im Subnet?

| Punkte | Gesamtstake | Bewertung |
|--------|-------------|-----------|
| 8-10 | > 100k TAO | Sehr hoch |
| 6-7 | 50k-100k TAO | Hoch |
| 4-5 | 10k-50k TAO | Moderat |
| 2-3 | 5k-10k TAO | Niedrig |
| 0-1 | < 5k TAO | Sehr niedrig |

**Datenquelle:** On-Chain-Daten

### Kriterium 9: Innovation/Nutzen (0-10)

**Beschreibung:** Wie innovativ/nuetzlich ist das Subnet?

| Punkte | Bewertung | Indikatoren |
|--------|-----------|-------------|
| 8-10 | Bahnbrechend | Einzigartig, hoher Nutzen |
| 6-7 | Innovativ | Gute Idee, sinnvolle Anwendung |
| 4-5 | Solide | Nuetzlich, aber nicht einzigartig |
| 2-3 | Wenig innovativ | Bekannte Konzepte |
| 0-1 | Ohne Mehrwert | Kein erkennbarer Nutzen |

**Datenquelle:** GitHub README, Dokumentation

### Kriterium 10: Dokumentation (0-10)

**Beschreibung:** Wie gut ist die Dokumentation?

| Punkte | Bewertung | Indikatoren |
|--------|-----------|-------------|
| 8-10 | Exzellent | Vollstaendig, Tutorials, API-Doku |
| 6-7 | Gut | Doku vorhanden, grundlegend |
| 4-5 | Durchschnittlich | Teilweise Doku |
| 2-3 | Schlecht | Minimale Doku |
| 0-1 | Keine | Keine Dokumentation |

**Datenquelle:** GitHub, Projekt-Website

---

## Ampel-Bewertung

### Gesamtbewertung

Die 10 Kriterien ergeben eine Gesamtpunktzahl von 0-100:

| Gesamtpunktzahl | Ampel | Empfehlung |
|-----------------|-------|------------|
| 80-100 | Gruen | Sehr empfehlenswert |
| 60-79 | Gruen-Gelb | Empfehlenswert |
| 40-59 | Gelb | Durchschnitt |
| 20-39 | Orange | Vorsicht |
| 0-19 | Rot | Nicht empfohlen |

### Ampel-Visualisierung

```
80-100:  [Gruen]   ██ Sehr empfehlenswert
60-79:   [L-Gruen] ██ Empfehlenswert
40-59:   [Gelb]    ██ Durchschnitt
20-39:   [Orange]  ██ Vorsicht
0-19:    [Rot]     ██ Nicht empfohlen
```

### Kriterien-spezifische Ampeln

Jedes Kriterium erhaelt ebenfalls eine Ampel:

```
Subnet X Analyse:
+-------------------------+-------+--------+
| Kriterium               | Score | Ampel  |
+-------------------------+-------+--------+
| Emissionshoehe          | 8/10  | Gruen  |
| Teilnehmer-Anzahl       | 7/10  | Gruen  |
| Registrierungskosten    | 4/10  | Gelb   |
| Deregistration-Risiko   | 2/10  | Orange |
| Technische Qualitaet    | 9/10  | Gruen  |
| Community-Aktivitaet    | 6/10  | Gruen  |
| Rentabilitaet           | 5/10  | Gelb   |
| Validator-Stake         | 7/10  | Gruen  |
| Innovation/Nutzen       | 8/10  | Gruen  |
| Dokumentation           | 7/10  | Gruen  |
+-------------------------+-------+--------+
| GESAMT                  | 63/100| Gruen  |
+-------------------------+-------+--------+
```

---

## Datenvalidierung

### Validierungsprozess

```
Daten empfangen
      |
      v
+-----+-----+
| Quelle    |
| bekannt?  |
+-----+-----+
  |      |
 Ja      Nein
  |      |
  v      v
+--+---------+     +----------------+
| Vertrauens |     | Als unbestaetigt|
| wuerdig?   |     | markieren       |
+--+---------+     +--------+-------+
   |      |                  |
  Ja      Nein               |
   |      |                  |
   v      v                  |
+--+------+--+               |
| Konsistenz |               |
| pruefen    |               |
+--+------+--+               |
   |      |                  |
  OK      Inkonsist.         |
   |      |                  |
   v      v                  |
+--+------+--+   +-----------+-----------+
| Daten    |     | Mehrere Quellen       |
| uebernehmen|   | pruefen               |
+-----------+   +-----------+-----------+
                            |
                    +-------+-------+
                    | Konsens?      |
                    +-------+-------+
                     |            |
                    Ja           Nein
                     |            |
                     v            v
               +----------+  +-----------+
               | Ueberneh- |  | Unsicher  |
               | men       |  | markieren |
               +----------+  +-----------+
```

### Validierungsregeln

1. **Quellenpruefung:** Nur bekannte, vertrauenswuerdige Quellen werden als "validiert" markiert
2. **Konsistenzpruefung:** Daten werden gegen mindestens 2 Quellen geprueft
3. **Zeitstempel:** Alle Daten erhalten einen Zeitstempel
4. **Plausibilitaet:** Werte muessen in erwarteten Bereichen liegen
5. **Cross-Reference:** Bei Widerspruechen wird die Mehrheit der Quellen verwendet

### Vertrauens-Level

| Level | Bedingung | Kennzeichnung |
|-------|-----------|---------------|
| **Validiert** | Mehrere offizielle Quellen bestaetigen | Keine Kennzeichnung |
| **Bestaetigt** | Eine offizielle Quelle bestaetigt | Keine Kennzeichnung |
| **Wahrscheinlich** | Mehrere unabhaengige Quellen | *(wahrscheinlich)* |
| **Unbestaetigt** | Nur eine Quelle, nicht offiziell | *(unbestaetigt)* |
| **Unsicher** | Widerspruechliche Informationen | *(unsicher)* |
| **Vermutet** | Keine direkte Bestaetigung | *(vermutet)* |

---

## Unsichere Informationen

### Kennzeichnung im Bericht

```markdown
## Subnet X Analyse

### Emissionshoehe
- **Wert:** 45.2 TAO/Epoche *(validiert — TaoStats)*

### Registrierungskosten
- **Wert:** 2.5 TAO *(unbestaetigt — nur eine Quelle)*

### Zukuenftige Emissionsaenderung
- **Wert:** Moegliche Reduktion in Q2 *(vermutet — Community-Geruecht)*

### Teilnehmeranzahl
- **Wert:** 32 Miner, 8 Validatoren *(validiert — On-Chain)*
```

### Kennzeichnungs-Legende

| Kennzeichnung | Bedeutung | Vertrauens-Level |
|---------------|-----------|-----------------|
| *(keine Kennzeichnung)* | Mehrfach validiert | Hoch |
| *(bestaetigt)* | Offizielle Quelle bestaetigt | Hoch |
| *(wahrscheinlich)* | Mehrere unabhaengige Quellen | Mittel |
| *(unbestaetigt)* | Einzelquelle | Niedrig |
| *(unsicher)* | Widerspruechliche Daten | Sehr niedrig |
| *(vermutet)* | Keine Bestaetigung | Spekulativ |
| *(veraltet)* | Daten aelter als 7 Tage | Pruefen |

---

## Recherche-Ablauf

### Standardablauf

```
Phase 1: Initialisierung (0-2 Min.)
  - Subnet-ID identifizieren
  - Bekannte Daten laden (Cache)
  - Datenquellen vorbereiten

Phase 2: On-Chain-Daten (2-5 Min.)
  - Emissionen abrufen
  - Teilnehmerzahlen abrufen
  - Stake-Daten abrufen
  - Registrierungskosten abrufen

Phase 3: Off-Chain-Daten (3-7 Min.)
  - GitHub-Repository analysieren
  - Dokumentation pruefen
  - Community-Aktivitaet messen

Phase 4: Bewertung (1-2 Min.)
  - 10 Kriterien bewerten
  - Ampel-Bewertung erstellen
  - Risiken identifizieren

Phase 5: Validierung (1-2 Min.)
  - Daten konsistenz pruefen
  - Quellen validieren
  - Unsichere Daten kennzeichnen

Phase 6: Bericht (1 Min.)
  - Markdown-Bericht generieren
  - Quellen auflisten
  - Empfehlung formulieren

GESAMTDAUER: ca. 8-19 Minuten
```

### Schnellablauf (fuer bekannte Subnets)

```
Phase 1: Cache pruefen (0-1 Min.)
  - Wenn Cache aktuell (< 1h): Cache verwenden
  - Sonst: Neu laden

Phase 2: Aktualisierung (2-5 Min.)
  - Nur On-Chain-Daten aktualisieren
  - Vergleich mit vorheriger Analyse

Phase 3: Bericht (30 Sek.)
  - Aktualisierten Bericht generieren

GESAMTDAUER: ca. 2-6 Minuten
```

---

## Subnet-Bericht-Template

```markdown
# Subnet [ID] — [Name] Analyse

**Datum:** YYYY-MM-DD HH:MM  
**Analyst:** Subnet Research Agent  
**Datenquellen:** [Liste]  
**Vertrauenslevel:** [Validiert / Unbestaetigt]

---

## Zusammenfassung

| Kennzahl | Wert | Trend |
|----------|------|-------|
| Gesamtbewertung | [X/100] | [Stabil / Steigend / Fallend] |
| Ampel | [Gruen/Gelb/Orange/Rot] | |

## Kriterien-Bewertung

### 1. Emissionshoehe: [X/10]
- Aktuell: [X] TAO/Epoche
- Quelle: [TaoStats / On-Chain]

### 2. Teilnehmer-Anzahl: [X/10]
- Miner: [X]
- Validatoren: [X]

### 3. Registrierungskosten: [X/10]
- Aktuell: [X] TAO
- Trend: [Steigend / Fallend / Stabil]

### 4. Deregistration-Risiko: [X/10]
- Einschaetzung: [Niedrig / Mittel / Hoch]
- Gruende: [...]

### 5. Technische Qualitaet: [X/10]
- GitHub-Aktivitaet: [Commits, Issues]
- Letztes Update: [Datum]

### 6. Community-Aktivitaet: [X/10]
- Discord-Mitglieder: [X]
- Taegliche Posts: [X]

### 7. Rentabilitaet: [X/10]
- Schaetzung: [X] TAO/Tag (Miner)
- Hinweis: *(geschaetzt, nicht garantiert)*

### 8. Validator-Stake: [X/10]
- Gesamtstake: [X] TAO

### 9. Innovation/Nutzen: [X/10]
- Beschreibung: [...]
- Bewertung: [...]

### 10. Dokumentation: [X/10]
- Vorhanden: [Ja/Nein]
- Qualitaet: [...]

## Gesamtbewertung

**Punktzahl:** [X/100]  
**Ampel:** [Farbe]  
**Empfehlung:** [Text]

## Risk-Bewertung

| Risiko | Level | Beschreibung |
|--------|-------|-------------|
| Deregistration | [Level] | [...] |
| Rentabilitaet | [Level] | [...] |
| Technisch | [Level] | [...] |

## Unsichere Informationen

- [Liste aller als unsicher markierten Daten]

## Quellen

1. [Quelle 1 — URL]
2. [Quelle 2 — URL]
3. [Quelle 3 — URL]

## Disclaimer

> Diese Analyse ist eine Recherche-Ergebnis und stellt keine Finanzberatung dar.
> Alle Angaben ohne Gewaehr. Kryptowaehrungen sind hochspekulativ.
```

---

*Letzte Aktualisierung: 2025-01-15*
