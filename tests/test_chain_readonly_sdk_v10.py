"""
Tests for the SDK v10 uptake in ``ChainReadOnlyCollector``:

- Real ``metagraph(lite=True)`` with stubbed SDK
- ``SubtensorApi`` preference over legacy ``bt.subtensor``
- Fallback endpoints threaded through the constructor
- Real economic parameters (``recycle``, ``get_subnet_burn_cost``,
  ``get_subnet_hyperparameters``) in ``get_subnet_info`` live mode
- Source-level guard: this collector never imports / calls write
  methods (``set_weights``, ``add_stake``, ``transfer``, …)
- Lifecycle: ``_with_subtensor`` opens, yields, closes
"""

from __future__ import annotations

import re
import types
from pathlib import Path
from typing import Any

import pytest

import src.collectors.chain_readonly as chain_module
from src.collectors.chain_readonly import (
    _DEFAULT_FALLBACK_ENDPOINTS,
    _WRITE_METHODS_DENYLIST,
    ChainReadOnlyCollector,
)

# ---------------------------------------------------------------------------
# Helpers: stubbed bittensor SDKs (modern v10 + legacy)
# ---------------------------------------------------------------------------

class _MetagraphStub:
    """Minimal stand-in for ``bt.Metagraph(lite=True)`` — exposes the
    attributes ``_live_metagraph`` reads, with sane plain-list values."""

    def __init__(self, netuid: int) -> None:
        self.netuid = netuid
        self.block = 5_000_000 + netuid
        # Three neurons: two miners, one validator.
        self.uids = [0, 1, 2]
        self.S = [12.5, 7.0, 100.0]
        self.E = [0.001, 0.0008, 0.005]
        self.T = [0.6, 0.55, 0.95]
        self.R = [0.1, 0.08, 0.5]
        self.C = [0.7, 0.65, 0.99]
        self.I = [0.001, 0.0009, 0.004]
        self.validator_permit = [False, False, True]
        self.last_update = [4_999_900, 4_999_950, 4_999_990]
        self.active = [True, True, True]


class _SubtensorApiStub:
    """v10-style SubtensorApi: exposes ``metagraph``, ``get_all_subnets_netuid``,
    ``recycle``, ``get_subnet_burn_cost``, ``get_subnet_hyperparameters``,
    plus a ``close`` we count to verify lifecycle."""

    last_init_kwargs: dict | None = None
    close_count = 0

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_init_kwargs = kwargs

    # Read methods (the only legitimate surface)
    def get_all_subnets_netuid(self) -> list[int]:
        return [1, 2, 12, 99]

    def metagraph(self, netuid: int, lite: bool = True) -> _MetagraphStub:
        return _MetagraphStub(netuid)

    def recycle(self, netuid: int) -> float:
        return 0.5 + netuid * 0.01

    def get_subnet_burn_cost(self) -> float:
        return 100.0

    def get_subnet_hyperparameters(self, netuid: int):
        return types.SimpleNamespace(
            tempo=360, immunity_period=4096, kappa=0.5, rho=10,
            commit_reveal_weights_enabled=False,
        )

    def close(self) -> None:
        type(self).close_count += 1


class _LegacySubtensorStub:
    """Pre-v10 ``bt.subtensor`` — only ``get_subnets``, no SubtensorApi
    surface, no ``close``."""

    def __init__(self, network: str) -> None:
        self.network = network

    def get_subnets(self) -> list[int]:
        return [3, 4]


def _make_v10_bt():
    fake = types.ModuleType("bittensor")
    fake.SubtensorApi = _SubtensorApiStub
    return fake


def _make_legacy_bt():
    fake = types.ModuleType("bittensor")
    fake.subtensor = _LegacySubtensorStub
    return fake


# ---------------------------------------------------------------------------
# SubtensorApi preference (v10 path)
# ---------------------------------------------------------------------------

def test_sdk_v10_subtensor_api_is_preferred_when_available(tmp_path, monkeypatch):
    fake_bt = _make_v10_bt()
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)
    _SubtensorApiStub.last_init_kwargs = None
    _SubtensorApiStub.close_count = 0

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    subnets = c.get_subnet_list()
    netuids = sorted(s["netuid"] for s in subnets)
    assert netuids == [1, 2, 12, 99]

    init = _SubtensorApiStub.last_init_kwargs or {}
    assert init.get("network") == "finney"
    # fallback_endpoints must be threaded through from the default list
    assert init.get("fallback_endpoints") == list(_DEFAULT_FALLBACK_ENDPOINTS)


def test_sdk_v10_close_called_on_with_subtensor_exit(tmp_path, monkeypatch):
    fake_bt = _make_v10_bt()
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)
    _SubtensorApiStub.close_count = 0

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    c.get_subnet_list()  # one open + close cycle
    assert _SubtensorApiStub.close_count >= 1


def test_legacy_bt_subtensor_still_works_when_api_missing(tmp_path, monkeypatch):
    fake_bt = _make_legacy_bt()
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)
    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    subnets = c.get_subnet_list()
    assert sorted(s["netuid"] for s in subnets) == [3, 4]


