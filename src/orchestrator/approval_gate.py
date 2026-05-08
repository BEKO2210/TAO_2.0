"""
Approval Gate Module for TAO/Bittensor Multi-Agent System.

Provides safety classification for all agent actions using a three-tier system:
- SAFE: Read-only operations with no risk
- CAUTION: Operations that modify state but are reversible
- DANGER: Irreversible operations involving real value

All wallet operations are strictly gated and never execute automatically.
"""

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Classification(str, Enum):
    """Three-tier safety classification for agent actions."""

    SAFE = "SAFE"
    CAUTION = "CAUTION"
    DANGER = "DANGER"


# Action classification mappings
_SAFE_ACTIONS: set[str] = {
    # Read public data
    "read_public_data",
    "fetch_market_data",
    "fetch_chain_data",
    "query_subtensor",
    "get_subnet_info",
    "get_block_data",
    "fetch_price",
    "fetch_volume",
    "get_metadata",
    # Local analysis
    "analyze_data",
    "compute_score",
    "generate_report",
    "run_analysis",
    "check_readiness",
    "evaluate_hardware",
    # Paper trading (simulated)
    "paper_trade",
    "simulate_trade",
    "backtest_strategy",
    # Wallet watch-only (read-only)
    "watch_wallet",
    "get_balance",
    "list_transfers",
    "get_staking_status",
    # Documentation
    "generate_docs",
    "update_readme",
    # Code review
    "review_code",
    "lint_code",
    # Design
    "design_dashboard",
    "create_mockup",
    # Testing
    "run_tests",
    "check_secrets",
    # Research
    "research_protocol",
    "discover_subnets",
    # Local infrastructure
    "plan_infra",
    "generate_dockerfile",
    # Training
    "plan_training",
    "estimate_hardware",
}

_CAUTION_ACTIONS: set[str] = {
    # Install dependencies
    "install_deps",
    "pip_install",
    "npm_install",
    "apt_install",
    # API connections (external)
    "connect_api",
    "api_request",
    "subscribe_websocket",
    # Testnet operations
    "testnet_register",
    "testnet_stake",
    "testnet_unstake",
    "faucet_request",
    # Local miner test (not mainnet)
    "local_miner_test",
    "start_local_miner",
    "test_miner",
    # Docker operations
    "build_container",
    "run_container",
    "compose_up",
    # File system changes
    "write_file",
    "modify_config",
    "create_directory",
}

_DANGER_ACTIONS: set[str] = {
    # Wallet creation (irreversible)
    "create_wallet",
    "create_hotkey",
    "create_coldkey",
    "regenerate_key",
    # Signing operations
    "sign_transaction",
    "sign_message",
    "approve_signature",
    # Staking / Financial
    "stake",
    "unstake",
    "delegate",
    "undelegate",
    "transfer",
    "send_tao",
    # Trading with real funds
    "execute_trade",
    "place_order",
    "market_order",
    "limit_order",
    # Mainnet registration
    "mainnet_register",
    "register_neuron",
    "register_miner",
    "register_validator",
    "burn_register",
    # Key exposure risk
    "export_key",
    "show_mnemonic",
    "reveal_seed",
    "backup_wallet",
    # Network-level operations
    "set_weights",
    "serve_axon",
    "commit_weights",
}

_WALLET_PERMISSIONS: dict[str, Classification] = {
    "create_wallet": Classification.DANGER,
    "create_hotkey": Classification.DANGER,
    "create_coldkey": Classification.DANGER,
    "show_mnemonic": Classification.DANGER,
    "export_key": Classification.DANGER,
    "reveal_seed": Classification.DANGER,
    "sign_transaction": Classification.DANGER,
    "sign_message": Classification.DANGER,
    "stake": Classification.DANGER,
    "unstake": Classification.DANGER,
    "delegate": Classification.DANGER,
    "undelegate": Classification.DANGER,
    "transfer": Classification.DANGER,
    "send_tao": Classification.DANGER,
    "trade": Classification.DANGER,
    "execute_trade": Classification.DANGER,
    "place_order": Classification.DANGER,
    "mainnet_register": Classification.DANGER,
    "set_weights": Classification.DANGER,
    "watch_wallet": Classification.SAFE,
    "get_balance": Classification.SAFE,
    "list_transfers": Classification.SAFE,
    "get_staking_status": Classification.SAFE,
}


