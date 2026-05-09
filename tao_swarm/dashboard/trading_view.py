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


# ---------------------------------------------------------------------------
# Equity-curve + outcome helpers (PR 2L)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EquityPoint:
    """One sample on the realised-P&L equity curve."""

    timestamp: float
    cumulative_pnl_tao: float


def equity_curve(trades) -> list[EquityPoint]:
    """Compute the cumulative realised-P&L curve from a sequence of
    :class:`tao_swarm.trading.ledger.TradeRecord` objects.

    Trades are sorted ascending by timestamp before accumulation so
    the result is monotonically increasing in time, even if the
    caller passes them in ledger-list order (which may be desc).

    Failed-attempt audit rows (``action`` ending in ``_failed``) are
    excluded from the realised-P&L sum because they didn't actually
    change the chain. They DO still appear in the trade table for
    forensic visibility.
    """
    items = sorted(
        (t for t in trades if not t.action.endswith("_failed")),
        key=lambda t: t.timestamp,
    )
    out: list[EquityPoint] = []
    cumulative = 0.0
    for t in items:
        cumulative += float(t.realised_pnl_tao)
        out.append(EquityPoint(
            timestamp=float(t.timestamp),
            cumulative_pnl_tao=round(cumulative, 6),
        ))
    return out


@dataclass(frozen=True)
class OutcomeDistribution:
    """Win/loss shape across a set of closed trades.

    A "closed" trade here is any row with non-zero
    ``realised_pnl_tao`` — typically the ``unstake_realised`` entries
    written by the backtester or by future close-tracking strategies.
    Open positions don't have a realised P&L yet, so they don't enter
    these statistics.
    """

    wins: int
    losses: int
    breakevens: int
    total_realised_pnl_tao: float
    largest_win_tao: float
    largest_loss_tao: float
    win_rate: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "wins": self.wins,
            "losses": self.losses,
            "breakevens": self.breakevens,
            "total_realised_pnl_tao": self.total_realised_pnl_tao,
            "largest_win_tao": self.largest_win_tao,
            "largest_loss_tao": self.largest_loss_tao,
            "win_rate": self.win_rate,
        }


def outcome_distribution(trades) -> OutcomeDistribution:
    """Compute win/loss statistics over closed trades.

    Excludes failed-attempt audit rows (``*_failed``) and opens
    (rows with realised P&L of exactly 0) — only realised closes
    count toward win-rate arithmetic.
    """
    pnls: list[float] = []
    for t in trades:
        if t.action.endswith("_failed"):
            continue
        pnl = float(t.realised_pnl_tao)
        if pnl == 0.0:
            continue
        pnls.append(pnl)
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    breakevens = sum(
        1 for t in trades
        if not t.action.endswith("_failed")
        and float(t.realised_pnl_tao) == 0.0
        and t.action.endswith("_realised")
    )
    total = sum(pnls)
    win_rate = (wins / len(pnls)) if pnls else 0.0
    return OutcomeDistribution(
        wins=wins,
        losses=losses,
        breakevens=breakevens,
        total_realised_pnl_tao=round(total, 6),
        largest_win_tao=round(max(pnls), 6) if pnls else 0.0,
        largest_loss_tao=round(min(pnls), 6) if pnls else 0.0,
        win_rate=round(win_rate, 4),
    )


# ---------------------------------------------------------------------------
# Halt-runner control (kill-switch convenience)
# ---------------------------------------------------------------------------

def halt_runner_via_killswitch(path: str | Path, reason: str = "dashboard halt") -> None:
    """Touch (or rewrite) the kill-switch file the runner watches.

    The runner refuses to act once this file exists. The dashboard
    button is the only "control" surface — the dashboard otherwise
    stays read-only. Halting is intentionally one-way: the operator
    has to manually delete the file to resume, mirroring the
    ``KillSwitch`` no-reset rule.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        f"halted via dashboard at {Path(__file__).name}: {reason}\n"
    )
    # Append rather than overwrite so multiple halts stack as audit log.
    with p.open("a", encoding="utf-8") as fh:
        fh.write(payload)