def test_custom_fallback_endpoints_threaded_through(tmp_path, monkeypatch):
    fake_bt = _make_v10_bt()
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)
    _SubtensorApiStub.last_init_kwargs = None

    db = tmp_path / "chain.db"
    custom = ["wss://my-private-node:443", "wss://backup:443"]
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
        "fallback_endpoints": custom,
    })
    c.get_subnet_list()
    assert _SubtensorApiStub.last_init_kwargs.get("fallback_endpoints") == custom


# ---------------------------------------------------------------------------
# Real metagraph(lite=True)
# ---------------------------------------------------------------------------

def test_live_metagraph_returns_real_neurons(tmp_path, monkeypatch):
    fake_bt = _make_v10_bt()
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    mg = c.get_metagraph(netuid=12)
    assert mg["netuid"] == 12
    assert mg["num_neurons"] == 3
    assert mg["validator_count"] == 1
    assert mg["miner_count"] == 2
    assert mg["_meta"]["mode"] == "live"
    assert mg["_meta"]["network"] == "finney"
    # Neurons preserve key fields from the SDK metagraph
    val = next(n for n in mg["neurons"] if n["validator_permit"])
    assert val["uid"] == 2
    assert val["stake"] == 100.0
    assert val["consensus"] == 0.99


def test_live_metagraph_falls_back_on_sdk_error(tmp_path, monkeypatch):
    """If the SDK call blows up (incompat version, network), the
    collector must degrade to the existing mock branch — never
    surface a partial / corrupt metagraph dict."""
    class _BrokenApi(_SubtensorApiStub):
        def metagraph(self, netuid, lite=True):
            raise RuntimeError("simulated chain timeout")

    fake_bt = types.ModuleType("bittensor")
    fake_bt.SubtensorApi = _BrokenApi
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    mg = c.get_metagraph(netuid=12)
    # Falls back to the synthetic branch — has neurons but no _meta
    # tagging it as live.
    assert "neurons" in mg
    assert mg.get("_meta", {}).get("mode") != "live"


# ---------------------------------------------------------------------------
# get_subnet_info enriched with real economics
# ---------------------------------------------------------------------------

def test_subnet_info_pulls_real_recycle_and_burn_cost_in_live_mode(tmp_path, monkeypatch):
    fake_bt = _make_v10_bt()
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    info = c.get_subnet_info(netuid=12)
    # real numbers from the stub, NOT the synthetic 0.1 * netuid path
    assert info["recycle_register"] == pytest.approx(0.62)
    assert info["burn_cost"] == 100.0
    assert "hyperparameters" in info
    assert info["hyperparameters"]["tempo"] == 360
    assert info["_meta"]["mode"] == "live"


def test_subnet_info_keeps_synthetic_path_in_mock_mode(tmp_path):
    # Default = mock; no SDK touched, synthetic 0.1 * netuid result.
    # Use netuid=1 — present in the _MOCK_SUBNETS fixture.
    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({"db_path": str(db)})
    info = c.get_subnet_info(netuid=1)
    assert "error" not in info
    assert info["recycle_register"] == pytest.approx(0.1)  # 0.1 * 1
    assert info["burn_cost"] == pytest.approx(0.05)        # 0.05 * 1
    assert info.get("_meta", {}).get("mode") == "mock"


# ---------------------------------------------------------------------------
# Source-level guard: never call write methods
# ---------------------------------------------------------------------------

def test_collector_source_does_not_call_any_write_method():
    """Belt-and-braces source scan: ``chain_readonly.py`` must contain
    none of the SDK's write-side method names. If the SDK adds a new
    write method we forgot, add it to ``_WRITE_METHODS_DENYLIST``."""
    src_path = Path(chain_module.__file__)
    source = src_path.read_text()

    # We allow the names to *appear inside the denylist constant itself*,
    # so strip that block out before scanning.
    denylist_block = re.search(
        r"_WRITE_METHODS_DENYLIST.*?\}", source, re.DOTALL,
    )
    scannable = source
    if denylist_block:
        scannable = source.replace(denylist_block.group(0), "")

    for method in _WRITE_METHODS_DENYLIST:
        # Match `.method_name(` — i.e. an actual call, not a substring match.
        pattern = re.compile(rf"\.{re.escape(method)}\s*\(")
        assert not pattern.search(scannable), (
            f"chain_readonly.py contains a call to write method "
            f"`{method}` — this collector must stay read-only."
        )


def test_denylist_includes_all_known_write_extrinsics():
    """Sanity: the denylist must cover the bittensor v10 write surface
    we know about. If you add a new write op to the SDK, update this
    list and the source guard above."""
    must_include = {
        "set_weights", "add_stake", "unstake", "transfer", "register",
        "burned_register", "commit_weights", "reveal_weights",
        "add_proxy", "serve_axon",
    }
    missing = must_include - _WRITE_METHODS_DENYLIST
    assert not missing, f"_WRITE_METHODS_DENYLIST missing: {missing}"
