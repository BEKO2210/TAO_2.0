"""
Tests for ``tao_swarm.trading.reconcile`` and the runner's
cold-start reconciliation hook.

Coverage
========

aggregate_by_netuid:
- Empty input → empty dict.
- Multiple positions on the same netuid sum correctly.
- Different netuids stay separated.

BittensorChainPositionReader:
- Constructs without touching the SDK at all (lazy).
- ``read_positions`` calls ``Subtensor.get_stake_info_for_coldkey``
  with the right kwargs, returns ReconciledPosition list.
- Filters out zero-stake positions.
- Coerces Balance.tao to float.
- Skips malformed StakeInfo entries with a warning, doesn't raise.
- Empty / None coldkey rejected.
- ``close()`` closes the underlying Subtensor and is idempotent.
- Lazy real-import path uses sys.modules['bittensor'] when no
  module is injected.

TradingRunner reconciliation:
- Constructor rejects half-configured reconciliation
  (chain_reader without coldkey, or vice versa).
- Manual ``reconcile()`` populates the position book.
- Auto-reconcile fires on the first tick when configured.
- Auto-reconcile failure halts the runner with a clear reason.
- Status reports last_reconcile_ts and reconciled_total_tao.
- A second tick does NOT trigger another reconcile (one-shot).
- Reconciled positions feed the executor's current_total_tao.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from tao_swarm.trading import (
    BittensorChainPositionReader,
    DailyLossLimit,
    Executor,
    KillSwitch,
    PaperLedger,
    PositionCap,
    ReconciledPosition,
    Strategy,
    StrategyMeta,
    TradeProposal,
    TradingRunner,
    WalletMode,
    aggregate_by_netuid,
)

# ---------------------------------------------------------------------------
# Fixtures: stub SDK + simple scripted strategy
# ---------------------------------------------------------------------------

class _StubBalance:
    def __init__(self, tao: float) -> None:
        self.tao = float(tao)


def _stake_info(netuid: int, hotkey: str, tao: float, registered: bool = True):
    """Quack like bittensor.core.chain_data.stake_info.StakeInfo."""
    return SimpleNamespace(
        netuid=netuid,
        hotkey_ss58=hotkey,
        coldkey_ss58="5Coldkey",
        stake=_StubBalance(tao),
        is_registered=registered,
    )


class _StubSubtensor:
    def __init__(self, *, network: str = "finney", endpoint: str | None = None):
        self.network = network
        self.endpoint = endpoint
        self.calls: list[tuple[str, dict]] = []
        self.next_response: list[Any] = []
        self.closed = False

    def get_stake_info_for_coldkey(self, *, coldkey_ss58: str, block: int | None = None):
        self.calls.append(("get_stake_info_for_coldkey", {
            "coldkey_ss58": coldkey_ss58, "block": block,
        }))
        return list(self.next_response)

    def close(self) -> None:
        self.closed = True


def _bt_module() -> Any:
    bt = SimpleNamespace()
    bt.Subtensor = _StubSubtensor
    return bt


class _ScriptedStrategy(Strategy):
    def __init__(self, proposals: list[list[TradeProposal]] | None = None):
        self._queue = list(proposals or [])
        self._tick = 0
        self._meta = StrategyMeta(
            name="scripted", version="1.0",
            max_position_tao=10.0, max_daily_loss_tao=10.0,
            actions_used=("stake", "unstake"),
        )

    def meta(self) -> StrategyMeta:
        return self._meta

    def evaluate(self, _ms):
        if self._tick < len(self._queue):
            out = self._queue[self._tick]
        else:
            out = []
        self._tick += 1
        return out


def _proposal(action: str = "stake", netuid: int = 1, amount: float = 1.0,
              price: float = 100.0) -> TradeProposal:
    return TradeProposal(
        action=action, target={"netuid": netuid},
        amount_tao=amount, price_tao=price, confidence=0.5, reasoning="t",
    )


def _build_executor(tmp_path, *, max_per: float = 5.0, max_total: float = 20.0):
    ledger = PaperLedger(str(tmp_path / "ledger.db"))
    return Executor(
        mode=WalletMode.AUTO_TRADING,
        kill_switch=KillSwitch(flag_path=str(tmp_path / "no_kill")),
        position_cap=PositionCap(max_per_position_tao=max_per, max_total_tao=max_total),
        daily_loss_limit=DailyLossLimit(max_daily_loss_tao=10.0, ledger=ledger),
        ledger=ledger,
    ), ledger


# ---------------------------------------------------------------------------
# aggregate_by_netuid
# ---------------------------------------------------------------------------

def test_aggregate_empty():
    assert aggregate_by_netuid([]) == {}


def test_aggregate_sums_same_netuid():
    out = aggregate_by_netuid([
        ReconciledPosition(netuid=1, hotkey_ss58="A", size_tao=2.0),
        ReconciledPosition(netuid=1, hotkey_ss58="B", size_tao=3.5),
        ReconciledPosition(netuid=2, hotkey_ss58="C", size_tao=1.0),
    ])
    assert out == {1: 5.5, 2: 1.0}


def test_reconciled_position_as_dict():
    p = ReconciledPosition(netuid=4, hotkey_ss58="X", size_tao=2.5)
    d = p.as_dict()
    assert d["netuid"] == 4
    assert d["size_tao"] == 2.5
    assert d["is_registered"] is True


# ---------------------------------------------------------------------------
# BittensorChainPositionReader
# ---------------------------------------------------------------------------

def test_reader_lazy_does_not_load_sdk_until_called():
    """Constructing the reader must not import bittensor."""
    reader = BittensorChainPositionReader()
    # No subtensor created yet. (We can't easily assert that bittensor
    # itself wasn't imported because earlier tests may have done so;
    # the contract is that read_positions is the first thing that
    # touches it.)
    assert reader._subtensor is None  # type: ignore[attr-defined]


def test_reader_returns_positions(monkeypatch):
    bt = _bt_module()
    reader = BittensorChainPositionReader(bittensor_module=bt)
    sub = reader._get_subtensor(bt)  # type: ignore[attr-defined]
    sub.next_response = [
        _stake_info(netuid=1, hotkey="5Hot1", tao=2.0),
        _stake_info(netuid=2, hotkey="5Hot2", tao=4.5),
    ]
    out = reader.read_positions("5Coldkey")
    assert len(out) == 2
    assert out[0].netuid == 1
    assert out[0].size_tao == 2.0
    assert out[1].size_tao == 4.5
    assert sub.calls[0][1]["coldkey_ss58"] == "5Coldkey"


def test_reader_filters_zero_stake_rows():
    bt = _bt_module()
    reader = BittensorChainPositionReader(bittensor_module=bt)
    sub = reader._get_subtensor(bt)  # type: ignore[attr-defined]
    sub.next_response = [
        _stake_info(netuid=1, hotkey="5A", tao=0.0),
        _stake_info(netuid=2, hotkey="5B", tao=0.5),
    ]
    out = reader.read_positions("5Coldkey")
    assert len(out) == 1
    assert out[0].netuid == 2


def test_reader_skips_malformed_entries():
    bt = _bt_module()
    reader = BittensorChainPositionReader(bittensor_module=bt)
    sub = reader._get_subtensor(bt)  # type: ignore[attr-defined]
    bad = SimpleNamespace()  # no fields at all
    sub.next_response = [
        bad,
        _stake_info(netuid=1, hotkey="5A", tao=1.0),
    ]
    out = reader.read_positions("5Coldkey")
    assert len(out) == 1
    assert out[0].netuid == 1


def test_reader_rejects_empty_coldkey():
    reader = BittensorChainPositionReader(bittensor_module=_bt_module())
    with pytest.raises(ValueError):
        reader.read_positions("")


def test_reader_close_is_idempotent():
    bt = _bt_module()
    reader = BittensorChainPositionReader(bittensor_module=bt)
    sub = reader._get_subtensor(bt)  # type: ignore[attr-defined]
    reader.close()
    assert sub.closed is True
    reader.close()  # no raise


def test_reader_context_manager_closes():
    bt = _bt_module()
    with BittensorChainPositionReader(bittensor_module=bt) as reader:
        sub = reader._get_subtensor(bt)  # type: ignore[attr-defined]
        sub.next_response = []
        reader.read_positions("5Coldkey")
    assert sub.closed is True


def test_reader_lazy_imports_real_bittensor(monkeypatch):
    """When no bittensor_module is injected, the reader imports the
    real one. We replace ``bittensor`` in sys.modules so the test
    doesn't depend on the actual SDK being installed."""
    import sys
    fake_bt = _bt_module()
    monkeypatch.setitem(sys.modules, "bittensor", fake_bt)
    reader = BittensorChainPositionReader()
    out = reader.read_positions("5C")
    assert out == []


