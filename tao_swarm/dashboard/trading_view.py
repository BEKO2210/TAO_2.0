"""
Pure data-model helpers for the dashboard's "Trading" panel.

The Streamlit page in :mod:`tao_swarm.dashboard.app` calls these
functions to assemble what to render. The functions themselves
are Streamlit-free and unit-testable.

Two sources of truth feed the panel:

- The :class:`tao_swarm.trading.ledger.PaperLedger` SQLite file —
  every paper or live trade the executor has written.
- An optional ``runner_status.json`` file written by
  :meth:`tao_swarm.trading.runner.TradingRunner.dump_status` — the
  live runner's current state (ticks, executed/refused counters,
  open positions, halted reason).

Both are read defensively: a missing file or malformed JSON returns
``None`` / an empty summary rather than raising. The panel renders
"runner not running" / "ledger empty" placeholders accordingly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LedgerSummary:
    """Aggregates the trade ledger for the dashboard's headline KPIs."""

    total_trades: int
    paper_trades: int
    live_trades: int
    failed_trades: int
    realised_pnl_tao: float
    last_trade_ts: float | None
    distinct_strategies: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "paper_trades": self.paper_trades,
            "live_trades": self.live_trades,
            "failed_trades": self.failed_trades,
            "realised_pnl_tao": self.realised_pnl_tao,
            "last_trade_ts": self.last_trade_ts,
            "distinct_strategies": list(self.distinct_strategies),
        }


def load_runner_status(path: str | Path) -> dict[str, Any] | None:
    """Load the JSON written by ``TradingRunner.dump_status(...)``.

    Returns ``None`` if the file doesn't exist or can't be parsed.
    Doesn't raise — the dashboard treats absence as "no runner is
    currently writing here".
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("failed to read runner status %s: %s", p, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("runner status %s is not a dict", p)
        return None
    return data


def summarise_ledger(ledger, *, strategy: str | None = None,
                     limit: int = 1000) -> LedgerSummary:
    """Summarise the ledger for the dashboard's KPI block.

    Args:
        ledger: Anything that quacks like
            :class:`tao_swarm.trading.ledger.PaperLedger`. Must
            expose ``list_trades(strategy, limit)`` and
            ``realised_pnl(strategy)``.
        strategy: Optional filter by strategy name.
        limit: Maximum rows to inspect for the headline aggregates.
            The ledger may have far more rows; the dashboard only
            needs a recent snapshot.
    """
    rows = list(ledger.list_trades(strategy=strategy, limit=limit))
    paper = sum(1 for r in rows if r.paper)
    live = sum(1 for r in rows if not r.paper)
    failed = sum(1 for r in rows if r.action.endswith("_failed"))
    last_ts = max((r.timestamp for r in rows), default=None)
    strategies = tuple(sorted({r.strategy for r in rows if r.strategy}))
    return LedgerSummary(
        total_trades=len(rows),
        paper_trades=paper,
        live_trades=live,
        failed_trades=failed,
        realised_pnl_tao=float(ledger.realised_pnl(strategy=strategy)),
        last_trade_ts=last_ts,
        distinct_strategies=strategies,
    )


def trades_to_table_rows(trades) -> list[dict[str, Any]]:
    """Convert TradeRecord objects to plain dicts for the dataframe.

    Strips the ledger primitives down to dashboard-friendly columns
    and collapses the JSON ``target`` to a short ``netuid`` /
    ``hotkey`` summary.
    """
    out: list[dict[str, Any]] = []
    for r in trades:
        target = r.target if isinstance(r.target, dict) else {}
        netuid = target.get("netuid")
        hotkey = target.get("hotkey") or target.get("destination") or ""
        out.append({
            "time": r.timestamp,
            "strategy": r.strategy,
            "action": r.action,
            "netuid": netuid,
            "hotkey": (hotkey[:8] + "…") if hotkey else "",
            "amount_tao": float(r.amount_tao),
            "price_tao": float(r.price_tao),
            "realised_pnl_tao": float(r.realised_pnl_tao),
            "paper": bool(r.paper),
            "tx_hash": (r.tx_hash[:10] + "…") if r.tx_hash else "",
        })
    return out


def runner_health_label(status: dict[str, Any] | None) -> tuple[str, str]:
    """Produce a (label, semantic-colour) tuple for the dashboard
    badge.

    Returns ``("offline", "secondary")`` when no status is available.
    """
    if not status:
        return "offline", "secondary"
    state = str(status.get("state", "idle"))
    if state == "halted":
        return "halted", "danger"
    if state == "error":
        return "error", "warning"
    if state == "running":
        return "running", "success"
    return state, "secondary"
