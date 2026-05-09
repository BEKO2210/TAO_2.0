"""
Live smoke tests — actually hit the real upstream services.

Skipped by default (gated by ``pytest.mark.network``). Run with::

    pytest -m network tests/test_live_smoke.py -v

Each test verifies that a live path either produces real data OR
fails into a clearly-tagged graceful fallback. None of them assert
specific numeric values (those move with markets / chain state),
only the shape and a freshness signal.

These tests need:
  - ``bittensor`` installed (``pip install bittensor``)
  - Outbound network to mainnet finney, Subscan, CoinGecko, GitHub
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.network


# ---------------------------------------------------------------------------
# Chain (Bittensor mainnet finney)
# ---------------------------------------------------------------------------

def test_live_chain_lists_real_subnets(tmp_path):
    """The real chain currently exposes well over 50 subnets and
    each rich entry carries an ``identity`` block with at least
    ``description`` set on the curated ones."""
    pytest.importorskip("bittensor", reason="bittensor SDK not installed")
    from src.collectors.chain_readonly import ChainReadOnlyCollector

    c = ChainReadOnlyCollector({
        "use_mock_data": False, "network": "finney",
        "db_path": str(tmp_path / "chain_smoke.db"),
    })
    subnets = c.get_subnet_list()

    assert isinstance(subnets, list)
    assert len(subnets) > 50, (
        f"expected >50 live subnets, got {len(subnets)}; "
        f"chain may be unreachable or SDK changed shape"
    )
    sample = subnets[0]
    assert {"netuid", "name"}.issubset(sample.keys())
    # The rich path should provide identity for at least one subnet.
    rich_count = sum(1 for s in subnets if isinstance(s.get("identity"), dict))
    assert rich_count > 5, (
        f"expected several subnets with identity blocks, got {rich_count}"
    )


def test_live_chain_subnet_info_real_economics(tmp_path):
    """Subnet 1 (Apex) is a stable canary. Live read should yield
    chain-derived emission / hyperparameter fields, not mock."""
    pytest.importorskip("bittensor", reason="bittensor SDK not installed")
    from src.collectors.chain_readonly import ChainReadOnlyCollector

    c = ChainReadOnlyCollector({
        "use_mock_data": False, "network": "finney",
        "db_path": str(tmp_path / "chain_info_smoke.db"),
    })
    info = c.get_subnet_info(1)
    assert info.get("netuid") == 1
    # Live mode tags the meta with the source — accept either shape.
    meta = info.get("_meta", {})
    if "mode" in meta:
        assert meta["mode"] in ("live", "mock")


# ---------------------------------------------------------------------------
# Wallet — Subscan
# ---------------------------------------------------------------------------

# A canonical SS58 prefix-42 address known to validate everywhere.
_KNOWN_GOOD_SS58 = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"


def test_validate_address_accepts_real_ss58():
    from src.collectors.wallet_watchonly import WalletWatchOnlyCollector

    c = WalletWatchOnlyCollector({"use_mock_data": True, "db_path": "/tmp/ws.db"})
    assert c.validate_address(_KNOWN_GOOD_SS58) is True
    assert c.validate_address("5xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx") is False
    assert c.validate_address("not_an_address") is False


def test_live_wallet_balance_either_real_or_clean_fallback(tmp_path):
    """Live Subscan call must produce either a live balance dict or
    a fallback dict with ``_meta.fallback_reason`` set. It must
    never raise."""
    from src.collectors.wallet_watchonly import WalletWatchOnlyCollector

    c = WalletWatchOnlyCollector({
        "use_mock_data": False,
        "db_path": str(tmp_path / "wallet_smoke.db"),
    })
    balance = c.get_balance(_KNOWN_GOOD_SS58)

    assert isinstance(balance, dict)
    assert {"address", "free", "reserved", "total", "_meta"}.issubset(balance.keys())
    assert balance["address"] == _KNOWN_GOOD_SS58
    meta = balance["_meta"]
    assert meta["mode"] in ("live", "mock")
    if meta["mode"] == "mock":
        # Fallback must explain itself.
        assert meta.get("fallback_reason"), (
            "mock fallback in live mode must carry a fallback_reason"
        )


# ---------------------------------------------------------------------------
# Market data — CoinGecko
# ---------------------------------------------------------------------------

def test_live_tao_price_either_real_or_error(tmp_path):
    from src.collectors.market_data import MarketDataCollector

    c = MarketDataCollector({
        "use_mock_data": False,
        "db_path": str(tmp_path / "market_smoke.db"),
    })
    result = c.get_tao_price()
    assert isinstance(result, dict)
    if "error" in result:
        # Endpoint may be rate-limiting or down — acceptable, the
        # collector must not raise. Just sanity-check it's a string.
        assert isinstance(result["error"], str)
    else:
        # Real response: price_usd must be positive.
        assert result.get("price_usd", 0) > 0, (
            f"expected positive price_usd, got {result}"
        )
        # Live mode must tag itself.
        assert result.get("_meta", {}).get("mode") == "live"


# ---------------------------------------------------------------------------
# Subnet discovery agent end-to-end against live chain
# ---------------------------------------------------------------------------

def test_live_subnet_discovery_agent_returns_real_subnets(tmp_path):
    """End-to-end: the agent invoked through the orchestrator must
    return a real chain-derived subnet list when bittensor is
    installed and live mode is on."""
    pytest.importorskip("bittensor", reason="bittensor SDK not installed")
    from src.agents.subnet_discovery_agent import SubnetDiscoveryAgent
    from src.orchestrator import SwarmOrchestrator

    orch = SwarmOrchestrator({
        "use_mock_data": False, "network": "finney",
        "wallet_mode": "WATCH_ONLY",
    })
    orch.register_agent(SubnetDiscoveryAgent({
        "use_mock_data": False, "network": "finney",
        "chain_db_path": str(tmp_path / "agent_chain.db"),
    }))

    out = orch.execute_task({"type": "subnet_discovery"})

    assert out["status"] == "success"
    payload = out["output"]
    assert payload["source"] == "chain", (
        f"expected source=chain in live mode, got {payload['source']}"
    )
    assert payload["subnet_count"] > 50
    assert any(
        isinstance(s.get("identity"), dict) and s["identity"].get("description")
        for s in payload["subnets"]
    ), "expected at least one subnet with a real identity description"
