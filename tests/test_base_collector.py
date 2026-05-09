"""
Tests for ``BaseCollector`` and the mock/live convention shared by
all five collectors.
"""

from __future__ import annotations

import pytest

from src.collectors._base import BaseCollector
from src.collectors.github_repos import GitHubRepoCollector
from src.collectors.market_data import MarketDataCollector

# ---------------------------------------------------------------------------
# BaseCollector unit-level
# ---------------------------------------------------------------------------

def test_base_defaults_to_mock_offline_first():
    """The swarm is offline-first — importing a collector and calling
    it without config must never accidentally hit the network."""
    bc = BaseCollector()
    assert bc.use_mock_data is True


def test_resolve_mode_respects_use_mock_data_true():
    bc = BaseCollector({"use_mock_data": True})
    assert bc._resolve_mode(live_available=True) == "mock"
    assert bc._mock_fallback_reason is None


def test_resolve_mode_returns_live_when_requested_and_available():
    bc = BaseCollector({"use_mock_data": False})
    assert bc._resolve_mode(live_available=True) == "live"
    assert bc._mock_fallback_reason is None


def test_resolve_mode_falls_back_to_mock_when_live_unavailable():
    bc = BaseCollector({"use_mock_data": False})
    mode = bc._resolve_mode(
        live_available=False,
        reason_when_unavailable="SDK missing",
    )
    assert mode == "mock"
    assert bc._mock_fallback_reason == "SDK missing"


def test_meta_carries_source_mode_and_fetched_at():
    bc = BaseCollector({"use_mock_data": True})
    bc.SOURCE_NAME = "test_collector"
    meta = bc._meta(mode="mock")
    assert meta["source"] == "test_collector"
    assert meta["mode"] == "mock"
    assert isinstance(meta["fetched_at"], float)


def test_meta_records_fallback_reason_only_on_fallback():
    bc = BaseCollector({"use_mock_data": False})
    bc._resolve_mode(live_available=False, reason_when_unavailable="SDK missing")
    meta_fallback = bc._meta(mode="mock")
    assert meta_fallback["fallback_reason"] == "SDK missing"

    bc2 = BaseCollector({"use_mock_data": False})
    bc2._resolve_mode(live_available=True)
    meta_live = bc2._meta(mode="live")
    assert "fallback_reason" not in meta_live


# ---------------------------------------------------------------------------
# GitHubRepoCollector mock path
# ---------------------------------------------------------------------------

def test_github_default_mock_returns_fixture(tmp_path):
    db = tmp_path / "github.db"
    c = GitHubRepoCollector({"db_path": str(db)})
    assert c.use_mock_data is True
    info = c.get_repo_info("https://github.com/opentensor/bittensor")
    assert info["_meta"]["mode"] == "mock"
    assert info["_meta"]["source"] == "github_repos"
    assert info["owner"] == "opentensor"
    assert info["repo_name"] == "bittensor"
    # Mock data has plausible numbers — assert they're present, not their value
    assert isinstance(info["stars"], int)
    assert isinstance(info["forks"], int)


def test_github_invalid_url_short_circuits_before_mock(tmp_path):
    """Validation errors must surface even in mock mode."""
    db = tmp_path / "github.db"
    c = GitHubRepoCollector({"db_path": str(db)})
    info = c.get_repo_info("not-a-github-url")
    assert "error" in info


# ---------------------------------------------------------------------------
# MarketDataCollector mock path
# ---------------------------------------------------------------------------

def test_market_default_mock_returns_fixture(tmp_path):
    db = tmp_path / "market.db"
    c = MarketDataCollector({"db_path": str(db)})
    assert c.use_mock_data is True
    price = c.get_tao_price()
    assert price["_meta"]["mode"] == "mock"
    assert price["_meta"]["source"] == "market_data"
    assert "bittensor" in price
    tao = price["bittensor"]
    assert isinstance(tao["usd"], (int, float))
    assert tao["usd"] > 0


# ---------------------------------------------------------------------------
# All five collectors expose use_mock_data — pin it down
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,builder",
    [
        ("chain_readonly", lambda tmp: __import__(
            "src.collectors.chain_readonly", fromlist=["ChainReadOnlyCollector"],
        ).ChainReadOnlyCollector({"db_path": str(tmp / "c.db")})),
        ("github_repos", lambda tmp: GitHubRepoCollector({"db_path": str(tmp / "g.db")})),
        ("market_data", lambda tmp: MarketDataCollector({"db_path": str(tmp / "m.db")})),
        ("subnet_metadata", lambda tmp: __import__(
            "src.collectors.subnet_metadata", fromlist=["SubnetMetadataCollector"],
        ).SubnetMetadataCollector({"db_path": str(tmp / "s.db")})),
        ("wallet_watchonly", lambda tmp: __import__(
            "src.collectors.wallet_watchonly", fromlist=["WalletWatchOnlyCollector"],
        ).WalletWatchOnlyCollector({"db_path": str(tmp / "w.db")})),
    ],
)
def test_all_collectors_inherit_base_and_default_to_mock(tmp_path, name, builder):
    c = builder(tmp_path)
    assert isinstance(c, BaseCollector), f"{name} must inherit BaseCollector"
    assert c.use_mock_data is True, f"{name} must default to mock data"
    assert c.SOURCE_NAME != "unknown_collector", (
        f"{name} must set SOURCE_NAME on its subclass"
    )
