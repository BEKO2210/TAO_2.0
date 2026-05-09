"""
Command cheat-sheet for the dashboard's "Wie rede ich mit dem System"
panel.

The TAO Swarm has no chat / NLU surface — by design. Trading systems
that accept free-form prompts have a large attack surface. The
"language" you speak to this system is:

1. **CLI commands** (the canonical interface)
2. **Dashboard** (read-only monitor + halt button)
3. **Files** (env vars, kill-switch flag, status JSON)
4. **Direct SQLite queries** on the trade ledger

This module exposes ``cheat_sheet_groups()`` returning a structured
list of those interactions so the dashboard sidebar can render a
compact, copy-paste-friendly reference. The caller decides how to
display it (Streamlit ``st.code`` blocks, plain markdown, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CheatItem:
    """One line in the cheat-sheet — a command + what it does."""

    command: str
    description: str


@dataclass(frozen=True)
class CheatGroup:
    """A named group of related cheat-sheet items."""

    title: str
    icon: str
    items: tuple[CheatItem, ...] = field(default_factory=tuple)
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "icon": self.icon,
            "note": self.note,
            "items": [
                {"command": i.command, "description": i.description}
                for i in self.items
            ],
        }


def cheat_sheet_groups() -> list[CheatGroup]:
    """Return the canonical command cheat-sheet.

    The list is ordered from "first-time user" to "power user". The
    dashboard renders these as collapsible sections in the sidebar.
    """
    return [
        CheatGroup(
            title="Erste Schritte",
            icon="🚀",
            items=(
                CheatItem(
                    "tao-swarm version",
                    "Version + Mode-Banner anzeigen",
                ),
                CheatItem(
                    "tao-swarm --live --network finney status",
                    "System-Check gegen reale Mainnet-Endpoints",
                ),
                CheatItem(
                    "tao-swarm --live subnets --limit 5",
                    "129 reale Subnets mit echten tao_in / Volume",
                ),
                CheatItem(
                    "tao-swarm --live market",
                    "TAO-Preis, Marketcap, 24h Volume",
                ),
            ),
        ),
        CheatGroup(
            title="Backtest",
            icon="🧪",
            items=(
                CheatItem(
                    "tao-swarm trade backtest "
                    "--strategy momentum_rotation "
                    "--snapshots ./snapshots.json",
                    "Strategie gegen historische Snapshots laufen lassen",
                ),
                CheatItem(
                    "tao-swarm trade backtest "
                    "--strategy mean_reversion "
                    "--snapshots ./snapshots.json --json",
                    "Backtest als JSON-Output für Scripting",
                ),
            ),
            note=(
                "Snapshots-File ist eine JSON-Liste von market_state "
                "Dicts (subnets + history). Siehe docs/auto_trading.md."
            ),
        ),
        CheatGroup(
            title="Paper-Trading (kein Risk)",
            icon="📝",
            items=(
                CheatItem(
                    "tao-swarm --live --network finney trade run "
                    "--strategy ensemble:all --paper "
                    "--tick-interval-s 60 "
                    "--status-file data/runner_status.json",
                    "Adaptive Ensemble paper-tradet auf Mainnet",
                ),
                CheatItem(
                    "tao-swarm --live trade run "
                    "--strategy momentum_rotation --paper",
                    "Einzelne Strategie paper-tradet",
                ),
                CheatItem(
                    "tao-swarm trade status",
                    "Ledger-Summary: Trades, P&L, Status",
                ),
                CheatItem(
                    "tao-swarm trade learning-report --window-days 14",
                    "Per-Strategy Performance + suggested Weights",
                ),
            ),
            note=(
                "Paper-Trades schreiben nur in den lokalen SQLite-Ledger. "
                "Kein echtes Geld bewegt sich."
            ),
        ),
        CheatGroup(
            title="Keystore (Live-Trading-Vorbereitung)",
            icon="🔐",
            items=(
                CheatItem(
                    "tao-swarm keystore init "
                    "--path ~/.tao-swarm/live.keystore "
                    "--label live-finney",
                    "Verschlüsselte Keystore erstellen "
                    "(Argon2id + AES-256-GCM)",
                ),
                CheatItem(
                    "tao-swarm keystore info "
                    "--path ~/.tao-swarm/live.keystore",
                    "Metadata anzeigen ohne Passwort",
                ),
                CheatItem(
                    "tao-swarm keystore verify "
                    "--path ~/.tao-swarm/live.keystore",
                    "Passwort testen ohne Runner zu starten",
                ),
            ),
            note=(
                "WICHTIG: Verwende eine DEDIZIERTE Trading-Coldkey, "
                "nie deine Haupt-Coldkey. Loss of password = loss of "
                "keystore. Es gibt KEINE Recovery."
            ),
        ),
        CheatGroup(
            title="Live-Trading (echtes Geld)",
            icon="⚠️",
            items=(
                CheatItem(
                    "export TAO_LIVE_TRADING=1",
                    "Stage 1: Env-Var setzen",
                ),
                CheatItem(
                    "tao-swarm --live --network finney trade run "
                    "--strategy ensemble:all "
                    "--live --live-trading "
                    "--keystore-path ~/.tao-swarm/live.keystore "
                    "--reconcile-from-coldkey 5xxx "
                    "--verify-broadcasts "
                    "--max-position-tao 1.0",
                    "Live-Run mit allen 3 Stages aktiv",
                ),
                CheatItem(
                    "touch /run/tao-swarm.kill",
                    "Halt am nächsten Tick (Kill-Switch)",
                ),
                CheatItem(
                    "rm /run/tao-swarm.kill",
                    "Resume nach Halt (manuell, kein Auto-Reset)",
                ),
            ),
            note=(
                "Live-Mode signiert + broadcastet REAL. Das CLI "
                "verlangt typed 'I UNDERSTAND' confirmation bevor "
                "irgendein Extrinsic geschickt wird."
            ),
        ),
        CheatGroup(
            title="Dashboard + Files",
            icon="📊",
            items=(
                CheatItem(
                    "tao-swarm dashboard",
                    "Streamlit-UI auf http://localhost:8501",
                ),
                CheatItem(
                    "cat data/runner_status.json | jq .",
                    "Live-Runner-State als JSON (atomisch geschrieben)",
                ),
                CheatItem(
                    "sqlite3 data/trades.db "
                    "'SELECT strategy, COUNT(*), ROUND(SUM(realised_pnl_tao),4) "
                    "FROM trades GROUP BY strategy'",
                    "Trade-Ledger direkt querien",
                ),
                CheatItem(
                    "tail -f data/.kill 2>/dev/null || echo 'no halts'",
                    "Halt-Audit-Log anschauen",
                ),
            ),
        ),
        CheatGroup(
            title="Eigene Strategie",
            icon="🧠",
            items=(
                CheatItem(
                    "TAO_STRATEGY_PATHS=/path/to/strategies "
                    "tao-swarm trade run --strategy whale_follow",
                    "Eigene *_strategy.py-Datei laden",
                ),
                CheatItem(
                    "npx hygen plugin new",
                    "Plug-in-Skeleton scaffolden (Hygen)",
                ),
            ),
            note=(
                "Vollständige Doku: docs/strategy_plugins.md. Plug-ins "
                "durchlaufen den gleichen ApprovalGate wie Built-ins."
            ),
        ),
    ]


def how_to_interact_html() -> str:
    """Return the HTML for the 'Wie rede ich mit dem System' intro
    block at the top of the cheat-sheet panel."""
    return (
        '<div class="tao-banner tao-banner-info">'
        '<div>'
        '<b>Wie rede ich mit dem System?</b><br>'
        'Drei Wege — kein Chat-NLU, bewusst:'
        '<ul style="margin: 6px 0 0 1.2em; padding: 0;">'
        '<li><b>CLI</b> — der primäre Weg. Befehle unten als '
        'Cheat-Sheet, alle copy-paste-fertig.</li>'
        '<li><b>Dashboard</b> — read-only Monitor + Halt-Button '
        '(unten rechts in jeder Page).</li>'
        '<li><b>Files</b> — Kill-Switch (<code>data/.kill</code>), '
        'Status (<code>data/runner_status.json</code>), Ledger '
        '(<code>data/trades.db</code>).</li>'
        '</ul>'
        '</div></div>'
    )
