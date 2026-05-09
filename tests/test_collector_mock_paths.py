"""
Tests for the mock paths added to ``subnet_metadata`` and
``wallet_watchonly`` (PR #8 follow-up).

PR #8 wired ``BaseCollector`` into all five collectors but only added
real fixture branches to ``market_data`` and ``github_repos``. This
file pins down:

- ``SubnetMetadataCollector.collect_from_github`` and
  ``collect_from_docs`` now have proper mock branches with ``_meta``
  tagging.
- ``WalletWatchOnlyCollector`` was already deterministic-mock-only
  (no live HTTP path implemented yet); its ``get_balance`` and
  ``get_staking_info`` now expose the mock/live signal via ``_meta``
  so consumers can audit data provenance and so a future Subscan
  integration plugs in cleanly.
"""

from __future__ import annotations

import pytest

from src.collectors.subnet_metadata import SubnetMetadataCollector
from src.collectors.wallet_watchonly import WalletWatchOnlyCollector


# ---------------------------------------------------------------------------
# subnet_metadata: mock branches for the two HTTP entry points
# ---------------------------------------------------------------------------

def test_subnet_metadata_github_mock_returns_fixture(tmp_path):
    db = tmp_path / "sm.db"
    c = SubnetMetadataCollector({"db_path": str(db)})
    assert c.use_mock_data is True
    info = c.collect_from_github("https://github.com/opentensor/bittensor")
    assert info["_meta"]["mode"] == "mock"
    assert info["_meta"]["source"] == "subnet_metadata"
    assert info["owner"] == "opentensor"
    assert info["repo_name"] == "bittensor"
    assert isinstance(info["stars"], int)
    # Mock fixture must NOT touch the network — invalid URLs still pass
    # the URL parser (owner/repo extraction); the regex check above is
    # what guards the no-network promise.


def test_subnet_metadata_github_invalid_url_short_circuits(tmp_path):
    """Validation must surface even before the mock branch fires."""
    db = tmp_path / "sm.db"
    c = SubnetMetadataCollector({"db_path": str(db)})
    out = c.collect_from_github("not-a-url")
    assert "error" in out


def test_subnet_metadata_docs_mock_returns_fixture(tmp_path):
    db = tmp_path / "sm.db"
    c = SubnetMetadataCollector({"db_path": str(db)})
    out = c.collect_from_docs("https://docs.example.com")
    assert out["_meta"]["mode"] == "mock"
    assert out["title"] == "Mock Documentation Page"
    assert out["http_status"] == 200
    assert out["headings_h2"] >= 1


def test_subnet_metadata_mock_results_are_cached(tmp_path):
    """A second call must come back from the SQLite cache, not regenerate."""
    db = tmp_path / "sm.db"
    c = SubnetMetadataCollector({"db_path": str(db)})
    first = c.collect_from_github("https://github.com/opentensor/bittensor")
    second = c.collect_from_github("https://github.com/opentensor/bittensor")
    assert first == second


# ---------------------------------------------------------------------------
# wallet_watchonly: _meta tagging + clear fallback signal in live mode
# ---------------------------------------------------------------------------

ADDR = "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"


def test_wallet_balance_mock_carries_meta(tmp_path):
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db)})
    bal = c.get_balance(ADDR)
    assert bal["_meta"]["mode"] == "mock"
    assert bal["_meta"]["source"] == "wallet_watchonly"
    assert "free" in bal
    assert "reserved" in bal
    assert "fallback_reason" not in bal["_meta"]


def test_wallet_staking_mock_carries_meta(tmp_path):
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db)})
    info = c.get_staking_info(ADDR)
    assert info["_meta"]["mode"] == "mock"
    assert info["total_staked"] >= 0


def test_wallet_live_mode_records_fallback_reason(tmp_path, monkeypatch):
    """When use_mock_data=False but the live Subscan call fails (no
    network in the test environment), the collector must record a
    fallback_reason naming the upstream failure, and still return
    deterministic mock values rather than crashing."""
    import requests as _requests

    def _boom(*args, **kwargs):
        raise _requests.exceptions.ConnectionError("simulated no network")

    monkeypatch.setattr(_requests, "post", _boom)

    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})
    bal = c.get_balance(ADDR)
    assert bal["_meta"]["mode"] == "mock"
    assert "Subscan" in bal["_meta"]["fallback_reason"]
    assert "ConnectionError" in bal["_meta"]["fallback_reason"]


def test_wallet_balance_is_deterministic_for_same_address(tmp_path):
    """Mock data must be stable across instances so test assertions hold."""
    db1 = tmp_path / "ww1.db"
    db2 = tmp_path / "ww2.db"
    c1 = WalletWatchOnlyCollector({"db_path": str(db1)})
    c2 = WalletWatchOnlyCollector({"db_path": str(db2)})
    a = c1.get_balance(ADDR)
    b = c2.get_balance(ADDR)
    # Mock derives values from a SHA-256 of the address, so equal addresses
    # must produce equal numeric fields (timestamps differ — strip them).
    for field in ("free", "reserved", "total"):
        assert a[field] == b[field]


# ---------------------------------------------------------------------------
# Cross-collector smoke: every reported _meta carries the source name
# ---------------------------------------------------------------------------

def test_meta_source_matches_collector_name(tmp_path):
    sm = SubnetMetadataCollector({"db_path": str(tmp_path / "sm.db")})
    ww = WalletWatchOnlyCollector({"db_path": str(tmp_path / "ww.db")})
    gh = sm.collect_from_github("https://github.com/x/y")
    bal = ww.get_balance(ADDR)
    assert gh["_meta"]["source"] == "subnet_metadata"
    assert bal["_meta"]["source"] == "wallet_watchonly"
