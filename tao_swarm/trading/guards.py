"""
Trading guards — independent, composable, append-only.

Three guards govern whether the executor is allowed to move value:

- :class:`KillSwitch` — file flag plus env var. Either tripped =
  no trades. Reason is appended to a log; the bot cannot reset
  the switch (the operator must manually delete the flag file or
  unset the env var).
- :class:`PositionCap` — hard maximum exposure per position and
  in total. Pure value-arithmetic, no I/O.
- :class:`DailyLossLimit` — kills further trading for the rest of
  the UTC day if cumulative day P&L drops to ≤ the limit.
  Reads the paper ledger; does not write.

Each guard is intentionally narrow. The :class:`~tao_swarm.trading.
executor.Executor` composes them and is the only thing that sees
all three at once.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from tao_swarm.trading.ledger import PaperLedger


# ---------------------------------------------------------------------------
# KillSwitch
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KillSwitchState:
    """A snapshot of the kill switch at a point in time."""

    tripped: bool
    reason: str | None
    source: str  # "file", "env", "none"


class KillSwitch:
    """File-flag plus env-var override. Either tripped = trades stop.

    Why two channels? An operator on a remote ssh session may not be
    able to drop a file but can ``export TAO_KILL_SWITCH=1``; an
    operator with file access (or a monitoring script) can ``touch``
    the flag. The bot cannot clear either channel — that's a manual
    operator action.

    Args:
        flag_path: Path to a file whose mere existence trips the
            switch. The file's content (if any) is read as the
            reason and recorded.
        env_var: Environment-variable name. Tripped when set to a
            truthy value (``1`` / ``true`` / ``yes`` / ``on``).
        log_path: Optional append-only audit log. Every status
            check that observes "tripped" appends a line; useful
            for post-incident review.
    """

    _TRUTHY = frozenset({"1", "true", "yes", "on"})

    def __init__(
        self,
        flag_path: Path | str,
        *,
        env_var: str = "TAO_KILL_SWITCH",
        log_path: Path | str | None = None,
    ) -> None:
        self._flag_path = Path(flag_path)
        self._env_var = env_var
        self._log_path = Path(log_path) if log_path else None

    def state(self) -> KillSwitchState:
        """Return the current state. Reads file + env on every call —
        deliberately no caching, since the operator's whole point
        is that this should respond *now*."""
        env_val = os.environ.get(self._env_var, "").strip().lower()
        if env_val in self._TRUTHY:
            return KillSwitchState(
                tripped=True,
                reason=f"environment variable {self._env_var}={env_val!r}",
                source="env",
            )
        if self._flag_path.exists():
            try:
                content = self._flag_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                content = f"(could not read flag file: {exc})"
            return KillSwitchState(
                tripped=True,
                reason=content or f"flag file present: {self._flag_path}",
                source="file",
            )
        return KillSwitchState(tripped=False, reason=None, source="none")

    def is_tripped(self) -> bool:
        """Convenience: does the executor have to refuse right now?"""
        s = self.state()
        if s.tripped:
            self._audit(s)
        return s.tripped

    def _audit(self, state: KillSwitchState) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                ts = datetime.now(timezone.utc).isoformat()
                fh.write(f"{ts}\tsource={state.source}\treason={state.reason!r}\n")
        except OSError as exc:
            logger.warning("kill-switch audit log write failed: %s", exc)

    # The bot does NOT have a method to reset / un-trip the switch.
    # Resetting is an operator action: ``rm <flag>`` or ``unset
    # <env>``. This asymmetry is deliberate.


# ---------------------------------------------------------------------------
# PositionCap
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionCap:
    """Hard maximum exposure, in TAO.

    Two-level: ``max_per_position_tao`` caps any single open
    position; ``max_total_tao`` caps the sum across all open
    positions. Both must be positive; values ≤ 0 disable trading
    by failing the can-open check.
    """

    max_per_position_tao: float
    max_total_tao: float

    def __post_init__(self) -> None:
        if self.max_per_position_tao <= 0:
            raise ValueError(
                f"max_per_position_tao must be > 0, got {self.max_per_position_tao}"
            )
        if self.max_total_tao <= 0:
            raise ValueError(
                f"max_total_tao must be > 0, got {self.max_total_tao}"
            )
        if self.max_per_position_tao > self.max_total_tao:
            raise ValueError(
                "max_per_position_tao cannot exceed max_total_tao "
                f"({self.max_per_position_tao} > {self.max_total_tao})"
            )

    def can_open(
        self, requested_tao: float, current_total_tao: float,
    ) -> tuple[bool, str]:
        """Decide whether a new position of ``requested_tao`` is allowed
        given the current total exposure.

        Returns ``(allowed, reason)``. ``reason`` is empty on allow,
        a human-readable string on refuse.
        """
        if requested_tao <= 0:
            return False, f"requested_tao must be positive, got {requested_tao}"
        if requested_tao > self.max_per_position_tao:
            return False, (
                f"per-position cap exceeded: {requested_tao} TAO requested, "
                f"cap {self.max_per_position_tao} TAO"
            )
        if current_total_tao + requested_tao > self.max_total_tao:
            return False, (
                f"total exposure cap exceeded: current {current_total_tao} + "
                f"requested {requested_tao} > cap {self.max_total_tao} TAO"
            )
        return True, ""


# ---------------------------------------------------------------------------
# DailyLossLimit
# ---------------------------------------------------------------------------

class DailyLossLimit:
    """UTC-day P&L floor.

    If cumulative P&L for the current UTC day is at or below
    ``-max_daily_loss_tao``, further trades are refused for the rest
    of the day. Resets automatically at the next UTC midnight.

    Reads the ledger; never writes. The ledger is the source of
    truth for realised P&L.
    """

    def __init__(
        self,
        max_daily_loss_tao: float,
        ledger: PaperLedger,
        *,
        clock: callable = None,  # type: ignore[type-arg]
    ) -> None:
        if max_daily_loss_tao <= 0:
            raise ValueError(
                f"max_daily_loss_tao must be > 0 (a positive limit on losses), "
                f"got {max_daily_loss_tao}"
            )
        self._limit = float(max_daily_loss_tao)
        self._ledger = ledger
        # Test-injectable wall clock so the UTC-midnight reset is
        # deterministic in tests.
        self._clock = clock or time.time

    def _utc_day_start(self) -> float:
        now = datetime.fromtimestamp(self._clock(), tz=timezone.utc)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight.timestamp()

    def daily_pnl(self) -> float:
        """The current UTC day's realised P&L, in TAO. Positive =
        gains, negative = losses."""
        return self._ledger.realised_pnl(since=self._utc_day_start())

    def is_breached(self) -> bool:
        """True iff the day's losses meet or exceed the limit."""
        pnl = self.daily_pnl()
        # We breach when losses (negative pnl) reach -limit. That is,
        # ``pnl <= -limit``.
        return pnl <= -self._limit

    def remaining_budget(self) -> float:
        """How much more loss the operator is allowed to take today
        before the limit trips, in TAO. Always >= 0."""
        pnl = self.daily_pnl()
        # remaining = limit - already_lost; already_lost = max(0, -pnl)
        already_lost = max(0.0, -pnl)
        return max(0.0, self._limit - already_lost)

    @property
    def limit_tao(self) -> float:
        return self._limit