def test_reader_balance_to_tao_handles_plain_numbers():
    """If a backend returns Balance-less floats (e.g. cached JSON),
    coerce gracefully."""
    info = SimpleNamespace(
        netuid=3, hotkey_ss58="5X", coldkey_ss58="5C",
        stake=2.5, is_registered=True,
    )
    bt = _bt_module()
    reader = BittensorChainPositionReader(bittensor_module=bt)
    sub = reader._get_subtensor(bt)  # type: ignore[attr-defined]
    sub.next_response = [info]
    out = reader.read_positions("5C")
    assert len(out) == 1
    assert out[0].size_tao == 2.5


# ---------------------------------------------------------------------------
# TradingRunner — reconciliation integration
# ---------------------------------------------------------------------------

class _FakeReader:
    def __init__(self, positions: list[ReconciledPosition] | None = None,
                 raises: Exception | None = None):
        self._positions = positions or []
        self._raises = raises
        self.calls: list[str] = []

    def read_positions(self, coldkey_ss58):
        self.calls.append(coldkey_ss58)
        if self._raises is not None:
            raise self._raises
        return list(self._positions)


def test_runner_constructor_rejects_half_configured(tmp_path):
    ex, _ = _build_executor(tmp_path)
    with pytest.raises(ValueError):
        TradingRunner(
            strategy=_ScriptedStrategy(), executor=ex,
            snapshot_fn=lambda: [],
            chain_reader=_FakeReader(),  # without coldkey
        )
    with pytest.raises(ValueError):
        TradingRunner(
            strategy=_ScriptedStrategy(), executor=ex,
            snapshot_fn=lambda: [],
            reconcile_coldkey_ss58="5C",  # without reader
        )


