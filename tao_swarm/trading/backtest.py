"""
Deterministic backtester for trading strategies.

Feed a sequence of historical ``market_state`` snapshots into a
strategy, route each emitted proposal through a paper executor,
and compute summary statistics over the resulting paper-ledger.

The backtester is deliberately simple: it does not simulate
slippage, partial fills, mempool ordering, or off-chain venues.
It exists so the operator can answer one question — "would this
strategy have been profitable on past data?" — before risking real
funds. Anything more sophisticated lands as a separate harness.

Usage::

    bt = Backtester(strategy, paper_db_path=":memory:")
    result = bt.run(snapshots, prices_after_each_step)
    print(result.total_pnl, result.num_trades, result.max_drawdown)

The caller supplies ``prices_after_each_step``: for each snapshot
the strategy evaluates, the realised mark-to-market price the
backtester should record. This lets the harness compute realised
P&L without a market-impact model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from tao_swarm.trading.executor import Executor
from tao_swarm.trading.guards import (
    DailyLossLimit,
    KillSwitch,
    PositionCap,
)
from tao_swarm.trading.ledger import PaperLedger, TradeRecord
from tao_swarm.trading.modes import WalletMode
from tao_swarm.trading.strategy_base import Strategy

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Summary of a backtest run."""

    strategy_name: str
    num_steps: int
    num_proposals: int
    num_executed: int
    num_refused: int
    total_pnl_tao: float
    win_rate: float          # fraction of closed trades with positive P&L
    max_drawdown_tao: float  # max peak-to-trough equity drop, positive
    sharpe_ratio: float      # pseudo-sharpe of per-step P&L deltas
    refusals: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "num_steps": self.num_steps,
            "num_proposals": self.num_proposals,
            "num_executed": self.num_executed,
            "num_refused": self.num_refused,
            "total_pnl_tao": self.total_pnl_tao,
            "win_rate": self.win_rate,
            "max_drawdown_tao": self.max_drawdown_tao,
            "sharpe_ratio": self.sharpe_ratio,
            "refusals": list(self.refusals),
        }


