# =============================================================================
# TAO / Bittensor Multi-Agent System — Makefile
# =============================================================================
# VERWENDUNG: make <target>
# "make help" zeigt alle verfuegbaren Targets an.
# =============================================================================

# ---------------------------------------------------------------------------
# KONFIGURATION
# ---------------------------------------------------------------------------
.PHONY: help setup install install-dev test lint format typecheck clean \
        docker-build docker-up docker-down docker-logs docker-clean \
        run-cli run-dashboard run-daemon db-init db-migrate db-backup \
        db-restore db-reset check health status logs open-dashboard \
        release dist

# Python-Konfiguration
PYTHON := python3
PIP := pip3
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin
VENV_PYTHON := $(VENV_BIN)/python
VENV_PIP := $(VENV_BIN)/pip

# Docker-Konfiguration
DOCKER_COMPOSE := docker compose
DOCKER_IMAGE := tao-bittensor-agents
DOCKER_TAG := latest

# Projekt-Pfade
SRC_DIR := src
TESTS_DIR := tests
DATA_DIR := data
LOGS_DIR := logs
CONFIG_DIR := config

# Default Target: Hilfe anzeigen
.DEFAULT_GOAL := help

# Farben fuer Ausgabe
BLUE := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m
BOLD := \033[1m

# ---------------------------------------------------------------------------
# HILFE — Default Target
# ---------------------------------------------------------------------------
help: ## Zeigt diese Hilfeseite an
	@echo ""
	@echo "$(BOLD)$(BLUE)╔══════════════════════════════════════════════════════════════════════╗$(RESET)"
	@echo "$(BOLD)$(BLUE)║     TAO / Bittensor Multi-Agent System — Verfuegbare Befehle      ║$(RESET)"
	@echo "$(BOLD)$(BLUE)╚══════════════════════════════════════════════════════════════════════╝$(RESET)"
	@echo ""
	@echo "$(BOLD)$(GREEN)Setup & Installation:$(RESET)"
	@echo "  $(YELLOW)make setup$(RESET)          Komplettes Setup (venv + deps + db)"
	@echo "  $(YELLOW)make install$(RESET)        Abhaengigkeiten installieren"
	@echo "  $(YELLOW)make install-dev$(RESET)    Abhaengigkeiten + Dev-Tools installieren"
	@echo ""
	@echo "$(BOLD)$(GREEN)Entwicklung:$(RESET)"
	@echo "  $(YELLOW)make test$(RESET)           Alle Tests ausfuehren"
	@echo "  $(YELLOW)make test-verbose$(RESET)   Tests mit Detail-Ausgabe"
	@echo "  $(YELLOW)make lint$(RESET)           Code-Linting (ruff)"
	@echo "  $(YELLOW)make format$(RESET)         Code-Formatierung (ruff format)"
	@echo "  $(YELLOW)make typecheck$(RESET)      Typ-Ueberpruefung (mypy)"
	@echo "  $(YELLOW)make check$(RESET)          Lint + Format + Typecheck + Test"
	@echo ""
	@echo "$(BOLD)$(GREEN)Docker:$(RESET)"
	@echo "  $(YELLOW)make docker-build$(RESET)   Docker-Image bauen"
	@echo "  $(YELLOW)make docker-up$(RESET)      Container starten"
	@echo "  $(YELLOW)make docker-up-full$(RESET) Container + Dashboard + Backup starten"
	@echo "  $(YELLOW)make docker-down$(RESET)    Container stoppen"
	@echo "  $(YELLOW)make docker-logs$(RESET)    Container-Logs anzeigen"
	@echo "  $(YELLOW)make docker-clean$(RESET)   Container + Volumes + Images bereinigen"
	@echo ""
	@echo "$(BOLD)$(GREEN)Ausfuehrung:$(RESET)"
	@echo "  $(YELLOW)make run-cli$(RESET)        CLI-Modus starten"
	@echo "  $(YELLOW)make run-dashboard$(RESET)  Streamlit-Dashboard starten"
	@echo "  $(YELLOW)make run-daemon$(RESET)     Daemon-Modus starten"
	@echo ""
	@echo "$(BOLD)$(GREEN)Datenbank:$(RESET)"
	@echo "  $(YELLOW)make db-init$(RESET)        Datenbank initialisieren"
	@echo "  $(YELLOW)make db-migrate$(RESET)     Datenbank-Migrationen ausfuehren"
	@echo "  $(YELLOW)make db-backup$(RESET)      Datenbank-Backup erstellen"
	@echo "  $(YELLOW)make db-restore$(RESET)     Datenbank aus Backup wiederherstellen"
	@echo "  $(YELLOW)make db-reset$(RESET)       Datenbank zuruecksetzen (WARNUNG: Datenverlust!)"
	@echo ""
	@echo "$(BOLD)$(GREEN)Wartung:$(RESET)"
	@echo "  $(YELLOW)make clean$(RESET)          Temporaere Dateien loeschen"
	@echo "  $(YELLOW)make clean-all$(RESET)      Alles loeschen (inkl. venv, db)"
	@echo "  $(YELLOW)make health$(RESET)         System-Health-Check"
	@echo "  $(YELLOW)make status$(RESET)         System-Status anzeigen"
	@echo "  $(YELLOW)make logs$(RESET)           Logs anzeigen"
	@echo "  $(YELLOW)make open-dashboard$(RESET) Dashboard im Browser oeffnen"
	@echo ""
	@echo "$(BOLD)$(GREEN)Release:$(RESET)"
	@echo "  $(YELLOW)make dist$(RESET)           Distribution-Paket erstellen"
	@echo ""
	@echo "$(BOLD)$(BLUE)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "$(BOLD)Hinweis:$(RESET) Alle Befehle werden mit $(VENV_PYTHON) ausgefuehrt."
	@echo "$(BOLD)Docker:$(RESET) 'make docker-up' startet die containerisierte Version."
	@echo "$(BOLD)Sicherheit:$(RESET) Stelle sicher, dass .env korrekt konfiguriert ist."
	@echo "$(BOLD)$(BLUE)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo ""

# =============================================================================
# SETUP & INSTALLATION
# =============================================================================

setup: ## Komplettes Setup: venv erstellen, deps installieren, db initialisieren
	@echo "$(GREEN)>>> Starte komplettes Setup...$(RESET)"
	@$(MAKE) venv
	@$(MAKE) install
	@$(MAKE) db-init
	@echo "$(GREEN)>>> Setup abgeschlossen!$(RESET)"
	@echo "$(YELLOW)    Bitte .env konfigurieren: cp .env.example .env$(RESET)"

venv: ## Virtuelle Umgebung erstellen
	@echo "$(GREEN)>>> Erstelle virtuelle Umgebung...$(RESET)"
	@$(PYTHON) -m venv $(VENV_DIR)
	@echo "$(GREEN)>>> Virtuelle Umgebung erstellt in $(VENV_DIR)/$(RESET)"

install: ## Produktions-Abhaengigkeiten installieren
	@echo "$(GREEN)>>> Installiere Abhaengigkeiten...$(RESET)"
	@test -d $(VENV_DIR) || $(MAKE) venv
	@$(VENV_PIP) install --upgrade pip
	@$(VENV_PIP) install -r requirements.txt
	@echo "$(GREEN)>>> Abhaengigkeiten installiert.$(RESET)"

install-dev: ## Entwicklungs-Abhaengigkeiten installieren
	@echo "$(GREEN)>>> Installiere Abhaengigkeiten + Dev-Tools...$(RESET)"
	@test -d $(VENV_DIR) || $(MAKE) venv
	@$(VENV_PIP) install --upgrade pip
	@$(VENV_PIP) install -r requirements.txt
	@$(VENV_PIP) install -r requirements-dev.txt
	@echo "$(GREEN)>>> Dev-Abhaengigkeiten installiert.$(RESET)"

# =============================================================================
# ENTWICKLUNG
# =============================================================================

test: ## Alle Tests ausfuehren
	@echo "$(GREEN)>>> Fuehre Tests aus...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden. Fuehre 'make setup' aus.$(RESET)" && exit 1)
	@cd $(SRC_DIR) && $(VENV_PYTHON) -m pytest $(TESTS_DIR)/ -v --tb=short
	@echo "$(GREEN)>>> Tests abgeschlossen.$(RESET)"

