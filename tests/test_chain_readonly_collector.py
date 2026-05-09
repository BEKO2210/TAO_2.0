"""
Tests for ``ChainReadOnlyCollector``.

Covers:

* The default offline-first mock path.
* The bittensor-SDK live path, with the SDK monkey-patched (so the
  real test suite never connects to a chain).
* The graceful fallback when ``bittensor`` isn't installed.
* The single network-marked test (``@pytest.mark.network``) that
  hits the actual ``finney`` mainnet — skipped by default; opt in
  via ``pytest -m network``.
"""

from __future__ import annotations

import types

import pytest

import tao_swarm.collectors.chain_readonly as chain_module
from tao_swarm.collectors.chain_readonly import ChainReadOnlyCollector

# ---------------------------------------------------------------------------
# Mock-mode (default) — runs offline, hits no network
# ---------------------------------------------------------------------------

def test_default_uses_mock_and_returns_subnets(tmp_path):
    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({"db_path": str(db)})
    assert c.use_mock_data is True
    subnets = c.get_subnet_list()
    assert isinstance(subnets, list)
    assert len(subnets) >= 1
    assert {"netuid"} <= set(subnets[0].keys())


def test_explicit_use_mock_data_true_uses_mock(tmp_path, monkeypatch):
    """If a sneaky import attempts to load bittensor, monkey-patching
    it to None proves we never even tried to use it in mock mode."""
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: None)
    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({"db_path": str(db), "use_mock_data": True})
    subnets = c.get_subnet_list()
    assert subnets


def test_network_mock_implies_use_mock_data(tmp_path):
    """Backward compat: passing network='mock' (the original API) must
    still force mock mode even if use_mock_data wasn't set."""
    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({"db_path": str(db), "network": "mock"})
    assert c.use_mock_data is True


# ---------------------------------------------------------------------------
# Live-mode with stubbed bittensor SDK
# ---------------------------------------------------------------------------

def _make_fake_bt(netuids: list[int]):
    """Build a stand-in bittensor module exposing the minimal surface."""
    fake_bt = types.ModuleType("bittensor")

    class FakeSubtensor:
        def __init__(self, network: str) -> None:
            self.network = network

        def get_subnets(self):
            return netuids

    fake_bt.subtensor = FakeSubtensor  # type: ignore[attr-defined]
    return fake_bt


def test_live_path_uses_bittensor_get_subnets(tmp_path, monkeypatch):
    fake_bt = _make_fake_bt([1, 2, 5, 12, 99])
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    subnets = c.get_subnet_list()
    netuids = [s["netuid"] for s in subnets]
    assert netuids == [1, 2, 5, 12, 99]


def test_live_path_falls_back_to_get_all_subnet_netuids(tmp_path, monkeypatch):
    """Older SDK versions exposed get_all_subnet_netuids; newer ones
    use get_subnets. The collector accepts either — assert the
    fallback fires when only the older one is available."""
    fake_bt = types.ModuleType("bittensor")

    class OldSubtensor:
        def __init__(self, network: str) -> None:
            self.network = network

        def get_all_subnet_netuids(self):
            return [7, 8]

    fake_bt.subtensor = OldSubtensor  # type: ignore[attr-defined]
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    netuids = [s["netuid"] for s in c.get_subnet_list()]
    assert netuids == [7, 8]


def test_live_path_raises_on_incompatible_sdk(tmp_path, monkeypatch):
    fake_bt = types.ModuleType("bittensor")

    class IncompatibleSubtensor:
        def __init__(self, network: str) -> None:
            pass

    fake_bt.subtensor = IncompatibleSubtensor  # type: ignore[attr-defined]
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    with pytest.raises(RuntimeError, match="incompatible SDK version"):
        c.get_subnet_list()


def test_live_path_falls_back_to_mock_when_sdk_missing(tmp_path, monkeypatch):
    """When use_mock_data=False but bittensor isn't installed, the
    collector must fall back to mock data and record why."""
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: None)

    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
    })
    subnets = c.get_subnet_list()
    assert subnets  # mock fixture
    assert c._mock_fallback_reason is not None
    assert "bittensor" in c._mock_fallback_reason.lower()


# ---------------------------------------------------------------------------
# Cache isolation: mock and live runs must never share a cache row
# ---------------------------------------------------------------------------

def test_db_path_namespaced_by_network(tmp_path):
    db = tmp_path / "chain_cache.db"
    mock_c = ChainReadOnlyCollector({"db_path": str(db), "network": "mock"})
    finney_c = ChainReadOnlyCollector({"db_path": str(db), "network": "finney", "use_mock_data": False})
    assert mock_c.db_path != finney_c.db_path
    assert mock_c.db_path.endswith(".mock.db")
    assert finney_c.db_path.endswith(".finney.db")


def test_pre_namespaced_path_is_not_double_namespaced(tmp_path):
    """If the caller already passed a path containing the network, don't
    append it again — keeps user-controlled paths predictable."""
    pre = str(tmp_path / "chain_cache.finney.db")
    c = ChainReadOnlyCollector({"db_path": pre, "network": "finney", "use_mock_data": False})
    assert c.db_path == pre


def test_mock_run_does_not_poison_live_cache(tmp_path, monkeypatch):
    """The original bug: a --mock run wrote subnets under (netuid=-1),
    a subsequent --live run read the same row and got mock data back.
    With per-network namespacing, the two caches are separate files
    and cannot collide."""
    import types
    fake_bt = types.ModuleType("bittensor")

    class FakeSubtensor:
        def __init__(self, network: str) -> None:
            pass
        def get_subnets(self):
            return [42, 99]

    fake_bt.subtensor = FakeSubtensor  # type: ignore[attr-defined]
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: fake_bt)

    db = tmp_path / "chain_cache.db"

    # 1) Mock run populates its own cache.
    mock_c = ChainReadOnlyCollector({"db_path": str(db), "network": "mock"})
    mock_subs = mock_c.get_subnet_list()
    mock_netuids = {s["netuid"] for s in mock_subs}

    # 2) Live run reads from a different cache file and gets the
    #    stubbed live data, NOT the mock data we just wrote.
    live_c = ChainReadOnlyCollector({
        "db_path": str(db),
        "network": "finney",
        "use_mock_data": False,
    })
    live_subs = live_c.get_subnet_list()
    live_netuids = {s["netuid"] for s in live_subs}

    assert live_netuids == {42, 99}
    assert live_netuids != mock_netuids

    # 3) Mock run again sees the original mock data (its cache wasn't
    #    overwritten by the live run).
    mock_c2 = ChainReadOnlyCollector({"db_path": str(db), "network": "mock"})
    mock_subs2 = mock_c2.get_subnet_list()
    assert {s["netuid"] for s in mock_subs2} == mock_netuids


# ---------------------------------------------------------------------------
# Live integration test against finney mainnet (opt-in)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_finney_live_returns_real_subnets(tmp_path):
    """Network test: actually connect to finney and read a subnet list.

    Skipped by default. Opt in with ``pytest -m network``. Will fail
    if bittensor isn't installed or the network is unreachable.
    """
    pytest.importorskip("bittensor", reason="bittensor SDK not installed")
    db = tmp_path / "chain.db"
    c = ChainReadOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "network": "finney",
        "timeout": 30,
    })
    subnets = c.get_subnet_list()
    assert len(subnets) > 0
    assert all("netuid" in s for s in subnets)
    assert c._mock_fallback_reason is None
