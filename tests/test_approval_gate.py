"""
tests/test_approval_gate.py
Comprehensive tests for the ApprovalGate class.

Tests cover:
- SAFE action classification and execution
- CAUTION action classification with/without override
- DANGER action blocking
- Wallet mode restrictions
- Plan validation
- Override behavior
- Error handling for invalid inputs
"""

import pytest

from src.orchestrator.approval_gate import ApprovalGate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gate():
    """Provide a fresh ApprovalGate instance for each test."""
    return ApprovalGate()


@pytest.fixture
def safe_actions():
    """List of all SAFE action types."""
    return [
        "read",
        "analyze",
        "query",
        "fetch",
        "paper_trade",
        "wallet_watch_only",
        "portfolio_summary",
        "balance_query",
        "transaction_history",
        "report",
        "monitor",
        "discover",
        "research",
    ]


@pytest.fixture
def caution_actions():
    """List of all CAUTION action types."""
    return [
        "install",
        "api_call",
        "testnet_interact",
        "setup",
        "configure",
        "clone_repo",
    ]


@pytest.fixture
def danger_actions():
    """List of all DANGER action types."""
    return [
        "wallet_create",
        "sign_transaction",
        "stake",
        "unstake",
        "trade",
        "mainnet_interact",
        "transfer",
        "delegate",
        "register",
        "burn",
    ]


# ---------------------------------------------------------------------------
# 1. SAFE actions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", [
    "read", "analyze", "query", "fetch", "paper_trade",
    "wallet_watch_only", "portfolio_summary", "balance_query",
    "transaction_history", "report", "monitor", "discover", "research",
])
def test_safe_actions_allowed(gate, action):
    """SAFE actions must classify as SAFE and be executable."""
    classification = gate.classify_action(action)
    assert classification == ApprovalGate.SAFE, (
        f"Action '{action}' should be SAFE, got {classification}"
    )
    assert gate.can_execute(classification) is True, (
        f"SAFE action '{action}' should be executable"
    )


# ---------------------------------------------------------------------------
# 2. CAUTION actions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", [
    "install_deps", "connect_api", "write_file", "modify_config", "build_container",
])
def test_caution_actions_require_override(gate, action):
    """CAUTION actions must classify as CAUTION and be executable with logging."""
    classification = gate.classify_action(action)
    assert classification == ApprovalGate.CAUTION, (
        f"Action '{action}' should be CAUTION, got {classification}"
    )
    assert gate.can_execute(classification) is True, (
        f"CAUTION action '{action}' should be executable with logging"
    )


# ---------------------------------------------------------------------------
# 3. DANGER actions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", [
    "create_wallet", "sign_transaction", "stake", "unstake",
    "trade", "mainnet_register", "transfer", "delegate", "register_miner", "burn_register",
])
def test_danger_actions_blocked(gate, action):
    """DANGER actions must classify as DANGER and be blocked without override."""
    classification = gate.classify_action(action)
    assert classification == ApprovalGate.DANGER, (
        f"Action '{action}' should be DANGER, got {classification}"
    )
    assert gate.can_execute(classification) is False, (
        f"DANGER action '{action}' must be blocked without override"
    )
    assert gate.can_execute_with_override(classification, override=True) is True, (
        f"DANGER action '{action}' must be allowed with explicit override"
    )


# ---------------------------------------------------------------------------
# 4. Wallet modes
# ---------------------------------------------------------------------------

def test_no_wallet_mode_blocks_danger_actions(gate):
    """NO_WALLET mode must block DANGER wallet actions."""
    danger_actions = ["stake", "transfer", "create_wallet"]
    for action in danger_actions:
        allowed = gate.check_wallet_permission(action, ApprovalGate.MODE_NO_WALLET)
        assert allowed is False, (
            f"DANGER action '{action}' must be blocked in NO_WALLET mode"
        )
    # SAFE actions should still be allowed
    assert gate.check_wallet_permission("read", ApprovalGate.MODE_NO_WALLET) is True


def test_watch_only_allows_read_only(gate):
    """WATCH_ONLY mode must allow read-only actions and block DANGER."""
    read_actions = ["read", "analyze", "query", "fetch", "report", "monitor", "research"]
    for action in read_actions:
        allowed = gate.check_wallet_permission(action, ApprovalGate.MODE_WATCH_ONLY)
        assert allowed is True, (
            f"Read-only action '{action}' must be allowed in WATCH_ONLY mode"
        )

    # But danger actions must still be blocked
    danger = ["stake", "trade", "sign_transaction"]
    for action in danger:
        allowed = gate.check_wallet_permission(action, ApprovalGate.MODE_WATCH_ONLY)
        assert allowed is False, (
            f"DANGER action '{action}' must be blocked in WATCH_ONLY mode"
        )


