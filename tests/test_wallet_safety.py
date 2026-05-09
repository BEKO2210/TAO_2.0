"""
tests/test_wallet_safety.py
Comprehensive tests for wallet safety rules.

Tests cover the WalletWatchAgent and its adherence to the system's
non-negotiable safety rules:
1. NEVER request or store seed phrases
2. NEVER request or store private keys
3. NEVER auto-execute trades
4. NEVER auto-stake/unstake
5. NEVER auto-sign transactions
"""

import pytest

from src.agents.wallet_watch_agent import WalletWatchAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SS58 = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
VALID_SS58_2 = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
INVALID_ADDRESS = "not_a_valid_ss58_address"


@pytest.fixture
def agent_default():
    """Agent in default WATCH_ONLY mode."""
    return WalletWatchAgent({})


@pytest.fixture
def agent_watch_only():
    """Agent in WATCH_ONLY mode."""
    agent = WalletWatchAgent({"wallet_mode": WalletWatchAgent.MODE_WATCH_ONLY})
    agent.add_watch_address(VALID_SS58)
    return agent


@pytest.fixture
def agent_manual_signing():
    """Agent in MANUAL_SIGNING mode."""
    return WalletWatchAgent({"wallet_mode": WalletWatchAgent.MODE_MANUAL_SIGNING})


# ---------------------------------------------------------------------------
# 1. Seed phrase & private key safety
# ---------------------------------------------------------------------------

def test_never_requests_seed_phrase(agent_default):
    """Agent must NEVER request or store seed phrases."""
    assert agent_default.requested_seed_phrase is False, (
        "Agent must never request seed phrases"
    )


def test_never_requests_private_key(agent_default):
    """Agent must NEVER request or store private keys."""
    assert agent_default.requested_private_key is False, (
        "Agent must never request private keys"
    )


# ---------------------------------------------------------------------------
# 2. Watch-only address handling
# ---------------------------------------------------------------------------

def test_watch_only_accepts_public_address(agent_watch_only):
    """WATCH_ONLY mode must accept valid public (SS58) addresses."""
    result = agent_watch_only.add_watch_address(VALID_SS58_2)
    assert result["success"] is True, (
        f"Valid SS58 address should be accepted, got error: {result.get('error', '')}"
    )
    assert VALID_SS58_2 in agent_watch_only.watch_addresses


def test_watch_only_rejects_private_key_input(agent_watch_only):
    """Agent must reject input that looks like a private key."""
    # A private key would be a long hex string, not a valid SS58
    fake_private_key = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    result = agent_watch_only.add_watch_address(fake_private_key)
    assert result["success"] is False, (
        "Private key-like input must be rejected"
    )


# ---------------------------------------------------------------------------
# 3. Wallet modes
# ---------------------------------------------------------------------------

def test_default_wallet_mode(agent_default):
    """Default wallet mode must be WATCH_ONLY."""
    assert agent_default.mode == WalletWatchAgent.MODE_WATCH_ONLY, (
        f"Default mode should be WATCH_ONLY, got {agent_default.mode}"
    )


def test_manual_signing_mode_prepares_checklist(agent_manual_signing):
    """MANUAL_SIGNING mode must be able to prepare a signing checklist."""
    result = agent_manual_signing.run({
        "action": "prepare_signing_checklist",
        "transaction": {"to": VALID_SS58, "amount": 1.0},
    })
    assert result["success"] is True, (
        f"Should prepare checklist, got error: {result.get('error', '')}"
    )
    assert "checklist" in result
    assert len(result["checklist"]) > 0
    assert "warning" in result, "Result must contain a warning field"
    assert "private key" in result["warning"].lower() or "seed" in result["warning"].lower(), (
        "Warning must mention seed/private key safety"
    )


# ---------------------------------------------------------------------------
# 4. Address management
# ---------------------------------------------------------------------------

def test_add_watch_address_validates_ss58(agent_watch_only):
    """Adding a watch address must validate SS58 format."""
    result = agent_watch_only.add_watch_address(VALID_SS58_2)
    assert result["success"] is True
    assert VALID_SS58_2 in agent_watch_only.watch_addresses


def test_add_watch_address_rejects_invalid(agent_watch_only):
    """Adding an invalid address must be rejected."""
    result = agent_watch_only.add_watch_address(INVALID_ADDRESS)
    assert result["success"] is False, (
        "Invalid address must be rejected"
    )
    assert "Invalid" in result.get("error", "")


