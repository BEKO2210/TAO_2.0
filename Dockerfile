# =============================================================================
# TAO / Bittensor Multi-Agent System — Dockerfile
# =============================================================================
# Multi-Stage Build fuer optimale Image-Groesse
# =============================================================================

# ---------------------------------------------------------------------------
# STAGE 1: Basis-Image mit Python
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

# System-Abhaengigkeiten
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis
WORKDIR /app

# ---------------------------------------------------------------------------
# STAGE 2: Abhaengigkeiten installieren
# ---------------------------------------------------------------------------
FROM base AS dependencies

# Requirements zuerst kopieren (fuer Layer-Caching)
COPY requirements.txt requirements-dev.txt ./

# Python-Abhaengigkeiten installieren
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# STAGE 3: Produktions-Image
# ---------------------------------------------------------------------------
FROM dependencies AS production

# Anwendungscode kopieren
COPY src/ ./src/
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY KIMI.md ./
COPY README.md ./

# Nicht-Root Benutzer erstellen
RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    mkdir -p /app/data /app/logs /app/data/reports /app/data/backups && \
    chown -R appuser:appuser /app

USER appuser

# Health-Check Endpunkt
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=5)" || exit 1

# Standard-Port
EXPOSE 8080

# Start-Kommando
CMD ["python", "-m", "src.orchestrator", "--mode", "daemon"]

# ---------------------------------------------------------------------------
# STAGE 4: Dashboard-Image (optional)
# ---------------------------------------------------------------------------
FROM production AS dashboard

# Dashboard-Code kopieren
COPY dashboard/ ./dashboard/

# Streamlit-Port
EXPOSE 8501

# Health-Check fuer Streamlit
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Start-Kommando fuer Dashboard
CMD ["python", "-m", "streamlit", "run", "dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