# ---------------------------------------------------------------------------
# 5. Plan validation
# ---------------------------------------------------------------------------

def test_plan_validation_safe(gate):
    """A plan with only SAFE steps must be valid."""
    plan = {
        "actions": [
            {"type": "read", "target": "subnet_metadata"},
            {"type": "analyze", "target": "rewards"},
            {"type": "report", "target": "dashboard"},
        ]
    }
    result = gate.validate_plan(plan)
    assert result["valid"] is True, "SAFE plan should be valid"
    assert result["classification"] == ApprovalGate.SAFE
    assert any("SAFE" in r for r in result["reasons"])


def test_plan_validation_caution(gate):
    """A plan with CAUTION steps must have CAUTION classification and be valid."""
    plan = {
        "actions": [
            {"type": "read", "target": "subnet_metadata"},
            {"type": "install", "target": "dependency"},
        ]
    }
    result = gate.validate_plan(plan)
    assert result["classification"] == ApprovalGate.CAUTION
    assert result["valid"] is True  # CAUTION is executable with logging
    assert any("install" in r for r in result["reasons"])


def test_plan_validation_danger_blocked(gate):
    """A plan with DANGER steps must be invalid."""
    plan = {
        "actions": [
            {"type": "read", "target": "subnet_metadata"},
            {"type": "stake", "target": "subnet_1"},
        ]
    }
    result = gate.validate_plan(plan)
    assert result["valid"] is False, "Plan with DANGER step must be invalid"
    assert result["classification"] == ApprovalGate.DANGER
    assert any("stake" in r for r in result["reasons"])


# ---------------------------------------------------------------------------
# 6. Wallet permission check
# ---------------------------------------------------------------------------

def test_wallet_permission_check(gate):
    """check_wallet_permission must correctly evaluate actions per mode."""
    # Read action in NO_WALLET mode
    assert gate.check_wallet_permission("read", ApprovalGate.MODE_NO_WALLET) is True

    # Read action in WATCH_ONLY mode
    assert gate.check_wallet_permission("read", ApprovalGate.MODE_WATCH_ONLY) is True

    # Stake (DANGER) in MANUAL_SIGNING mode - FULL-like mode allows all
    assert gate.check_wallet_permission("stake", ApprovalGate.MODE_MANUAL_SIGNING) is True

    # Read action in MANUAL_SIGNING mode
    assert gate.check_wallet_permission("read", ApprovalGate.MODE_MANUAL_SIGNING) is True

    # Stake (DANGER) in WATCH_ONLY mode - should be blocked
    assert gate.check_wallet_permission("stake", ApprovalGate.MODE_WATCH_ONLY) is False


# ---------------------------------------------------------------------------
# 7. Rules
# ---------------------------------------------------------------------------

def test_rules_list_not_empty(gate):
    """The rules list must contain all safety rules."""
    rules = gate.rules
    assert len(rules) > 0, "Rules list must not be empty"
    # rules is a list of dicts; check description field
    descriptions = [r.get("description", "").lower() for r in rules]
    assert any("seed" in d for d in descriptions), (
        "Rules must mention seed phrases"
    )
    assert any("private key" in d for d in descriptions), (
        "Rules must mention private keys"
    )
    assert any("trade" in d for d in descriptions), (
        "Rules must mention trades"
    )


# ---------------------------------------------------------------------------
# 8. Override behavior
# ---------------------------------------------------------------------------

def test_override_allows_caution(gate):
    """CAUTION actions are always executable (with logging)."""
    classification = ApprovalGate.CAUTION
    assert gate.can_execute_with_override(classification, override=True) is True
    assert gate.can_execute_with_override(classification, override=False) is True


def test_override_allows_danger_with_flag(gate):
    """DANGER actions are blocked without override but allowed with it."""
    classification = ApprovalGate.DANGER
    assert gate.can_execute_with_override(classification, override=True) is True
    assert gate.can_execute_with_override(classification, override=False) is False


# ---------------------------------------------------------------------------
# 9. Invalid inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_input", [None, 123, [], {}, set()])
def test_invalid_action_type_raises_error(gate, bad_input):
    """Non-string action_type must raise ValueError."""
    with pytest.raises(ValueError):
        gate.classify_action(bad_input)


def test_classify_unknown_action_returns_safe(gate):
    """Unknown/unrecognized actions must default to SAFE (read-only default)."""
    unknown_actions = ["fly_to_moon", "unknown_action_xyz", "foo_bar_baz"]
    for action in unknown_actions:
        classification = gate.classify_action(action)
        assert classification == ApprovalGate.SAFE, (
            f"Unknown action '{action}' should default to SAFE, got {classification}"
        )
