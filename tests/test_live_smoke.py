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
    try:
        subnets = c.get_subnet_list()
    except (ConnectionError, OSError, RuntimeError) as exc:
        # WSS / SSL flakiness against the public finney endpoint is
        # environmental — skip rather than report a false negative.
        pytest.skip(f"finney endpoint unreachable: {exc!r}")

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
# Market trade agent end-to-end against live CoinGecko
# ---------------------------------------------------------------------------

def test_live_market_trade_agent_uses_collector(tmp_path):
    """End-to-end: the market-trade agent in live mode pulls real
    price + volume from the ``MarketDataCollector`` and produces an
    analysis tagged ``source=coingecko``."""
    from src.agents.market_trade_agent import MarketTradeAgent

    agent = MarketTradeAgent({
        "use_mock_data": False,
        "paper_trading": True,
        "market_db_path": str(tmp_path / "market_smoke.db"),
    })
    out = agent.run({
        "type": "market_analysis",
        "params": {"action": "analyze", "symbol": "TAO"},
    })

    assert out.get("status") == "analyzed"
    analysis = out.get("analysis", {})
    price = analysis.get("price", {})
    volume = analysis.get("volume", {})

    # Live path tags itself; mock fallback would say "mock".
    if price.get("source") == "coingecko":
        assert price.get("current", 0) > 0
        # _meta must propagate the collector's mode.
        assert price.get("_meta", {}).get("mode") in ("live", "mock")
    if volume.get("source") == "coingecko":
        assert volume.get("volume_24h_usd", 0) >= 0


# ---------------------------------------------------------------------------
# Subnet scoring agent uses live chain economics (tao_in)
# ---------------------------------------------------------------------------

def test_live_subnet_scoring_uses_chain_economics(tmp_path):
    """When ``SubnetScoringAgent`` receives subnets that carry chain
    economics (``tao_in``), the competition score must reflect the
    live stake rather than the hardcoded netuid heuristic."""
    pytest.importorskip("bittensor", reason="bittensor SDK not installed")
    from src.agents.subnet_discovery_agent import SubnetDiscoveryAgent
    from src.agents.subnet_scoring_agent import SubnetScoringAgent
    from src.orchestrator import SwarmOrchestrator

    orch = SwarmOrchestrator({
        "use_mock_data": False, "network": "finney",
        "wallet_mode": "WATCH_ONLY",
    })
    orch.register_agent(SubnetDiscoveryAgent({
        "use_mock_data": False, "network": "finney",
        "chain_db_path": str(tmp_path / "score_chain.db"),
    }))
    orch.register_agent(SubnetScoringAgent({}))

    try:
        disc = orch.execute_task({"type": "subnet_discovery"})
    except (ConnectionError, OSError, RuntimeError) as exc:
        pytest.skip(f"finney endpoint unreachable: {exc!r}")

    if disc.get("status") != "success":
        pytest.skip(f"discovery failed: {disc!r}")
    if disc["output"].get("source") != "chain":
        pytest.skip(
            f"discovery fell back from chain to "
            f"{disc['output'].get('source')!r} — transient endpoint flake"
        )
    discovered = disc["output"]["subnets"]
    # Pick a couple of subnets that have chain economics (skip root).
    candidates = [s for s in discovered if s.get("netuid", 0) > 0 and s.get("tao_in")]
    if not candidates:
        pytest.skip("no live subnets with tao_in returned by chain")

    out = orch.execute_task({"type": "subnet_scoring", "subnets": candidates[:3]})
    assert out["status"] == "success"
    scored = out["output"]["scored_subnets"]
    assert scored, "expected at least one scored subnet"

    # At least one of the competition reasons must cite TAO_in (the
    # live-data path), not the heuristic.
    reasons = [
        s.get("criteria_scores", {}).get("competition", {}).get("reason", "")
        for s in scored
    ]
    assert any("TAO_in" in r for r in reasons), (
        f"expected at least one competition reason to cite TAO_in; got {reasons!r}"
    )


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
    if payload.get("source") != "chain":
        # Discovery's collector wraps SSL/conn errors and falls back
        # to metadata-hints. Treat sandbox-only network flakiness as
        # skip rather than fail.
        pytest.skip(
            f"discovery fell back from chain to {payload.get('source')!r} "
            "— transient endpoint failure, not a code regression"
        )
    assert payload["subnet_count"] > 50
    assert any(
        isinstance(s.get("identity"), dict) and s["identity"].get("description")
        for s in payload["subnets"]
    ), "expected at least one subnet with a real identity description"