test-verbose: ## Tests mit ausfuehrlicher Ausgabe
	@echo "$(GREEN)>>> Fuehre Tests aus (verbose)...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden. Fuehre 'make setup' aus.$(RESET)" && exit 1)
	@cd $(SRC_DIR) && $(VENV_PYTHON) -m pytest $(TESTS_DIR)/ -vv --tb=long --showlocals

test-coverage: ## Test-Coverage-Bericht erstellen
	@echo "$(GREEN)>>> Erstelle Coverage-Bericht...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@cd $(SRC_DIR) && $(VENV_PYTHON) -m pytest $(TESTS_DIR)/ --cov=$(SRC_DIR) --cov-report=html --cov-report=term-missing
	@echo "$(GREEN)>>> Coverage-Bericht: htmlcov/index.html$(RESET)"

bench: ## Alle Benchmarks ausfuehren (mock mode, no network)
	@echo "$(GREEN)>>> ApprovalGate-Throughput...$(RESET)"
	@$(VENV_PYTHON) -m scripts.bench_approval_gate
	@echo ""
	@echo "$(GREEN)>>> Per-Agent-Latenz...$(RESET)"
	@$(VENV_PYTHON) -m scripts.bench_agents
	@echo ""
	@echo "$(GREEN)>>> Orchestrator end-to-end...$(RESET)"
	@$(VENV_PYTHON) -m scripts.bench_orchestrator
	@echo ""
	@echo "$(GREEN)>>> Live-Collectors (opt-in TAO_BENCH_LIVE=1)...$(RESET)"
	@$(VENV_PYTHON) -m scripts.bench_live
	@echo ""
	@echo "$(GREEN)>>> Ergebnisse: bench/results/*.json$(RESET)"