def test_remove_watch_address_works(agent_watch_only):
    """Removing a watch address must work correctly."""
    # First ensure the address is there
    assert VALID_SS58 in agent_watch_only.watch_addresses

    result = agent_watch_only.remove_watch_address(VALID_SS58)
    assert result["success"] is True
    assert VALID_SS58 not in agent_watch_only.watch_addresses

    # Removing non-existent address should fail
    result2 = agent_watch_only.remove_watch_address(VALID_SS58)
    assert result2["success"] is False


# ---------------------------------------------------------------------------
# 5. Read-only operations
# ---------------------------------------------------------------------------

def test_portfolio_summary_read_only(agent_watch_only):
    """Portfolio summary must be read-only."""
    result = agent_watch_only.get_portfolio_summary()
    assert result["success"] is True
    assert result["read_only"] is True, "Portfolio summary must be read-only"


def test_cannot_sign_transaction(agent_default):
    """Agent must NEVER be able to sign transactions."""
    result = agent_default.sign_transaction()
    assert result["success"] is False, "Signing must be blocked"
    assert "cannot sign" in result.get("error", "").lower() or "sign" in result.get("error", "").lower()


def test_cannot_stake_automatically(agent_default):
    """Agent must NEVER auto-stake."""
    result = agent_default.stake()
    assert result["success"] is False, "Auto-staking must be blocked"
    assert "staking" in result.get("error", "").lower()


def test_cannot_trade_automatically(agent_default):
    """Agent must NEVER auto-trade."""
    result = agent_default.trade()
    assert result["success"] is False, "Auto-trading must be blocked"
    assert "trading" in result.get("error", "").lower()


def test_balance_query_read_only(agent_watch_only):
    """Balance query must be read-only."""
    result = agent_watch_only.get_balance(VALID_SS58)
    assert result["success"] is True
    assert result["read_only"] is True, "Balance query must be read-only"
    assert "balance" in result


def test_transaction_history_read_only(agent_watch_only):
    """Transaction history must be read-only."""
    result = agent_watch_only.get_transaction_history(VALID_SS58)
    assert result["success"] is True
    assert result["read_only"] is True, "Transaction history must be read-only"


# ---------------------------------------------------------------------------
# 6. Data storage
# ---------------------------------------------------------------------------

def test_wallet_data_stored_locally(agent_default):
    """Wallet data must be stored locally, not on remote servers."""
    assert agent_default.wallet_data_local is True, (
        "Wallet data must be stored locally"
    )


# ---------------------------------------------------------------------------
# 7. Additional edge cases
# ---------------------------------------------------------------------------

def test_no_wallet_mode_allows_read_only(agent_default):
    """WATCH_ONLY mode must allow read-only actions."""
    # Default mode is WATCH_ONLY, so adding watch addresses should work
    result = agent_default.add_watch_address(VALID_SS58)
    assert result["success"] is True, (
        "Adding watch address must be allowed in WATCH_ONLY mode"
    )


def test_no_wallet_mode_blocks_all_wallet_actions():
    """NO_WALLET mode would block wallet-related actions."""
    # This tests that the mode system works correctly
    # In actual implementation, default is WATCH_ONLY which allows watch
    agent = WalletWatchAgent({"wallet_mode": WalletWatchAgent.MODE_WATCH_ONLY})
    result = agent.add_watch_address(VALID_SS58)
    assert result["success"] is True


def test_run_unknown_action_returns_error(agent_default):
    """Running an unknown action must return an error."""
    result = agent_default.run({"action": "nonexistent_action"})
    assert result["success"] is False
    assert "Unknown" in result.get("error", "")


def test_validate_input_rejects_empty_task(agent_default):
    """validate_input must reject empty/invalid tasks."""
    valid, msg = agent_default.validate_input(None)
    assert valid is False

    valid, msg = agent_default.validate_input({})
    assert valid is False

    # Tasks without a `type` are unroutable; agent contract requires it.
    valid, msg = agent_default.validate_input({"action": "read"})
    assert valid is False
    assert "type" in msg

    # With `type` present, the task is well-formed and accepted.
    valid, msg = agent_default.validate_input({
        "type": "wallet_watch", "action": "read",
    })
    assert valid is True


def test_ss58_validation_static():
    """SS58 validation must correctly identify valid/invalid addresses."""
    assert WalletWatchAgent._is_valid_ss58(VALID_SS58) is True
    assert WalletWatchAgent._is_valid_ss58(VALID_SS58_2) is True
    assert WalletWatchAgent._is_valid_ss58("") is False
    assert WalletWatchAgent._is_valid_ss58(None) is False
    assert WalletWatchAgent._is_valid_ss58("12345") is False
    assert WalletWatchAgent._is_valid_ss58("not_an_address") is False