def test_runner_manual_reconcile_populates_book(tmp_path):
    ex, _ = _build_executor(tmp_path, max_per=10.0, max_total=100.0)
    reader = _FakeReader([
        ReconciledPosition(netuid=1, hotkey_ss58="5A", size_tao=2.0),
        ReconciledPosition(netuid=1, hotkey_ss58="5B", size_tao=1.0),
        ReconciledPosition(netuid=4, hotkey_ss58="5C", size_tao=0.5),
    ])
    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [],
        chain_reader=reader,
        reconcile_coldkey_ss58="5MyCold",
    )
    out = runner.reconcile()
    assert out == {1: 3.0, 4: 0.5}
    s = runner.status()
    assert s.open_positions[1]["size"] == pytest.approx(3.0)
    assert s.open_positions[4]["size"] == pytest.approx(0.5)
    assert s.reconciled_total_tao == pytest.approx(3.5)
    assert s.last_reconcile_ts is not None
    assert reader.calls == ["5MyCold"]


def test_runner_reconcile_requires_config(tmp_path):
    ex, _ = _build_executor(tmp_path)
    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [],
    )
    with pytest.raises(RuntimeError):
        runner.reconcile()


def test_runner_auto_reconcile_on_first_tick(tmp_path):
    ex, _ = _build_executor(tmp_path)
    reader = _FakeReader([
        ReconciledPosition(netuid=2, hotkey_ss58="5X", size_tao=1.5),
    ])
    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [],
        chain_reader=reader,
        reconcile_coldkey_ss58="5C",
    )
    runner.tick()
    assert reader.calls == ["5C"]
    s = runner.status()
    assert s.open_positions[2]["size"] == pytest.approx(1.5)