bench-live: ## Live-Collector-Benchmarks gegen echte Endpunkte (Netzwerk!)
	@TAO_BENCH_LIVE=1 $(VENV_PYTHON) -m scripts.bench_live

lint: ## Code-Linting mit ruff
	@echo "$(GREEN)>>> Fuehre Linting durch...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@$(VENV_PYTHON) -m ruff check $(SRC_DIR)/
	@echo "$(GREEN)>>> Linting abgeschlossen.$(RESET)"

lint-fix: ## Code-Linting mit automatischen Fixes
	@echo "$(GREEN)>>> Fuehre Linting mit Fixes durch...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@$(VENV_PYTHON) -m ruff check --fix $(SRC_DIR)/
	@echo "$(GREEN)>>> Linting mit Fixes abgeschlossen.$(RESET)"

format: ## Code-Formatierung
	@echo "$(GREEN)>>> Formatiere Code...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@$(VENV_PYTHON) -m ruff format $(SRC_DIR)/
	@echo "$(GREEN)>>> Formatierung abgeschlossen.$(RESET)"

typecheck: ## Statische Typ-Ueberpruefung mit mypy
	@echo "$(GREEN)>>> Fuehre Typ-Ueberpruefung durch...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@$(VENV_PYTHON) -m mypy $(SRC_DIR)/ --ignore-missing-imports
	@echo "$(GREEN)>>> Typ-Ueberpruefung abgeschlossen.$(RESET)"

check: ## Komplette Qualitaetspruefung (lint + format + typecheck + test)
	@echo "$(BOLD)$(BLUE)>>> Starte komplette Qualitaetspruefung...$(RESET)"
	@$(MAKE) lint
	@$(MAKE) format
	@$(MAKE) typecheck
	@$(MAKE) test
	@echo "$(BOLD)$(GREEN)>>> Alle Pruefungen bestanden!$(RESET)"