class Backtester:
    """Run a strategy against historical snapshots, record paper trades."""

    def __init__(
        self,
        strategy: Strategy,
        *,
        paper_db_path: str = ":memory:",
        slot_size_tao: float = 1.0,
        max_total_tao: float = 1_000.0,
        max_daily_loss_tao: float = 1_000.0,
    ) -> None:
        if paper_db_path == ":memory:":
            # SQLite in-memory is per-connection; the ledger opens
            # one connection per call, so ":memory:" wouldn't share
            # state. Use a tmp file path instead — the file is
            # cleaned up by the OS / caller.
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                prefix="bt_", suffix=".db", delete=False,
            )
            tmp.close()
            paper_db_path = tmp.name
        self._strategy = strategy
        self._ledger = PaperLedger(paper_db_path)
        # Permissive caps because the backtester is paper-only and
        # we want the strategy's own logic to be the binding
        # constraint, not surrounding guards. The operator's
        # production caps are enforced in production by the live
        # executor wired up in PR 2E.
        meta = strategy.meta()
        per_position = max(meta.max_position_tao, slot_size_tao)
        self._executor = Executor(
            mode=WalletMode.AUTO_TRADING,
            kill_switch=KillSwitch(
                # Use a path that never exists so the kill switch
                # can't accidentally trip during a backtest run.
                flag_path="/tmp/.tao_bt_no_such_file_ever",
            ),
            position_cap=PositionCap(
                max_per_position_tao=per_position,
                max_total_tao=max(max_total_tao, per_position),
            ),
            daily_loss_limit=DailyLossLimit(
                max_daily_loss_tao=max(
                    max_daily_loss_tao, meta.max_daily_loss_tao,
                ) * 1000,  # backtester intentionally permissive
                ledger=self._ledger,
            ),
            ledger=self._ledger,
        )

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def run(
        self,
        snapshots: list[dict[str, Any]],
        prices_after_step: list[dict[int, float]] | None = None,
    ) -> BacktestResult:
        """Iterate snapshots, route proposals, compute summary.

        Args:
            snapshots: Time-ordered ``market_state`` dicts. Each is
                fed to the strategy in order.
            prices_after_step: Optional per-step ``{netuid: price}``
                dict used to mark open positions to market and
                compute realised P&L when a position closes. If
                ``None`` the backtester records 0 P&L per trade
                (useful for verifying that a strategy actually
                emits proposals; not useful for evaluating
                profitability).
        """
        meta = self._strategy.meta()
        positions: dict[int, dict[str, float]] = {}
        equity_curve: list[float] = [0.0]
        per_step_pnl: list[float] = []
        num_proposals = 0
        num_executed = 0
        num_refused = 0
        refusals: list[str] = []

        for step, snapshot in enumerate(snapshots):
            proposals = self._strategy.evaluate(snapshot)
            num_proposals += len(proposals)
            current_total = sum(p["size"] for p in positions.values())

            for prop in proposals:
                result = self._executor.execute(
                    prop,
                    paper=True,
                    current_total_tao=current_total,
                    strategy_name=meta.name,
                )
                if result.is_ok():
                    num_executed += 1
                    self._apply_to_positions(
                        positions, prop, snapshot, prices_after_step, step,
                    )
                    current_total = sum(p["size"] for p in positions.values())
                else:
                    num_refused += 1
                    if result.reason and result.reason not in refusals:
                        refusals.append(result.reason)

            # Mark-to-market at end of step using prices_after_step
            mtm = self._mark_to_market(
                positions, prices_after_step, step,
            )
            equity_curve.append(mtm)
            per_step_pnl.append(equity_curve[-1] - equity_curve[-2])

        total_pnl = self._ledger.realised_pnl(strategy=meta.name) + equity_curve[-1]
        return BacktestResult(
            strategy_name=meta.name,
            num_steps=len(snapshots),
            num_proposals=num_proposals,
            num_executed=num_executed,
            num_refused=num_refused,
            total_pnl_tao=round(total_pnl, 6),
            win_rate=self._win_rate(meta.name),
            max_drawdown_tao=self._max_drawdown(equity_curve),
            sharpe_ratio=self._sharpe(per_step_pnl),
            refusals=refusals,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_to_positions(
        self,
        positions: dict[int, dict[str, float]],
        prop: Any,
        snapshot: dict[str, Any],
        prices_after_step: list[dict[int, float]] | None,
        step: int,
    ) -> None:
        """Update the in-memory position book based on a paper-trade
        proposal. ``stake`` opens / increases; ``unstake`` reduces /
        closes."""
        netuid = int(prop.target.get("netuid", -1))
        if netuid < 0:
            return
        pos = positions.setdefault(
            netuid, {"size": 0.0, "entry": prop.price_tao},
        )
        if prop.action == "stake":
            # Average entry price (size-weighted).
            new_size = pos["size"] + prop.amount_tao
            pos["entry"] = (
                (pos["entry"] * pos["size"] + prop.price_tao * prop.amount_tao)
                / new_size if new_size else prop.price_tao
            )
            pos["size"] = new_size
        elif prop.action == "unstake":
            close_size = min(prop.amount_tao, pos["size"])
            if close_size <= 0:
                return
            # Realised P&L on the closed slice = (exit - entry) * size
            exit_price = prop.price_tao
            realised = (exit_price - pos["entry"]) * close_size
            self._ledger.record_trade(TradeRecord(
                strategy=self._strategy.meta().name,
                action="unstake_realised",
                target={"netuid": netuid},
                amount_tao=close_size,
                price_tao=exit_price,
                realised_pnl_tao=realised,
                paper=True,
                note=f"backtest step {step}",
            ))
            pos["size"] -= close_size
            if pos["size"] <= 1e-9:
                positions.pop(netuid, None)

    def _mark_to_market(
        self,
        positions: dict[int, dict[str, float]],
        prices_after_step: list[dict[int, float]] | None,
        step: int,
    ) -> float:
        """Unrealised P&L of currently-open positions."""
        if not prices_after_step or step >= len(prices_after_step):
            return 0.0
        prices = prices_after_step[step] or {}
        total = 0.0
        for netuid, pos in positions.items():
            mark = prices.get(netuid)
            if mark is None:
                continue
            total += (mark - pos["entry"]) * pos["size"]
        return total

    def _win_rate(self, strategy_name: str) -> float:
        closes = [
            t for t in self._ledger.list_trades(strategy=strategy_name, limit=10000)
            if t.action == "unstake_realised"
        ]
        if not closes:
            return 0.0
        wins = sum(1 for t in closes if t.realised_pnl_tao > 0)
        return wins / len(closes)

    @staticmethod
    def _max_drawdown(equity: list[float]) -> float:
        """Worst peak-to-trough drop in the equity curve. Positive
        number; 0 if equity never declined."""
        if not equity:
            return 0.0
        peak = equity[0]
        worst = 0.0
        for v in equity[1:]:
            if v > peak:
                peak = v
            drop = peak - v
            if drop > worst:
                worst = drop
        return round(worst, 6)

    @staticmethod
    def _sharpe(per_step_pnl: list[float]) -> float:
        """Pseudo-Sharpe: mean / stddev of per-step P&L. No
        annualisation — the backtester doesn't know the
        snapshot interval. Returns 0 on insufficient data."""
        n = len(per_step_pnl)
        if n < 2:
            return 0.0
        mean = sum(per_step_pnl) / n
        var = sum((x - mean) ** 2 for x in per_step_pnl) / (n - 1)
        if var <= 0:
            return 0.0
        return round(mean / (var ** 0.5), 4)