def test_runner_auto_reconcile_only_runs_once(tmp_path):
    ex, _ = _build_executor(tmp_path)
    reader = _FakeReader([
        ReconciledPosition(netuid=2, hotkey_ss58="5X", size_tao=1.5),
    ])
    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [],
        chain_reader=reader,
        reconcile_coldkey_ss58="5C",
    )
    runner.tick()
    runner.tick()
    runner.tick()
    assert reader.calls == ["5C"]  # exactly one call


def test_runner_auto_reconcile_failure_halts(tmp_path):
    ex, _ = _build_executor(tmp_path)
    reader = _FakeReader(raises=ConnectionError("websocket dropped"))
    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [],
        chain_reader=reader,
        reconcile_coldkey_ss58="5C",
        max_consecutive_errors=10,
    )
    runner.tick()
    assert runner.is_halted
    s = runner.status()
    assert "reconcile" in (s.halted_reason or "")


def test_runner_auto_reconcile_off_when_disabled(tmp_path):
    ex, _ = _build_executor(tmp_path)
    reader = _FakeReader([
        ReconciledPosition(netuid=2, hotkey_ss58="5X", size_tao=1.5),
    ])
    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [],
        chain_reader=reader,
        reconcile_coldkey_ss58="5C",
        auto_reconcile=False,
    )
    runner.tick()
    # No auto-reconcile → no calls.
    assert reader.calls == []
    # Manual reconcile still works.
    runner.reconcile()
    assert reader.calls == ["5C"]


def test_reconciled_positions_feed_executor_cap(tmp_path):
    """A reconciled position counts toward current_total_tao on the
    very next proposal, so the cap arithmetic is correct after a
    cold start."""
    # tight total cap so reconciled stake fills it.
    ex, _ = _build_executor(tmp_path, max_per=3.0, max_total=3.0)
    reader = _FakeReader([
        ReconciledPosition(netuid=1, hotkey_ss58="5X", size_tao=2.5),
    ])
    strat = _ScriptedStrategy([
        # First proposal post-reconcile: amount 1.0 + total 2.5 = 3.5 > 3.0
        # → refuse.
        [_proposal(action="stake", netuid=4, amount=1.0)],
    ])
    runner = TradingRunner(
        strategy=strat, executor=ex,
        snapshot_fn=lambda: [],
        chain_reader=reader,
        reconcile_coldkey_ss58="5C",
    )
    runner.tick()
    s = runner.status()
    assert s.refused == 1
    assert s.executed == 0


def test_runner_status_includes_reconcile_fields_in_dict(tmp_path):
    ex, _ = _build_executor(tmp_path)
    reader = _FakeReader([
        ReconciledPosition(netuid=1, hotkey_ss58="5X", size_tao=1.0),
    ])
    runner = TradingRunner(
        strategy=_ScriptedStrategy(), executor=ex,
        snapshot_fn=lambda: [],
        chain_reader=reader,
        reconcile_coldkey_ss58="5C",
    )
    runner.reconcile()
    d = runner.status().as_dict()
    import json
    json.dumps(d)
    assert d["reconciled_total_tao"] == pytest.approx(1.0)
    assert d["last_reconcile_ts"] is not None


def test_reader_rejects_none_response_gracefully():
    """Some SDK paths return ``None`` instead of an empty list."""
    bt = _bt_module()
    reader = BittensorChainPositionReader(bittensor_module=bt)
    sub = reader._get_subtensor(bt)  # type: ignore[attr-defined]
    sub.next_response = None  # type: ignore[assignment]

    # Override the method directly to return None.
    sub.get_stake_info_for_coldkey = mock.MagicMock(return_value=None)
    out = reader.read_positions("5C")
    assert out == []