# =============================================================================
# DOCKER
# =============================================================================

docker-build: ## Docker-Image bauen
	@echo "$(GREEN)>>> Baue Docker-Images...$(RESET)"
	@$(DOCKER_COMPOSE) build --no-cache
	@echo "$(GREEN)>>> Docker-Build abgeschlossen.$(RESET)"

docker-up: ## Container starten (App only)
	@echo "$(GREEN)>>> Starte Container (App)...$(RESET)"
	@$(DOCKER_COMPOSE) up -d app
	@echo "$(GREEN)>>> Container gestartet.$(RESET)"
	@echo "$(YELLOW)    Logs: make docker-logs$(RESET)"

docker-up-dashboard: ## Container + Dashboard starten
	@echo "$(GREEN)>>> Starte Container (App + Dashboard)...$(RESET)"
	@$(DOCKER_COMPOSE) --profile dashboard up -d
	@echo "$(GREEN)>>> Container gestartet.$(RESET)"
	@echo "$(YELLOW)    Dashboard: http://localhost:8501$(RESET)"

docker-up-full: ## Alle Container starten (App + Dashboard + Backup)
	@echo "$(GREEN)>>> Starte alle Container...$(RESET)"
	@$(DOCKER_COMPOSE) --profile full up -d
	@echo "$(GREEN)>>> Alle Container gestartet.$(RESET)"

docker-down: ## Alle Container stoppen
	@echo "$(YELLOW)>>> Stoppe Container...$(RESET)"
	@$(DOCKER_COMPOSE) down
	@echo "$(GREEN)>>> Container gestoppt.$(RESET)"

docker-down-volumes: ## Container stoppen und Volumes loeschen
	@echo "$(RED)>>> Stoppe Container und loesche Volumes...$(RESET)"
	@$(DOCKER_COMPOSE) down -v
	@echo "$(GREEN)>>> Container und Volumes entfernt.$(RESET)"

docker-logs: ## Container-Logs anzeigen
	@$(DOCKER_COMPOSE) logs -f --tail=100

docker-clean: ## Container, Volumes, Netzwerke und Images bereinigen
	@echo "$(RED)>>> Bereinige Docker-Artefakte...$(RESET)"
	@$(DOCKER_COMPOSE) down -v --remove-orphans
	@docker rmi $(DOCKER_IMAGE):$(DOCKER_TAG) 2>/dev/null || true
	@echo "$(GREEN)>>> Docker-Bereinigung abgeschlossen.$(RESET)"

docker-shell: ## Shell im App-Container oeffnen
	@$(DOCKER_COMPOSE) exec app /bin/bash

# =============================================================================
# AUSFUEHRUNG
# =============================================================================

run-cli: ## CLI-Modus starten (interaktiv)
	@echo "$(GREEN)>>> Starte CLI-Modus...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden. Fuehre 'make setup' aus.$(RESET)" && exit 1)
	@test -f .env || (echo "$(YELLOW).env nicht gefunden. Kopiere von .env.example$(RESET)" && cp .env.example .env)
	@$(VENV_PYTHON) -m $(SRC_DIR).orchestrator --mode cli

run-dashboard: ## Streamlit-Dashboard starten
	@echo "$(GREEN)>>> Starte Dashboard...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@test -f .env || (echo "$(YELLOW).env nicht gefunden. Kopiere von .env.example$(RESET)" && cp .env.example .env)
	@$(VENV_PYTHON) -m streamlit run dashboard/app.py --server.port=8501 --server.address=127.0.0.1

