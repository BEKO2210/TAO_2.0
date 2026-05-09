"""
Paper-trade ledger — SQLite-backed P&L book.

Every trade the executor performs (paper *or* live) is recorded
here. Strategies and the daily-loss-limit guard read from it; only
the executor writes to it.

Schema is intentionally simple — one ``trades`` table — because the
trading module's job is to *act* and *audit*, not to be a full
analytics system. Higher-level reporting can read this same SQLite
file.

Realised P&L is computed as ``sum(realised_pnl_tao)`` over the
selected time window. We don't try to mark-to-market open
positions in this module; that's the strategy's responsibility
when it computes proposals.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """One row in the ledger.

    The same shape covers paper and live trades. ``paper=True``
    means no real on-chain transaction happened. ``tx_hash`` is
    only populated for live trades.
    """

    strategy: str
    action: str            # buy / sell / stake / unstake / …
    target: dict           # {netuid, hotkey, exchange, ...}
    amount_tao: float
    price_tao: float       # price the strategy assumed when proposing
    realised_pnl_tao: float
    paper: bool
    note: str = ""
    tx_hash: str | None = None
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.id,
            self.timestamp,
            self.strategy,
            self.action,
            json.dumps(self.target, sort_keys=True),
            self.amount_tao,
            self.price_tao,
            self.realised_pnl_tao,
            int(self.paper),
            self.note,
            self.tx_hash,
        )

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> TradeRecord:
        (
            tid, ts, strategy, action, target_json, amt, price,
            pnl, paper_int, note, tx_hash,
        ) = row
        return cls(
            id=tid,
            timestamp=float(ts),
            strategy=strategy,
            action=action,
            target=json.loads(target_json) if target_json else {},
            amount_tao=float(amt),
            price_tao=float(price),
            realised_pnl_tao=float(pnl),
            paper=bool(paper_int),
            note=note or "",
            tx_hash=tx_hash,
        )

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class PaperLedger:
    """SQLite-backed ledger of every recorded trade.

    Thread-safety: SQLite with default ``check_same_thread`` is
    not safe across threads. We open a fresh connection per
    operation so callers can pass the ledger between threads
    without issue. This is fine because the operations are
    short-lived and SQLite handles concurrent reads well.
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            timestamp REAL NOT NULL,
            strategy TEXT NOT NULL,
            action TEXT NOT NULL,
            target_json TEXT NOT NULL,
            amount_tao REAL NOT NULL,
            price_tao REAL NOT NULL,
            realised_pnl_tao REAL NOT NULL,
            paper INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            tx_hash TEXT
        )
    """
    _INDEX = "CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp)"

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(self._SCHEMA)
            conn.execute(self._INDEX)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        # ``isolation_level=None`` would give us autocommit; we use
        # the default and rely on the ``with`` block's commit/rollback.
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def record_trade(self, trade: TradeRecord) -> None:
        """Append a trade. Idempotent on ``trade.id``."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                trade.to_row(),
            )
            conn.commit()

    def list_trades(
        self,
        *,
        strategy: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 1000,
    ) -> list[TradeRecord]:
        """Return trades matching the filter, newest first."""
        clauses: list[str] = []
        params: list[Any] = []
        if strategy is not None:
            clauses.append("strategy = ?")
            params.append(strategy)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(float(since))
        if until is not None:
            clauses.append("timestamp < ?")
            params.append(float(until))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT id, timestamp, strategy, action, target_json, "
            f"amount_tao, price_tao, realised_pnl_tao, paper, note, "
            f"tx_hash FROM trades{where} "
            f"ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [TradeRecord.from_row(r) for r in rows]

    def realised_pnl(
        self,
        *,
        strategy: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> float:
        """Sum of ``realised_pnl_tao`` over the matching window."""
        clauses: list[str] = []
        params: list[Any] = []
        if strategy is not None:
            clauses.append("strategy = ?")
            params.append(strategy)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(float(since))
        if until is not None:
            clauses.append("timestamp < ?")
            params.append(float(until))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT COALESCE(SUM(realised_pnl_tao), 0.0) FROM trades{where}"
        with self._connect() as conn:
            (total,) = conn.execute(sql, params).fetchone()
        return float(total or 0.0)

    def total_count(self) -> int:
        with self._connect() as conn:
            (n,) = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
        return int(n)
