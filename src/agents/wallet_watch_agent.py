"""
Wallet Watch Agent (Agent 5).

Read-only wallet monitoring agent. Supports public wallet addresses
for balance tracking, transfer history, and staking status.

STRICT RULES:
- NEVER requests seeds or private keys
- NEVER creates wallets
- NEVER signs transactions
- Pure read-only observation mode
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "wallet_watch_agent"
AGENT_VERSION: str = "1.0.0"


class WalletWatchAgent:
    """
    Read-only wallet monitoring agent.

    Provides wallet balance, transfer history, and staking status
    for watched addresses. Operates strictly in watch-only mode -
    never requests or handles credentials, seeds, or private keys.

    All wallet operations are SAFE classification per ApprovalGate.
    """

    # Wallet mode constants
    MODE_NO_WALLET: str = "NO_WALLET"
    MODE_WATCH_ONLY: str = "WATCH_ONLY"
    MODE_MANUAL_SIGNING: str = "MANUAL_SIGNING"

    def __init__(self, config: dict = None) -> None:
        """
        Initialize the WalletWatchAgent.

        Args:
            config: Configuration with optional:
                - watched_addresses: List of addresses to monitor
                - labels: Dictionary of address -> label
                - use_mock_data: Whether to use mock data (default True)
                - wallet_mode: Wallet mode (default WATCH_ONLY)
        """
        config = config or {}
        self.config: dict = config
        self._status: str = "idle"
        self._watched: dict[str, dict] = {}
        self._labels: dict[str, str] = dict(config.get("labels", {}))
        self._use_mock: bool = config.get("use_mock_data", True)
        self._mode: str = config.get("wallet_mode", self.MODE_WATCH_ONLY)

        # Safety attributes (always False - agent never requests sensitive data)
        self.requested_seed_phrase: bool = False
        self.requested_private_key: bool = False
        self.wallet_data_local: bool = True

        # Initialize watched addresses
        for addr in config.get("watched_addresses", []):
            self._watched[addr] = {
                "added_at": time.time(),
                "label": self._labels.get(addr, ""),
                "last_check": None,
            }

        logger.info(
            "WalletWatchAgent initialized (watched=%d, mock=%s)",
            len(self._watched), self._use_mock,
        )

    @property
    def mode(self) -> str:
        """Return the current wallet mode."""
        return self._mode

    @property
    def watch_addresses(self) -> list:
        """Return list of watched addresses."""
        return list(self._watched.keys())

    def add_watch_address(self, address: str, label: str = "") -> dict:
        """
        Public wrapper to add an address to the watch list.

        Args:
            address: Wallet address to watch
            label: Optional label for the address

        Returns:
            Result dictionary with success/error info
        """
        if not self._validate_address(address):
            return {"success": False, "error": f"Invalid address format: {address}"}
        result = self._add_watch({"address": address, "label": label})
        if result["status"] in ("added", "already_watched"):
            return {"success": True, "address": address, "status": result["status"]}
        return {"success": False, "error": result.get("status", "unknown")}

    def remove_watch_address(self, address: str) -> dict:
        """
        Public wrapper to remove an address from the watch list.

        Args:
            address: Wallet address to remove

        Returns:
            Result dictionary with success/error info
        """
        result = self._remove_watch({"address": address})
        if result["status"] == "removed":
            return {"success": True, "address": address}
        return {"success": False, "error": f"Address not found: {address}"}

    def get_portfolio_summary(self) -> dict:
        """
        Get a read-only portfolio summary.

        Returns:
            Portfolio summary dictionary
        """
        result = self._portfolio_snapshot()
        return {
            "success": True,
            "read_only": True,
            **result,
        }

    def get_balance(self, address: str) -> dict:
        """
        Get balance for an address (read-only).

        Args:
            address: Wallet address

        Returns:
            Balance data dictionary
        """
        if not self._validate_address(address):
            return {"success": False, "error": f"Invalid address: {address}"}
        result = self._check_address({"address": address})
        return {
            "success": True,
            "read_only": True,
            "balance": result.get("balance", {}),
            "address": address,
        }

    def get_transaction_history(self, address: str) -> dict:
        """
        Get transaction history for an address (read-only).

        Args:
            address: Wallet address

        Returns:
            Transaction history dictionary
        """
        if not self._validate_address(address):
            return {"success": False, "error": f"Invalid address: {address}"}
        transfers = self._get_recent_transfers(address)
        return {
            "success": True,
            "read_only": True,
            "transactions": transfers,
            "address": address,
        }

    def sign_transaction(self) -> dict:
        """
        Agent NEVER signs transactions.

        Returns:
            Error response - signing is always blocked
        """
        logger.critical("SECURITY: sign_transaction() called - always blocked")
        return {"success": False, "error": "Agent cannot sign transactions. Manual signing required."}

    def stake(self) -> dict:
        """
        Agent NEVER auto-stakes.

        Returns:
            Error response - staking is always blocked
        """
        logger.critical("SECURITY: stake() called - always blocked")
        return {"success": False, "error": "Auto-staking is not allowed."}

    def trade(self) -> dict:
        """
        Agent NEVER auto-trades.

        Returns:
            Error response - trading is always blocked
        """
        logger.critical("SECURITY: trade() called - always blocked")
        return {"success": False, "error": "Auto-trading is not allowed."}

    @staticmethod
    def _is_valid_ss58(address: str) -> bool:
        """
        Validate a Bittensor SS58 address format.

        Args:
            address: Address string to validate

        Returns:
            True if valid SS58 format
        """
        if not address or not isinstance(address, str):
            return False
        return address.startswith("5") and len(address) == 48

    def run(self, task: dict) -> dict:
        """
        Run wallet watch task.

        Args:
            task: Dictionary with 'params' containing:
                - action: "watch", "unwatch", "check", "snapshot", or "prepare_signing_checklist"
                - address: Wallet address (for watch/unwatch/check)
                - label: Optional label for the address

        Returns:
            Wallet watch report or portfolio snapshot
        """
        self._status = "running"
        # Support both nested ``params`` and flat task-level keys. If the
        # caller passed any of action/address/label at the top level and
        # didn't nest them, promote them so the rest of run() doesn't care.
        params = dict(task.get("params") or {})
        for key in ("action", "address", "label"):
            if key in task and key not in params:
                params[key] = task[key]
        action = params.get("action", "snapshot")
        address = params.get("address", "")

        # Auto-watch: if the caller asked for a snapshot/check and supplied
        # an address that we don't yet track, register it first so the
        # operation has something to look at instead of returning balance=0.
        if address and action in ("snapshot", "check") and address not in self._watched:
            if self._validate_address(address):
                self._add_watch({
                    "address": address,
                    "label": params.get("label", ""),
                })

        logger.info("WalletWatchAgent: action=%s", action)

        try:
            if action == "watch":
                result = self._add_watch(params)
                result["success"] = result["status"] in ("added", "already_watched")
            elif action == "unwatch":
                result = self._remove_watch(params)
                result["success"] = result["status"] == "removed"
            elif action == "check":
                result = self._check_address(params)
                result["success"] = True
            elif action == "snapshot":
                result = self._portfolio_snapshot()
                result["success"] = result["status"] != "error"
            elif action == "prepare_signing_checklist":
                result = self._prepare_signing_checklist(params)
            else:
                result = {
                    "status": "error",
                    "success": False,
                    "error": f"Unknown action: {action}",
                }

            self._status = "complete"
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("WalletWatchAgent: failed: %s", e)
            raise

    def get_status(self) -> dict:
        """
        Get current agent status.

        Returns:
            Status dictionary
        """
        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "status": self._status,
            "wallets_tracked": len(self._watched),
            "mode": "WATCH_ONLY",
        }

    def validate_input(self, task: dict) -> tuple[bool, str]:
        """
        Validate task input.

        Args:
            task: Task dictionary to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(task, dict) or not task:
            return False, "Task must be a non-empty dictionary"

        # Support both direct action and params.action
        params = task.get("params", {})
        if "action" in task and not params:
            params = task
        action = params.get("action", "snapshot")

        valid_actions = ["watch", "unwatch", "check", "snapshot", "prepare_signing_checklist", "read"]
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"

        # Security check: reject any task with sensitive keywords
        task_str = str(task).lower()
        forbidden_keywords = [
            "seed", "mnemonic", "private_key", "password",
            "secret", "keyfile", "decrypt", "unlock",
        ]
        for kw in forbidden_keywords:
            if kw in task_str:
                logger.critical(
                    "SECURITY: WalletWatchAgent received forbidden keyword: %s", kw
                )
                return False, f"Security violation: forbidden keyword '{kw}' in task"

        # Check address for watch/check actions
        if action in ("watch", "check"):
            address = params.get("address", "")
            if not address:
                return False, "address is required for watch/check actions"
            if not self._validate_address(address):
                return False, f"Invalid address format: {address}"

        return True, ""

    def _add_watch(self, params: dict) -> dict:
        """
        Add an address to the watch list.

        Args:
            params: Parameters with 'address' and optional 'label'

        Returns:
            Result dictionary
        """
        address = params.get("address", "")
        label = params.get("label", "")

        if address in self._watched:
            return {
                "status": "already_watched",
                "address": address,
                "label": self._watched[address].get("label", ""),
            }

        self._watched[address] = {
            "added_at": time.time(),
            "label": label,
            "last_check": None,
        }
        if label:
            self._labels[address] = label

        logger.info("Added watch for address: %s (label=%s)", address, label)
        return {
            "status": "added",
            "address": address,
            "label": label,
            "total_watched": len(self._watched),
        }

    def _remove_watch(self, params: dict) -> dict:
        """
        Remove an address from the watch list.

        Args:
            params: Parameters with 'address'

        Returns:
            Result dictionary
        """
        address = params.get("address", "")

        if address not in self._watched:
            return {
                "status": "not_found",
                "address": address,
            }

        del self._watched[address]
        if address in self._labels:
            del self._labels[address]

        logger.info("Removed watch for address: %s", address)
        return {
            "status": "removed",
            "address": address,
            "total_watched": len(self._watched),
        }

    def _check_address(self, params: dict) -> dict:
        """
        Check balance and status for a single address.

        Args:
            params: Parameters with 'address'

        Returns:
            Address status dictionary
        """
        address = params.get("address", "")

        if self._use_mock:
            balance_data = self._get_mock_balance(address)
        else:
            balance_data = self._fetch_real_balance(address)

        # Update last check time
        if address in self._watched:
            self._watched[address]["last_check"] = time.time()

        return {
            "status": "checked",
            "address": address,
            "label": self._labels.get(address, ""),
            "balance": balance_data,
            "staking": self._get_staking_info(address),
            "recent_transfers": self._get_recent_transfers(address),
            "checked_at": time.time(),
        }

    def _portfolio_snapshot(self) -> dict:
        """
        Get a complete portfolio snapshot of all watched addresses.

        Returns:
            Portfolio snapshot dictionary
        """
        if not self._watched:
            return {
                "status": "empty",
                "message": "No wallets being watched. Add addresses first.",
                "addresses": [],
                "total_balance_tao": 0,
            }

        addresses: list[dict] = []
        total_balance = 0.0
        total_staked = 0.0

        for address, meta in self._watched.items():
            if self._use_mock:
                balance = self._get_mock_balance(address)
            else:
                balance = self._fetch_real_balance(address)

            staking = self._get_staking_info(address)
            balance_val = balance.get("balance_tao", 0)
            staked_val = staking.get("total_staked", 0)
            total_balance += balance_val
            total_staked += staked_val

            addresses.append({
                "address": address,
                "label": meta.get("label", self._labels.get(address, "")),
                "balance_tao": balance_val,
                "staked_tao": staked_val,
                "total_tao": balance_val + staked_val,
            })

        return {
            "status": "snapshot",
            "address_count": len(addresses),
            "addresses": addresses,
            "total_balance_tao": round(total_balance, 4),
            "total_staked_tao": round(total_staked, 4),
            "total_portfolio_tao": round(total_balance + total_staked, 4),
            "timestamp": time.time(),
        }

    def _validate_address(self, address: str) -> bool:
        """
        Validate a Bittensor address format.

        Bittensor addresses start with '5' and are 48 characters
        in SS58 format.

        Args:
            address: Address string to validate

        Returns:
            True if valid format
        """
        if not address or not isinstance(address, str):
            return False
        # SS58 address format: starts with 5, 48 chars
        return address.startswith("5") and len(address) == 48

    def _get_mock_balance(self, address: str) -> dict:
        """
        Generate deterministic mock balance for testing.

        Args:
            address: Wallet address

        Returns:
            Mock balance data
        """
        # Deterministic mock based on address characters
        import hashlib
        h = hashlib.sha256(address.encode()).hexdigest()
        balance = round(int(h[:8], 16) / 1e8, 4)
        return {
            "balance_tao": balance,
            "balance_rao": int(balance * 1e9),
            "source": "mock",
        }

    def _fetch_real_balance(self, address: str) -> dict:
        """
        Fetch real balance from the Bittensor chain.

        Args:
            address: Wallet address

        Returns:
            Balance data
        """
        try:
            import bittensor as bt
            subtensor = bt.subtensor()
            balance = subtensor.get_balance(address)
            return {
                "balance_tao": float(balance),
                "balance_rao": int(float(balance) * 1e9),
                "source": "chain",
            }
        except ImportError:
            logger.warning("bittensor not installed, falling back to mock")
            return self._get_mock_balance(address)
        except Exception as e:
            logger.error("Failed to fetch balance: %s", e)
            return self._get_mock_balance(address)

    def _get_staking_info(self, address: str) -> dict:
        """
        Get staking information for an address.

        Args:
            address: Wallet address

        Returns:
            Staking info dictionary
        """
        if self._use_mock:
            import hashlib
            h = hashlib.sha256((address + "stake").encode()).hexdigest()
            staked = round(int(h[:6], 16) / 1e7, 4)
            return {
                "total_staked": staked,
                "delegations": [
                    {
                        "hotkey": f"5{h[:47]}",
                        "amount": round(staked * 0.6, 4),
                    },
                    {
                        "hotkey": f"5{h[8:55]}",
                        "amount": round(staked * 0.4, 4),
                    },
                ],
                "source": "mock",
            }

        try:
            import bittensor as bt
            subtensor = bt.subtensor()
            # Get stake info from chain
            stake = subtensor.get_total_stake_for_coldkey(address)
            return {
                "total_staked": float(stake),
                "delegations": [],
                "source": "chain",
            }
        except Exception as e:
            logger.error("Failed to fetch staking info: %s", e)
            return {"total_staked": 0, "delegations": [], "source": "error"}

    def _get_recent_transfers(self, address: str) -> list[dict]:
        """
        Get recent transfer history for an address.

        Args:
            address: Wallet address

        Returns:
            List of recent transfer records
        """
        if self._use_mock:
            import hashlib
            h = hashlib.sha256((address + "tx").encode()).hexdigest()
            transfers = []
            for i in range(3):
                tx_hash = hashlib.sha256(f"{address}{i}".encode()).hexdigest()
                amount = round(int(h[i * 8:i * 8 + 6], 16) / 1e8, 4)
                transfers.append({
                    "tx_hash": f"0x{tx_hash[:64]}",
                    "amount_tao": amount,
                    "direction": "in" if i % 2 == 0 else "out",
                    "timestamp": time.time() - (i * 86400),
                })
            return transfers

        # Real chain query would go here
        return []

    def _prepare_signing_checklist(self, params: dict) -> dict:
        """
        Prepare a manual signing checklist for a transaction.

        Args:
            params: Parameters with 'transaction' containing to/amount

        Returns:
            Checklist dictionary
        """
        transaction = params.get("transaction", {})
        checklist = [
            "1. Review the recipient address carefully",
            "2. Verify the transaction amount",
            "3. Ensure your coldkey is secure and accessible",
            "4. Check network fees before signing",
            "5. Confirm the transaction on a hardware wallet if available",
        ]
        return {
            "status": "checklist",
            "success": True,
            "checklist": checklist,
            "transaction": transaction,
            "warning": (
                "WARNING: This agent NEVER has access to your private key or seed phrase. "
                "All signing must be done manually through the bittensor CLI or your wallet."
            ),
        }