class ApprovalGate:
    """
    Central safety gate that classifies all agent actions.

    Every action is classified as SAFE, CAUTION, or DANGER based on
    predefined rules. DANGER actions NEVER execute automatically -
    they are only reported as plans requiring human approval.

    Wallet mode controls the permission level:
    - NO_WALLET (default): No wallet operations allowed
    - WATCH_ONLY: Read-only wallet observation
    - FULL: All operations (DANGER still requires manual override)
    """

    SAFE: str = Classification.SAFE
    CAUTION: str = Classification.CAUTION
    DANGER: str = Classification.DANGER

    # Wallet mode constants
    MODE_NO_WALLET: str = "NO_WALLET"
    MODE_WATCH_ONLY: str = "WATCH_ONLY"
    MODE_MANUAL_SIGNING: str = "MANUAL_SIGNING"

    def __init__(self, wallet_mode: str = "NO_WALLET") -> None:
        """
        Initialize the ApprovalGate.

        Args:
            wallet_mode: One of "NO_WALLET", "WATCH_ONLY", "FULL"
        """
        self._wallet_mode = wallet_mode.upper()
        self._rules: list[dict[str, Any]] = self._build_rules()
        self._override_enabled = False
        logger.info(
            "ApprovalGate initialized with wallet_mode=%s", self._wallet_mode
        )

    def _build_rules(self) -> list[dict[str, Any]]:
        """Build the complete list of safety rules."""
        return [
            {
                "id": "RULE-001",
                "category": "wallet",
                "description": "NEVER request, store, or transmit seed phrases or private keys",
                "severity": "CRITICAL",
                "classification": Classification.DANGER,
            },
            {
                "id": "RULE-002",
                "category": "wallet",
                "description": "NEVER create wallets or keys without explicit user confirmation",
                "severity": "CRITICAL",
                "classification": Classification.DANGER,
            },
            {
                "id": "RULE-003",
                "category": "wallet",
                "description": "NEVER sign transactions or messages automatically",
                "severity": "CRITICAL",
                "classification": Classification.DANGER,
            },
            {
                "id": "RULE-004",
                "category": "wallet",
                "description": "Wallet watch-only mode is SAFE; never request credentials",
                "severity": "INFO",
                "classification": Classification.SAFE,
            },
            {
                "id": "RULE-005",
                "category": "trading",
                "description": "NEVER execute real trades or orders automatically",
                "severity": "CRITICAL",
                "classification": Classification.DANGER,
            },
            {
                "id": "RULE-006",
                "category": "trading",
                "description": "Paper trading and backtesting are SAFE",
                "severity": "INFO",
                "classification": Classification.SAFE,
            },
            {
                "id": "RULE-007",
                "category": "staking",
                "description": "NEVER stake, unstake, delegate, or transfer without approval",
                "severity": "CRITICAL",
                "classification": Classification.DANGER,
            },
            {
                "id": "RULE-008",
                "category": "registration",
                "description": "NEVER register on mainnet without explicit approval",
                "severity": "CRITICAL",
                "classification": Classification.DANGER,
            },
            {
                "id": "RULE-009",
                "category": "network",
                "description": "NEVER set weights or serve axon without approval",
                "severity": "CRITICAL",
                "classification": Classification.DANGER,
            },
            {
                "id": "RULE-010",
                "category": "dependencies",
                "description": "Installing packages requires CAUTION - verify sources",
                "severity": "WARNING",
                "classification": Classification.CAUTION,
            },
            {
                "id": "RULE-011",
                "category": "api",
                "description": "External API connections require CAUTION",
                "severity": "WARNING",
                "classification": Classification.CAUTION,
            },
            {
                "id": "RULE-012",
                "category": "testnet",
                "description": "Testnet operations are CAUTION (no real value but state changes)",
                "severity": "WARNING",
                "classification": Classification.CAUTION,
            },
            {
                "id": "RULE-013",
                "category": "data",
                "description": "Reading public blockchain data is SAFE",
                "severity": "INFO",
                "classification": Classification.SAFE,
            },
            {
                "id": "RULE-014",
                "category": "analysis",
                "description": "Local analysis and report generation is SAFE",
                "severity": "INFO",
                "classification": Classification.SAFE,
            },
            {
                "id": "RULE-015",
                "category": "security",
                "description": "Any operation involving key exposure is DANGER",
                "severity": "CRITICAL",
                "classification": Classification.DANGER,
            },
        ]

    def classify_action(self, action_type: str, params: dict | None = None) -> str:
        """
        Classify a single action into SAFE, CAUTION, or DANGER.

        Args:
            action_type: The type of action to classify
            params: Optional parameters that may affect classification

        Returns:
            Classification string: "SAFE", "CAUTION", or "DANGER"

        Raises:
            ValueError: If action_type is not a string
        """
        if not isinstance(action_type, str):
            raise ValueError(f"action_type must be a string, got {type(action_type).__name__}")
        params = params or {}
        action_lower = action_type.lower()

        # Direct lookup in danger list first (most restrictive)
        if action_lower in _DANGER_ACTIONS:
            logger.warning(
                "Action '%s' classified as DANGER", action_type
            )
            return Classification.DANGER

        # Check caution list
        if action_lower in _CAUTION_ACTIONS:
            logger.info(
                "Action '%s' classified as CAUTION", action_type
            )
            return Classification.CAUTION

        # Check safe list
        if action_lower in _SAFE_ACTIONS:
            logger.debug(
                "Action '%s' classified as SAFE", action_type
            )
            return Classification.SAFE

        # Heuristic fallback for unknown actions
        danger_keywords = [
            "sign", "stake", "unstake", "delegate", "transfer", "send_",
            "trade", "order", "register", "create_wallet", "create_key",
            "mnemonic", "seed", "private_key", "export", "burn",
            "commit_weights", "serve_axon",
        ]
        caution_keywords = [
            "install", "connect", "write", "modify", "create_",
            "delete", "update", "build", "run_container",
        ]

        for kw in danger_keywords:
            if kw in action_lower:
                logger.warning(
                    "Unknown action '%s' matched DANGER keyword '%s'",
                    action_type, kw,
                )
                return Classification.DANGER

        for kw in caution_keywords:
            if kw in action_lower:
                logger.info(
                    "Unknown action '%s' matched CAUTION keyword '%s'",
                    action_type, kw,
                )
                return Classification.CAUTION

        # Default: unknown actions are SAFE (read-only default)
        logger.info(
            "Unknown action '%s' defaulted to SAFE", action_type
        )
        return Classification.SAFE

    def can_execute_with_override(self, classification: str, override: bool = False) -> bool:
        """
        Determine if an action can execute with optional override.

        SAFE and CAUTION actions always execute. DANGER actions only
        execute with explicit override=True.

        Args:
            classification: The action classification (SAFE/CAUTION/DANGER)
            override: Whether the user has explicitly approved a DANGER action

        Returns:
            True if execution is permitted
        """
        classification = classification.upper()

        if classification == Classification.SAFE:
            return True
        if classification == Classification.CAUTION:
            return True
        if classification == Classification.DANGER:
            return override
        return False

    def can_execute(self, classification: str, override: bool = False) -> bool:
        """
        Determine if an action with the given classification can execute.

        SAFE actions always execute. CAUTION actions execute with logging.
        DANGER actions only execute with explicit override flag.

        Args:
            classification: The action classification (SAFE/CAUTION/DANGER)
            override: Whether the user has explicitly approved a DANGER action

        Returns:
            True if execution is permitted, False otherwise
        """
        classification = classification.upper()

        if classification == Classification.SAFE:
            logger.debug("SAFE action approved for execution")
            return True

        if classification == Classification.CAUTION:
            logger.info("CAUTION action approved with logging")
            return True

        if classification == Classification.DANGER:
            if override:
                logger.critical(
                    "DANGER action approved via EXPLICIT OVERRIDE"
                )
                return True
            logger.error(
                "DANGER action BLOCKED - requires explicit override"
            )
            return False

        logger.warning("Unknown classification '%s', defaulting to block", classification)
        return False

    def validate_plan(self, plan: dict) -> dict:
        """
        Validate a complete execution plan against all safety rules.

        Args:
            plan: Dictionary with 'actions' list or single 'action' key
                  Each action: {"type": str, "params": dict (optional)}

        Returns:
            Validation result with keys:
            - valid: bool (True if plan can proceed)
            - classification: str (highest classification found)
            - reasons: list[str] (human-readable explanation)
            - actions: list[dict] (per-action results)
        """
        reasons: list[str] = []
        action_results: list[dict] = []
        highest_classification = Classification.SAFE

        actions = plan.get("actions", [])
        if not actions and "type" in plan:
            actions = [plan]

        if not actions:
            return {
                "valid": True,
                "classification": Classification.SAFE,
                "reasons": ["Empty plan - nothing to validate"],
                "actions": [],
            }

        for idx, action in enumerate(actions):
            action_type = action.get("type", "unknown")
            params = action.get("params", {})
            classification = self.classify_action(action_type, params)

            # Track highest (most dangerous) classification
            if classification == Classification.DANGER:
                highest_classification = Classification.DANGER
            elif classification == Classification.CAUTION and highest_classification != Classification.DANGER:
                highest_classification = Classification.CAUTION

            can_exec = self.can_execute(classification)
            action_result = {
                "index": idx,
                "type": action_type,
                "classification": classification,
                "can_execute": can_exec,
            }
            action_results.append(action_result)

            if classification == Classification.DANGER:
                reasons.append(
                    f"Action [{idx}] '{action_type}' is DANGER and requires "
                    f"manual approval (override=True)"
                )
            elif classification == Classification.CAUTION:
                reasons.append(
                    f"Action [{idx}] '{action_type}' is CAUTION - proceeding with care"
                )
            else:
                reasons.append(
                    f"Action [{idx}] '{action_type}' is SAFE"
                )

        # Check wallet mode compatibility
        if highest_classification == Classification.DANGER and self._wallet_mode == "NO_WALLET":
            reasons.append(
                "CRITICAL: DANGER actions blocked - wallet_mode is NO_WALLET"
            )
            valid = False
        elif highest_classification == Classification.DANGER:
            reasons.append(
                "Plan contains DANGER actions - will only output as plan, not execute"
            )
            valid = False
        else:
            valid = True

        return {
            "valid": valid,
            "classification": highest_classification,
            "reasons": reasons,
            "actions": action_results,
        }

    @property
    def rules(self) -> list[dict[str, Any]]:
        """
        Return the complete list of safety rules.

        Returns:
            List of rule dictionaries with id, category, description,
            severity, and classification keys.
        """
        return [rule.copy() for rule in self._rules]

    def get_rules(self) -> list[dict[str, Any]]:
        """
        Return the complete list of safety rules.

        Returns:
            List of rule dictionaries with id, category, description,
            severity, and classification keys.
        """
        return self.rules

    def check_wallet_permission(self, action: str, mode: str | None = None) -> bool:
        """
        Check if a wallet-related action is permitted.

        Args:
            action: The wallet action to check
            mode: Optional wallet mode override. If None, uses current mode.

        Returns:
            True if the action is permitted in the given wallet_mode
        """
        action_lower = action.lower()
        classification = _WALLET_PERMISSIONS.get(
            action_lower, Classification.SAFE
        )

        wallet_mode = (mode or self._wallet_mode).upper()

        if wallet_mode == "NO_WALLET":
            # Only SAFE read-only operations allowed
            if classification == Classification.DANGER:
                logger.error(
                    "Wallet action '%s' BLOCKED in NO_WALLET mode", action
                )
                return False
            if classification == Classification.CAUTION:
                logger.warning(
                    "Wallet action '%s' is CAUTION in NO_WALLET mode", action
                )
                return False
            return True

        if wallet_mode == "WATCH_ONLY":
            # Only SAFE operations allowed
            if classification == Classification.DANGER:
                logger.error(
                    "Wallet action '%s' BLOCKED in WATCH_ONLY mode", action
                )
                return False
            return True

        if wallet_mode == "FULL" or wallet_mode == "MANUAL_SIGNING":
            # All allowed but DANGER still requires override
            return True

        logger.warning(
            "Unknown wallet_mode '%s', defaulting to deny", wallet_mode
        )
        return False

    @property
    def wallet_mode(self) -> str:
        """Return the current wallet mode."""
        return self._wallet_mode

    def set_wallet_mode(self, mode: str) -> None:
        """
        Change the wallet mode (requires logging).

        Args:
            mode: One of "NO_WALLET", "WATCH_ONLY", "FULL"
        """
        mode = mode.upper()
        if mode not in ("NO_WALLET", "WATCH_ONLY", "FULL"):
            raise ValueError(f"Invalid wallet_mode: {mode}")
        logger.info("Wallet mode changed: %s -> %s", self._wallet_mode, mode)
        self._wallet_mode = mode
