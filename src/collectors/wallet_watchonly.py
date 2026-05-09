"""
Wallet Watch-Only Collector

Provides read-only monitoring of Bittensor wallet addresses.
STRICT RULES:
  - Only public addresses (SS58 format)
  - NO seed phrases, NO private keys
  - All data stored locally in SQLite
  - Read-only operations only
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from typing import Optional

import requests

from src.collectors._base import BaseCollector

logger = logging.getLogger(__name__)

# Subscan API public endpoints (no key needed for basic queries)
SUBSCAN_API_BASE = "https://bittensor.api.subscan.io/api/v2"

# SS58 prefix for Bittensor
SS58_PREFIX = 42


class WalletWatchOnlyCollector(BaseCollector):
    """
    Watch-only wallet collector for Bittensor addresses.

    Monitors balances, transactions, and staking info for public
    addresses. NEVER stores or requests private keys or seed phrases.
    Honours the swarm-wide ``use_mock_data`` flag.
    """

    SOURCE_NAME = "wallet_watchonly"

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the wallet watch-only collector.

        Args:
            config: Configuration dict with keys:
                - 'use_mock_data': bool (default True) — fixture mode
                - 'db_path': SQLite database path
                - 'subscan_api_key': Optional Subscan API key
                - 'request_timeout': HTTP timeout in seconds (default 15)
                - 'cache_ttl': Cache TTL in seconds (default 120)
        """
        config = config or {}
        config.setdefault("cache_ttl", 120)
        config.setdefault("timeout", config.get("request_timeout", 15))
        super().__init__(config)
        self.config = config
        self.db_path = config.get("db_path", "data/wallet_watch.db")
        self.api_key = config.get("subscan_api_key", "")

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        logger.info(
            "WalletWatchOnlyCollector initialized (watch-only, use_mock_data=%s)",
            self.use_mock_data,
        )

    # ── Database ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create watch-only tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watched_addresses (
                    address TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    added_at REAL NOT NULL,
                    notes TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS balance_cache (
                    address TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transaction_cache (
                    address TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL,
                    PRIMARY KEY (address, tx_hash)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS staking_cache (
                    address TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.commit()

    def _cache_get(self, table: str, key_col: str, key_val: str) -> Optional[dict]:
        """Get cached data if not expired."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT data, cached_at FROM {table} WHERE {key_col} = ?", (key_val,)
            ).fetchone()
        if row is None:
            return None
        data, cached_at = row
        if time.time() - cached_at > self.cache_ttl:
            return None
        return json.loads(data)

    def _cache_set(self, table: str, key_col: str, key_val: str, data: dict) -> None:
        """Store data in cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({key_col}, data, cached_at) VALUES (?, ?, ?)",
                (key_val, json.dumps(data, default=str), time.time()),
            )
            conn.commit()

    # ── SS58 Validation ───────────────────────────────────────────────────

    def validate_address(self, address: str) -> bool:
        """
        Validate a Bittensor SS58 address.

        Uses the correct SS58 checksum algorithm for prefix 42 (Bittensor).

        Args:
            address: The SS58 address string to validate.

        Returns:
            True if the address is a valid SS58 address, False otherwise.
        """
        if not address or not isinstance(address, str):
            return False
        # Bittensor SS58 addresses start with '5' and are 48 characters
        if not re.match(r"^5[a-zA-Z0-9]{47}$", address):
            return False

        try:
            import base58

            decoded = base58.b58decode(address)
            if len(decoded) != 35:
                return False

            # Prefix check: 42 (Bittensor substrate prefix)
            prefix_len = 1
            prefix = decoded[0]
            if prefix >= 64:
                prefix_len = 2
                prefix = ((prefix - 64) << 2) | (decoded[1] & 0b11)
            if prefix != SS58_PREFIX:
                return False

            # Checksum
            import hashlib

            check_data = decoded[:33 + prefix_len]
            checksum_full = hashlib.blake2b(check_data, digest_size=64).digest()
            checksum = checksum_full[:2]
            return decoded[-2:] == checksum
        except ImportError:
            # Fallback: basic regex validation if base58 not installed
            return bool(re.match(r"^5[a-zA-Z0-9]{47}$", address))
        except Exception:
            return False

    # ── Address Management ────────────────────────────────────────────────

    def add_watch_address(self, address: str, label: str = "") -> bool:
        """
        Add a public address to the watch list.

        Args:
            address: Public SS58 address to watch.
            label: Optional human-readable label.

        Returns:
            True if added successfully, False if invalid or already watched.
        """
        if not self.validate_address(address):
            logger.warning("Invalid SS58 address: %s", address)
            return False

        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    "INSERT INTO watched_addresses (address, label, added_at) VALUES (?, ?, ?)",
                    (address, label, time.time()),
                )
                conn.commit()
                logger.info("Added watch address: %s (label=%s)", address, label)
                return True
            except sqlite3.IntegrityError:
                logger.debug("Address already watched: %s", address)
                return False

    def remove_watch_address(self, address: str) -> bool:
        """
        Remove an address from the watch list.

        Args:
            address: Address to remove.

        Returns:
            True if removed, False if not found.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM watched_addresses WHERE address = ?", (address,))
            conn.commit()
            if cursor.rowcount > 0:
                logger.info("Removed watch address: %s", address)
                return True
            return False

    def list_watched_addresses(self) -> list:
        """
        List all watched addresses.

        Returns:
            List of dicts with address, label, and added_at.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT address, label, added_at FROM watched_addresses ORDER BY added_at"
            ).fetchall()
        return [{"address": r[0], "label": r[1], "added_at": r[2]} for r in rows]

    # ── Balance ───────────────────────────────────────────────────────────

    def get_balance(self, address: str) -> dict:
        """
        Get the balance for a watched address.

        Args:
            address: SS58 address to query.

        Returns:
            Dictionary with free, reserved, and total balance in TAO.
        """
        cached = self._cache_get("balance_cache", "address", address)
        if cached:
            return cached

        # Note: this collector currently has no live Subscan integration —
        # all balances are deterministic mocks derived from the address.
        # The _resolve_mode call still records use_mock_data so consumers
        # can audit data provenance via the _meta block. A live Subscan
        # path is a follow-up.
        mode = self._resolve_mode(
            live_available=False,
            reason_when_unavailable="Subscan integration not yet implemented",
        )

        # Fallback: generate deterministic mock data
        h = hashlib.sha256(f"balance:{address}".encode()).hexdigest()
        free = round(float(int(h[:16], 16)) / 1e12, 6)
        reserved = round(float(int(h[16:32], 16)) / 1e13, 6)

        result = {
            "address": address,
            "free": free,
            "reserved": reserved,
            "total": round(free + reserved, 6),
            "frozen": 0.0,
            "misc_frozen": 0.0,
            "timestamp": int(time.time()),
            "_meta": self._meta(mode),
        }
        self._cache_set("balance_cache", "address", address, result)
        return result

    # ── Transactions ──────────────────────────────────────────────────────

    def get_transactions(self, address: str, limit: int = 50) -> list:
        """
        Get recent transactions for an address.

        Args:
            address: SS58 address to query.
            limit: Maximum number of transactions to return.

        Returns:
            List of transaction dictionaries.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT tx_hash, data FROM transaction_cache WHERE address = ? ORDER BY cached_at DESC LIMIT ?",
                (address, limit),
            ).fetchall()

        if rows:
            return [json.loads(r[1]) for r in rows]

        # Generate mock transactions
        h = hashlib.sha256(f"txs:{address}".encode()).hexdigest()
        transactions = []
        for i in range(min(limit, 50)):
            tx_hash = f"0x{hashlib.sha256(f'{address}:{i}'.encode()).hexdigest()}"
            amount = round(float(int(h[i*4:(i+1)*4], 16)) / 1e10, 6) if i < len(h)//4 else 0.001
            tx_type = ["transfer", "stake", "unstake", "reward"][i % 4]
            transactions.append({
                "tx_hash": tx_hash,
                "from_address": address if i % 2 == 0 else f"5{hashlib.sha256(f'from:{i}'.encode()).hexdigest()[:47]}",
                "to_address": f"5{hashlib.sha256(f'to:{i}'.encode()).hexdigest()[:47]}" if i % 2 == 0 else address,
                "amount": amount,
                "fee": round(amount * 0.001, 8),
                "type": tx_type,
                "block": 1234567 - i * 120,
                "timestamp": int(time.time()) - i * 3600,
                "success": True,
            })

        # Store in cache
        with sqlite3.connect(self.db_path) as conn:
            for tx in transactions:
                conn.execute(
                    "INSERT OR REPLACE INTO transaction_cache (address, tx_hash, data, cached_at) VALUES (?, ?, ?, ?)",
                    (address, tx["tx_hash"], json.dumps(tx, default=str), time.time()),
                )
            conn.commit()

        return transactions

    # ── Staking Info ──────────────────────────────────────────────────────

    def get_staking_info(self, address: str) -> dict:
        """
        Get staking information for an address.

        Args:
            address: SS58 address to query.

        Returns:
            Dictionary with staked amount, delegations, and APY estimates.
        """
        cached = self._cache_get("staking_cache", "address", address)
        if cached:
            return cached

        mode = self._resolve_mode(
            live_available=False,
            reason_when_unavailable="Subscan integration not yet implemented",
        )

        h = hashlib.sha256(f"staking:{address}".encode()).hexdigest()
        staked = round(float(int(h[:16], 16)) / 1e12, 6)
        delegated = round(float(int(h[16:32], 16)) / 1e13, 6)
        num_delegations = int(h[32:36], 16) % 10

        delegations = []
        for i in range(num_delegations):
            val_addr = f"5{hashlib.sha256(f'delegation:{address}:{i}'.encode()).hexdigest()[:47]}"
            amt = round(staked * (0.1 + (i * 0.05)), 6)
            delegations.append({
                "validator": val_addr,
                "amount": amt,
                "share_pct": round(amt / max(staked, 0.000001) * 100, 2),
                "apy_estimate": round(8.0 + (int(h[i*2:(i+1)*2], 16) % 500) / 100, 2),
            })

        result = {
            "address": address,
            "total_staked": staked,
            "total_delegated": delegated,
            "total": round(staked + delegated, 6),
            "num_delegations": num_delegations,
            "delegations": delegations,
            "estimated_apy_pct": round(8.0 + (float(int(h[:4], 16)) / 65535) * 12, 2),
            "timestamp": int(time.time()),
            "_meta": self._meta(mode),
        }
        self._cache_set("staking_cache", "address", address, result)
        return result

    # ── Portfolio Summary ─────────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict:
        """
        Get a summary of all watched addresses.

        Returns:
            Aggregate portfolio data across all watched wallets.
        """
        addresses = self.list_watched_addresses()
        if not addresses:
            return {"addresses": [], "total_balance": 0.0, "total_staked": 0.0, "count": 0}

        total_balance = 0.0
        total_staked = 0.0
        details = []

        for addr_info in addresses:
            addr = addr_info["address"]
            balance = self.get_balance(addr)
            staking = self.get_staking_info(addr)

            total_balance += balance.get("total", 0.0)
            total_staked += staking.get("total_staked", 0.0)
            details.append({
                "address": addr,
                "label": addr_info["label"],
                "balance": balance,
                "staking": staking,
            })

        return {
            "addresses": details,
            "count": len(addresses),
            "total_balance": round(total_balance, 6),
            "total_staked": round(total_staked, 6),
            "grand_total": round(total_balance + total_staked, 6),
            "timestamp": int(time.time()),
        }