run-daemon: ## Daemon-Modus starten (Hintergrund)
	@echo "$(GREEN)>>> Starte Daemon-Modus...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@test -f .env || (echo "$(YELLOW).env nicht gefunden.$(RESET)" && cp .env.example .env)
	@nohup $(VENV_PYTHON) -m $(SRC_DIR).orchestrator --mode daemon > $(LOGS_DIR)/daemon.log 2>&1 &
	@echo "$(GREEN)>>> Daemon gestartet. PID: $$!$(RESET)"
	@echo "$(YELLOW)    Logs: tail -f $(LOGS_DIR)/daemon.log$(RESET)"

stop-daemon: ## Daemon-Modus stoppen
	@echo "$(YELLOW)>>> Stoppe Daemon...$(RESET)"
	@-pkill -f "$(SRC_DIR).orchestrator --mode daemon" 2>/dev/null
	@echo "$(GREEN)>>> Daemon gestoppt.$(RESET)"

# =============================================================================
# DATENBANK
# =============================================================================

db-init: ## Datenbank initialisieren
	@echo "$(GREEN)>>> Initialisiere Datenbank...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@mkdir -p $(DATA_DIR)
	@$(VENV_PYTHON) -m $(SRC_DIR).core.database init --path $(DATA_DIR)/agents.db
	@echo "$(GREEN)>>> Datenbank initialisiert: $(DATA_DIR)/agents.db$(RESET)"

db-migrate: ## Datenbank-Migrationen ausfuehren
	@echo "$(GREEN)>>> Fuehre Migrationen aus...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@$(VENV_PYTHON) -m $(SRC_DIR).core.database migrate --path $(DATA_DIR)/agents.db
	@echo "$(GREEN)>>> Migrationen abgeschlossen.$(RESET)"

db-backup: ## Datenbank-Backup erstellen
	@echo "$(GREEN)>>> Erstelle Datenbank-Backup...$(RESET)"
	@mkdir -p $(DATA_DIR)/backups
	@BACKUP_FILE="$(DATA_DIR)/backups/agents_$$(date +%Y%m%d_%H%M%S).db"; \
	cp $(DATA_DIR)/agents.db $${BACKUP_FILE}; \
	echo "$(GREEN)>>> Backup erstellt: $${BACKUP_FILE}$(RESET)"

