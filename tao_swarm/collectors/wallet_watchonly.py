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
from typing import Any

import requests

from tao_swarm.collectors._base import BaseCollector

logger = logging.getLogger(__name__)

# Subscan API public endpoints (no key needed for basic queries —
# free tier has rate limits, an API key removes them).
# Docs: https://support.subscan.io/#api-references
SUBSCAN_API_BASE = "https://bittensor.api.subscan.io/api"

# Subscan returns balances as integer plancks (10^9 = 1 TAO).
# https://docs.bittensor.com/getting-started/Bittensor%20decimals
_PLANCK_PER_TAO = 10 ** 9

# SS58 prefix for Bittensor
SS58_PREFIX = 42

# Default Subscan request timeout. Subscan's public node can be slow
# under load; 15s is a reasonable upper bound for a single read.
_SUBSCAN_TIMEOUT_S = 15.0


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
        # Subscan API key. Order: explicit config → SUBSCAN_API_KEY env
        # → empty string. The public endpoints work without a key but
        # are rate-limited; supplying one (free signup at subscan.io)
        # removes the per-IP quota.
        self.api_key = config.get(
            "subscan_api_key",
            os.environ.get("SUBSCAN_API_KEY", ""),
        )
        # Allow the test suite (and operators with a private node) to
        # override the Subscan base URL. Default points at the public
        # endpoint — opt-in only via use_mock_data=False.
        self.subscan_base = config.get("subscan_api_base", SUBSCAN_API_BASE)
        # HTTP timeout for live Subscan calls. Inherited from BaseCollector
        # via config["timeout"] but kept as a separate field so the live
        # path doesn't accidentally pick up a sub-second test value.
        self._subscan_timeout_s: float = float(
            config.get("subscan_timeout_s", _SUBSCAN_TIMEOUT_S),
        )

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        logger.info(
            "WalletWatchOnlyCollector initialized (watch-only, use_mock_data=%s, "
            "subscan_key_set=%s)",
            self.use_mock_data, bool(self.api_key),
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

    def _cache_get(self, table: str, key_col: str, key_val: str) -> dict | None:
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
        Validate a Bittensor SS58 address (prefix 42).

        Strategy (in order, first one that works wins):

        1. ``scalecodec.utils.ss58.is_valid_ss58_address`` —
           transitively shipped with ``bittensor>=10``; the substrate-
           ecosystem reference implementation. This is the path we
           expect in any environment that has the SDK installed.
        2. ``substrateinterface.utils.ss58.is_valid_ss58_address`` —
           fallback if scalecodec isn't directly importable but
           substrateinterface is.
        3. ``base58`` + manual blake2b checksum — last-resort fallback
           for ultra-minimal installs. The previous in-repo
           implementation got the prefix-decode wrong for prefix 42
           and rejected genuine addresses, which is why we now prefer
           a vetted library.

        Args:
            address: The SS58 address string to validate.

        Returns:
            True if the address is a valid SS58 address (prefix 42),
            False otherwise.
        """
        if not address or not isinstance(address, str):
            return False
        # Cheap structural reject before doing any decoding work.
        if not re.match(r"^5[a-zA-Z0-9]{47}$", address):
            return False

        try:
            from scalecodec.utils.ss58 import (
                is_valid_ss58_address,  # type: ignore[import-not-found]
            )
            return bool(is_valid_ss58_address(address, valid_ss58_format=SS58_PREFIX))
        except ImportError:
            pass
        try:
            from substrateinterface.utils.ss58 import (
                is_valid_ss58_address,  # type: ignore[import-not-found]
            )
            return bool(is_valid_ss58_address(address, valid_ss58_format=SS58_PREFIX))
        except ImportError:
            pass

        # Manual fallback (kept correct for the common single-byte prefix).
        try:
            import hashlib

            import base58

            decoded = base58.b58decode(address)
            if len(decoded) != 35:
                return False
            # Bittensor prefix is 42 → fits in a single byte (< 64).
            if decoded[0] != SS58_PREFIX:
                return False
            check_data = b"SS58PRE" + decoded[:-2]
            checksum_full = hashlib.blake2b(check_data, digest_size=64).digest()
            return decoded[-2:] == checksum_full[:2]
        except ImportError:
            # Without base58 we can't checksum-verify. Be conservative
            # and accept the structural shape — the caller still hits
            # the chain for the authoritative answer.
            return True
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

        In live mode (``use_mock_data=False``), POSTs to Subscan's
        ``/api/scan/account`` endpoint with the SS58 key and parses the
        balance fields from the JSON response. The free / reserved
        values come back as integer plancks; we convert to TAO via
        ``_PLANCK_PER_TAO``. Falls back to the deterministic mock
        branch if the network call fails or live mode wasn't asked for.

        Args:
            address: SS58 address to query.

        Returns:
            Dictionary with free, reserved, and total balance in TAO,
            plus a ``_meta`` block tagging mock vs live and (on
            fall-back) the reason.
        """
        cached = self._cache_get("balance_cache", "address", address)
        if cached:
            return cached

        mode = self._resolve_mode(live_available=True)

        if mode == "live":
            try:
                live = self._subscan_account(address)
                if live is not None:
                    live["_meta"] = self._meta(mode)
                    self._cache_set("balance_cache", "address", address, live)
                    return live
                # Subscan responded but returned no usable data
                # (HTTP non-200, code != 0, or empty body). The
                # upstream call ran — we just don't trust the
                # answer. Tag the fallback with a reason so callers
                # can tell "live ran and gave nothing" apart from
                # "live wasn't requested".
                self._mock_fallback_reason = (
                    "Subscan returned no usable data "
                    "(HTTP non-200, code != 0, or address unknown)"
                )
                mode = "mock"
            except Exception as exc:
                logger.warning(
                    "Subscan balance lookup for %s failed: %s — "
                    "falling back to mock", address[:10], exc,
                )
                self._mock_fallback_reason = (
                    f"Subscan request failed: {type(exc).__name__}: {exc}"
                )
                mode = "mock"

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

    # ── Subscan client ────────────────────────────────────────────────────

    def _subscan_post(self, path: str, payload: dict) -> dict | None:
        """
        POST a JSON payload to the Subscan API.

        Returns the parsed ``data`` field on HTTP 200 + ``code == 0``
        (Subscan's success indicator). Returns ``None`` for any other
        outcome — caller treats that as "no live data" and falls back
        to mock. Network exceptions propagate so the caller can record
        the error in ``_mock_fallback_reason``.
        """
        url = f"{self.subscan_base}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        resp = requests.post(
            url, json=payload, headers=headers,
            timeout=self._subscan_timeout_s,
        )
        if resp.status_code != 200:
            logger.debug(
                "Subscan %s returned HTTP %s", path, resp.status_code,
            )
            return None
        try:
            body = resp.json()
        except ValueError:
            logger.debug("Subscan %s returned non-JSON body", path)
            return None
        # Subscan's API wraps successful responses as
        # {"code": 0, "data": {...}, "message": "Success"}.
        if body.get("code") != 0:
            logger.debug(
                "Subscan %s returned error code %s (%s)",
                path, body.get("code"), body.get("message"),
            )
            return None
        return body.get("data") or {}

    def _subscan_account(self, address: str) -> dict | None:
        """
        Fetch balance fields for ``address`` from
        ``/api/v2/scan/search`` (Subscan's account-detail endpoint).

        Returns a normalised balance dict ready for ``balance_cache``,
        or ``None`` if the address isn't found / Subscan returned an
        error response. Network errors propagate.
        """
        # Subscan v2 search returns the full account object. ``key`` can
        # be SS58 or a public hex key; we always send SS58.
        data = self._subscan_post("v2/scan/search", {"key": address})
        if not data:
            return None
        # The interesting fields live under ``data['account']`` for v2.
        account = data.get("account") or data
        free = self._planck_to_tao(account.get("balance", "0"))
        reserved = self._planck_to_tao(account.get("reserved", "0"))
        # Some v2 responses use ``balance_lock`` / ``frozen_balance``
        # for locked-but-not-reserved funds.
        frozen = self._planck_to_tao(
            account.get("balance_lock", account.get("frozen_balance", "0"))
        )
        misc_frozen = self._planck_to_tao(account.get("misc_frozen_balance", "0"))
        return {
            "address": address,
            "free": free,
            "reserved": reserved,
            "total": round(free + reserved, 6),
            "frozen": frozen,
            "misc_frozen": misc_frozen,
            "timestamp": int(time.time()),
        }

    @staticmethod
    def _planck_to_tao(value: Any) -> float:
        """Convert a Subscan-returned planck value (string or int) to
        TAO. Returns 0.0 for unparseable input rather than raising —
        partial responses shouldn't kill the whole balance fetch."""
        if value in (None, ""):
            return 0.0
        try:
            # Subscan returns these as decimal strings on v2.
            return round(float(value) / _PLANCK_PER_TAO, 6)
        except (TypeError, ValueError):
            return 0.0

    def _subscan_staking(self, address: str) -> dict | None:
        """
        Fetch staking / delegation rows for ``address`` from Subscan.

        Returns a normalised staking dict ready for ``staking_cache``,
        or ``None`` if the address has no staking history. Network
        errors propagate (caller logs + falls back to mock).
        """
        # Subscan endpoint: /api/scan/staking/list returns the user's
        # active delegations. Schema:
        #   {"data": {"list": [{"validator_id": SS58, "amount": planck,
        #                       "share_pct": float, "apy": float, ...}],
        #             "total": planck_total}}
        data = self._subscan_post(
            "scan/staking/list",
            {"address": address, "row": 100, "page": 0},
        )
        if not data:
            return None
        rows = data.get("list") or []
        delegations: list[dict] = []
        total_staked = 0.0
        for row in rows:
            amount_tao = self._planck_to_tao(row.get("amount", 0))
            total_staked += amount_tao
            delegations.append({
                "validator": row.get("validator_id") or row.get("stash") or "",
                "amount": amount_tao,
                "share_pct": float(row.get("share_pct", 0.0) or 0.0),
                "apy_estimate": float(row.get("apy", 0.0) or 0.0),
            })
        # Subscan's overall total may differ slightly from sum-of-rows
        # due to pending unstakes — prefer the explicit field if set.
        total_field = self._planck_to_tao(data.get("total", 0))
        if total_field > 0:
            total_staked = total_field
        # Free-form delegated balance (held outside active validator
        # set) — surfaced if Subscan provides it; otherwise 0.
        delegated = self._planck_to_tao(data.get("nominator_balance", 0))
        avg_apy = (
            sum(d["apy_estimate"] for d in delegations) / len(delegations)
            if delegations else 0.0
        )
        return {
            "address": address,
            "total_staked": round(total_staked, 6),
            "total_delegated": round(delegated, 6),
            "total": round(total_staked + delegated, 6),
            "num_delegations": len(delegations),
            "delegations": delegations,
            "estimated_apy_pct": round(avg_apy, 2),
            "timestamp": int(time.time()),
        }

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

        In live mode, queries Subscan's
        ``/api/scan/staking/account_staking_history`` endpoint for the
        active delegation list and rolls it up. Falls back to
        deterministic mock if the call fails or live wasn't requested.

        Args:
            address: SS58 address to query.

        Returns:
            Dictionary with staked amount, delegations, and APY estimates,
            plus a ``_meta`` block tagging mock vs live.
        """
        cached = self._cache_get("staking_cache", "address", address)
        if cached:
            return cached

        mode = self._resolve_mode(live_available=True)

        if mode == "live":
            try:
                live = self._subscan_staking(address)
                if live is not None:
                    live["_meta"] = self._meta(mode)
                    self._cache_set("staking_cache", "address", address, live)
                    return live
                # Subscan responded but with no usable staking data —
                # tag a reason so consumers can distinguish "live ran,
                # got nothing" from "live wasn't requested".
                self._mock_fallback_reason = (
                    "Subscan returned no usable staking data "
                    "(HTTP non-200, code != 0, or address unknown)"
                )
                mode = "mock"
            except Exception as exc:
                logger.warning(
                    "Subscan staking lookup for %s failed: %s — "
                    "falling back to mock", address[:10], exc,
                )
                self._mock_fallback_reason = (
                    f"Subscan request failed: {type(exc).__name__}: {exc}"
                )
                mode = "mock"

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