db-restore: ## Datenbank aus Backup wiederherstellen (interaktiv)
	@echo "$(YELLOW)>>> Verfuegbare Backups:$(RESET)"
	@ls -1t $(DATA_DIR)/backups/*.db 2>/dev/null | head -10
	@echo "$(YELLOW)    Backup-Datei eingeben:$(RESET)"
	@read backup_file; \
	if [ -f "$${backup_file}" ]; then \
		cp "$${backup_file}" $(DATA_DIR)/agents.db; \
		echo "$(GREEN)>>> Datenbank wiederhergestellt.$(RESET)"; \
	else \
		echo "$(RED)>>> Backup nicht gefunden.$(RESET)"; \
	fi

db-reset: ## Datenbank zuruecksetzen (WARNUNG: ALLE DATEN VERLOREN!)
	@echo "$(RED)WARNUNG: Diese Aktion loescht ALLE Daten!$(RESET)"
	@echo "$(YELLOW)    Abbrechen mit Ctrl+C, fortfahren mit Enter...$(RESET)"
	@read dummy
	@rm -f $(DATA_DIR)/agents.db
	@$(MAKE) db-init
	@echo "$(GREEN)>>> Datenbank zurueckgesetzt.$(RESET)"

# =============================================================================
# WARTUNG
# =============================================================================

clean: ## Temporaere Dateien loeschen
	@echo "$(GREEN)>>> Bereinige temporare Dateien...$(RESET)"
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name "*.egg-info" -delete 2>/dev/null || true
	@rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/ htmlcov/ build/ dist/
	@rm -rf *.egg-info/
	@echo "$(GREEN)>>> Bereinigung abgeschlossen.$(RESET)"

clean-all: ## Alles loeschen (inkl. venv, db, logs)
	@echo "$(RED)WARNUNG: Diese Aktion loescht venv, Datenbank und Logs!$(RESET)"
	@echo "$(YELLOW)    Abbrechen mit Ctrl+C, fortfahren mit Enter...$(RESET)"
	@read dummy
	@$(MAKE) clean
	@rm -rf $(VENV_DIR)/
	@rm -rf $(DATA_DIR)/agents.db
	@rm -rf $(LOGS_DIR)/*
	@echo "$(GREEN)>>> Alles bereinigt. Fuehre 'make setup' fuer Neuinstallation aus.$(RESET)"

health: ## System-Health-Check
	@echo "$(GREEN)>>> Pruefe System-Status...$(RESET)"
	@test -d $(VENV_DIR) && echo "  $(GREEN)✓$(RESET) Virtuelle Umgebung" || echo "  $(RED)✗$(RESET) Virtuelle Umgebung fehlt"
	@test -f .env && echo "  $(GREEN)✓$(RESET) .env existiert" || echo "  $(YELLOW)⚠$(RESET) .env fehlt (cp .env.example .env)"
	@test -f $(DATA_DIR)/agents.db && echo "  $(GREEN)✓$(RESET) Datenbank existiert" || echo "  $(YELLOW)⚠$(RESET) Datenbank fehlt (make db-init)"
	@test -f requirements.txt && echo "  $(GREEN)✓$(RESET) requirements.txt" || echo "  $(RED)✗$(RESET) requirements.txt fehlt"
	@echo "$(GREEN)>>> Health-Check abgeschlossen.$(RESET)"

status: ## System-Status anzeigen
	@echo "$(BOLD)$(BLUE)System-Status$(RESET)"
	@echo "$(BLUE)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"
	@echo "Python:      $(GREEN)$(shell $(PYTHON) --version 2>/dev/null || echo 'nicht gefunden')$(RESET)"
	@echo "Venv:        $(GREEN)$(VENV_DIR)$(RESET)"
	@echo "Wallet-Modus: $(GREEN)$(shell grep WALLET_MODE .env 2>/dev/null | cut -d= -f2 || echo 'unbekannt')$(RESET)"
	@echo "Netzwerk:    $(GREEN)$(shell grep NETWORK_MODE .env 2>/dev/null | cut -d= -f2 || echo 'unbekannt')$(RESET)"
	@echo "Log-Level:   $(GREEN)$(shell grep LOG_LEVEL .env 2>/dev/null | cut -d= -f2 || echo 'INFO')$(RESET)"
	@echo "Docker:      $(GREEN)$(shell docker --version 2>/dev/null || echo 'nicht installiert')$(RESET)"
	@echo "$(BLUE)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(RESET)"

logs: ## Logs anzeigen
	@test -d $(LOGS_DIR) || (echo "$(YELLOW)Log-Verzeichnis nicht gefunden.$(RESET)" && exit 0)
	@tail -n 50 $(LOGS_DIR)/*.log 2>/dev/null || echo "$(YELLOW)Keine Log-Dateien gefunden.$(RESET)"

open-dashboard: ## Dashboard im Browser oeffnen
	@echo "$(GREEN)>>> Oeffne Dashboard...$(RESET)"
	@python -m webbrowser "http://localhost:8501" 2>/dev/null || \
	echo "$(YELLOW)    Bitte manuell oeffnen: http://localhost:8501$(RESET)"

# =============================================================================
# RELEASE
# =============================================================================

dist: ## Distribution-Paket erstellen
	@echo "$(GREEN)>>> Erstelle Distribution...$(RESET)"
	@test -d $(VENV_DIR) || (echo "$(RED)Venv nicht gefunden.$(RESET)" && exit 1)
	@$(VENV_PIP) install build twine
	@$(VENV_PYTHON) -m build
	@echo "$(GREEN)>>> Distribution erstellt in dist/$(RESET)"

# =============================================================================
# HILFREICHE ALIASES
# =============================================================================

s: status ## Alias fuer status
q: check  ## Alias fuer check (quality)
d: docker-up ## Alias fuer docker-up
b: docker-build ## Alias fuer docker-build
c: clean ## Alias fuer clean
