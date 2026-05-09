"""
Chain Read-Only Collector for Bittensor/TAO.

Provides read-only access to Bittensor chain data via SQLite cache.
All operations are non-destructive; no writes to the actual chain.
"""

import json
import logging
import os
import sqlite3
import time
from typing import Any, Optional

from src.collectors._base import BaseCollector

logger = logging.getLogger(__name__)


def _try_import_bittensor() -> Any:
    """
    Lazily import the optional ``bittensor`` SDK.

    Returns the module or ``None`` if the dep isn't installed. We
    swallow ImportError silently here — the caller decides whether
    that's a fall-back-to-mock condition or a hard error.
    """
    try:
        import bittensor as bt  # type: ignore[import-not-found]
    except ImportError:
        return None
    return bt

# Mock subnet data for offline / development mode
_MOCK_SUBNETS = [
    {
        "netuid": 1,
        "name": "Root",
        "owner": "5F3sa2TJAEqDhV...",
        "block": 1234567,
        "tempo": 360,
        "immunity_period": 7200,
        "min_allowed_weights": 8,
        "max_weights_limit": 420,
        "num_neurons": 256,
        "max_neurons": 1024,
        "emission": 18.45,
    },
    {
        "netuid": 2,
        "name": "text-prompting",
        "owner": "5GrwvaEF5zXb26F...",
        "block": 1234500,
        "tempo": 360,
        "immunity_period": 7200,
        "min_allowed_weights": 5,
        "max_weights_limit": 420,
        "num_neurons": 128,
        "max_neurons": 512,
        "emission": 12.30,
    },
    {
        "netuid": 3,
        "name": "translate",
        "owner": "5FHneW46xGXgs5m...",
        "block": 1234480,
        "tempo": 360,
        "immunity_period": 7200,
        "min_allowed_weights": 4,
        "max_weights_limit": 420,
        "num_neurons": 64,
        "max_neurons": 256,
        "emission": 8.75,
    },
    {
        "netuid": 4,
        "name": "llm-defender",
        "owner": "5DAAnrj7VHTznn2...",
        "block": 1234400,
        "tempo": 360,
        "immunity_period": 7200,
        "min_allowed_weights": 3,
        "max_weights_limit": 420,
        "num_neurons": 96,
        "max_neurons": 384,
        "emission": 6.20,
    },
    {
        "netuid": 5,
        "name": "open-knowledge",
        "owner": "5HGjWAeFDfFCW69...",
        "block": 1234300,
        "tempo": 360,
        "immunity_period": 7200,
        "min_allowed_weights": 6,
        "max_weights_limit": 420,
        "num_neurons": 160,
        "max_neurons": 640,
        "emission": 9.15,
    },
    {
        "netuid": 6,
        "name": "nova-asr",
        "owner": "5GNJqTPyNqANBkU...",
        "block": 1234200,
        "tempo": 360,
        "immunity_period": 7200,
        "min_allowed_weights": 3,
        "max_weights_limit": 420,
        "num_neurons": 48,
        "max_neurons": 192,
        "emission": 3.80,
    },
    {
        "netuid": 7,
        "name": "storage",
        "owner": "5HpG9f8tXk9Hb...",
        "block": 1234100,
        "tempo": 360,
        "immunity_period": 7200,
        "min_allowed_weights": 4,
        "max_weights_limit": 420,
        "num_neurons": 72,
        "max_neurons": 288,
        "emission": 5.50,
    },
    {
        "netuid": 8,
        "name": "time-series",
        "owner": "5FLSigC9HGRKVhB...",
        "block": 1234000,
        "tempo": 360,
        "immunity_period": 7200,
        "min_allowed_weights": 3,
        "max_weights_limit": 420,
        "num_neurons": 56,
        "max_neurons": 224,
        "emission": 4.25,
    },
]


class ChainReadOnlyCollector(BaseCollector):
    """
    Read-only collector for Bittensor chain data.

    Fetches subnet, neuron, emission and metagraph data. Results are
    cached in a local SQLite database. No write operations are ever
    performed on the actual chain.

    Mock vs live is chosen via ``use_mock_data`` (the swarm-wide
    convention). When ``use_mock_data=False`` the collector lazily
    imports the optional ``bittensor`` SDK and connects to the
    network specified by ``network`` (``"finney"`` for mainnet,
    ``"test"`` for testnet). If the SDK isn't installed, the
    collector falls back to mock mode and tags the payload's
    ``_meta.fallback_reason`` so callers know.
    """

    SOURCE_NAME = "chain_readonly"

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the chain collector.

        Args:
            config: Configuration dictionary with keys:
                - 'use_mock_data': bool — force mock data (default True)
                - 'network': 'finney' | 'test' | 'mock' (default 'mock')
                - 'db_path': Path to SQLite cache database
                - 'cache_ttl': Cache time-to-live in seconds (default 300)
        """
        config = config or {}
        super().__init__(config)
        self.config = config
        self.network = config.get("network", "mock")
        # If the caller passed network='mock' explicitly, treat that as
        # an opt-in to mock data even when use_mock_data wasn't set.
        if self.network == "mock":
            self.use_mock_data = True

        # Namespace the cache file by network so mock fixtures and live
        # chain data can never share a row. Without this, a `--mock` run
        # poisons the cache for a subsequent `--live` run (and vice
        # versa) because the cache key is just `netuid`.
        configured_path = config.get("db_path", "data/chain_cache.db")
        self.db_path = self._namespace_db_path(configured_path, self.network)

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self._subtensor: Any = None  # lazily-loaded bittensor.subtensor
        logger.info(
            "ChainReadOnlyCollector initialized (network=%s, use_mock_data=%s, db=%s)",
            self.network, self.use_mock_data, os.path.basename(self.db_path),
        )

    @staticmethod
    def _namespace_db_path(path: str, network: str) -> str:
        """
        Insert ``.<network>`` before the file extension.

        ``data/chain_cache.db`` + ``finney`` → ``data/chain_cache.finney.db``

        If the configured path already contains ``.<network>`` we leave
        it alone so callers that explicitly pre-namespaced the path
        don't end up with double-namespacing.
        """
        if not network:
            return path
        base, ext = os.path.splitext(path)
        suffix = f".{network}"
        if base.endswith(suffix):
            return path
        return f"{base}{suffix}{ext}"

    # ── Database ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create SQLite cache tables if they do not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subnet_cache (
                    netuid INTEGER PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS miner_cache (
                    uid INTEGER PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS validator_cache (
                    uid INTEGER PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emission_cache (
                    netuid INTEGER PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metagraph_cache (
                    netuid INTEGER PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.commit()

    def _cache_get(self, table: str, key_col: str, key_val: int) -> Optional[dict]:
        """Retrieve cached data if it has not expired."""
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

    def _cache_set(self, table: str, key_col: str, key_val: int, data: dict) -> None:
        """Store data in the local cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {table} ({key_col}, data, cached_at)
                    VALUES (?, ?, ?)""",
                (key_val, json.dumps(data, default=str), time.time()),
            )
            conn.commit()

    # ── Subnet API ────────────────────────────────────────────────────────

    def get_subnet_list(self) -> list:
        """
        Return a list of all subnets.

        Returns:
            List of subnet dictionaries with keys: netuid, name, owner,
            block, tempo, immunity_period, etc.
        """
        cached = self._cache_get("subnet_cache", "netuid", -1)
        if cached and "subnets" in cached:
            logger.debug("Returning cached subnet list")
            return cached["subnets"]

        bt = _try_import_bittensor()
        mode = self._resolve_mode(
            live_available=bt is not None,
            reason_when_unavailable=(
                "bittensor SDK not installed; install via "
                "`pip install bittensor` to enable live chain reads"
            ),
        )

        if mode == "mock":
            subnets = [dict(s) for s in _MOCK_SUBNETS]
        else:
            subnets = self._live_subnet_list(bt)

        self._cache_set("subnet_cache", "netuid", -1, {"subnets": subnets})
        logger.info("Fetched %d subnets (mode=%s)", len(subnets), mode)
        return subnets

    def _live_subnet_list(self, bt: Any) -> list:
        """
        Pull subnet identifiers from the live chain via bittensor SDK.

        Uses *only* read methods on ``bt.subtensor``; this collector
        never instantiates a wallet or signs anything. If a network
        error occurs, propagate the exception — the caller (CLI / agent)
        is expected to catch it and fall back gracefully rather than
        silently masking real chain issues as fake data.
        """
        sub = self._get_subtensor(bt)
        # Different SDK versions expose this differently; try the most
        # stable read first and fall through to a simpler one.
        netuids: list[int]
        if hasattr(sub, "get_subnets"):
            netuids = list(sub.get_subnets())
        elif hasattr(sub, "get_all_subnet_netuids"):
            netuids = list(sub.get_all_subnet_netuids())
        else:
            raise RuntimeError(
                "bittensor.subtensor exposes neither get_subnets() nor "
                "get_all_subnet_netuids() — incompatible SDK version"
            )
        return [{"netuid": int(n), "name": f"subnet_{int(n)}"} for n in netuids]

    def _get_subtensor(self, bt: Any) -> Any:
        """Return a cached, read-only subtensor for the configured network."""
        if self._subtensor is None:
            self._subtensor = bt.subtensor(network=self.network)
        return self._subtensor

    def get_subnet_info(self, netuid: int) -> dict:
        """
        Return detailed information for a specific subnet.

        Args:
            netuid: The unique subnet identifier.

        Returns:
            Dictionary with subnet details or an error dict if not found.
        """
        cached = self._cache_get("subnet_cache", "netuid", netuid)
        if cached:
            return cached

        subnets = self.get_subnet_list()
        for s in subnets:
            if s["netuid"] == netuid:
                result = dict(s)
                # Enrich with mock additional fields
                result["recycle_register"] = 0.1 * netuid
                result["burn_cost"] = 0.05 * netuid
                result["subnet_version"] = 1
                result["created_at_block"] = s["block"] - 10000
                self._cache_set("subnet_cache", "netuid", netuid, result)
                return result

        logger.warning("Subnet netuid=%d not found", netuid)
        return {"error": f"Subnet {netuid} not found", "netuid": netuid}

    # ── Miner API ─────────────────────────────────────────────────────────

    def get_miner_info(self, netuid: int, uid: int) -> dict:
        """
        Return information about a specific miner neuron.

        Args:
            netuid: Subnet identifier.
            uid: Neuron unique id within the subnet.

        Returns:
            Dictionary with miner details (stake, rank, emission, etc.).
        """
        cached = self._cache_get("miner_cache", "uid", uid * 10000 + netuid)
        if cached:
            return cached

        # Mock data generation deterministic by uid/netuid
        import hashlib
        h = hashlib.sha256(f"{netuid}:{uid}".encode()).hexdigest()

        result = {
            "netuid": netuid,
            "uid": uid,
            "hotkey": f"5{h[:45]}",
            "coldkey": f"5{h[16:61]}",
            "stake": round(float(int(h[:8], 16)) / 1e8, 4),
            "rank": round(float(int(h[8:16], 16)) / 1e8, 4),
            "emission": round(float(int(h[16:24], 16)) / 1e10, 8),
            "trust": round(float(int(h[24:32], 16)) / 1e8, 4),
            "consensus": round(float(int(h[32:40], 16)) / 1e8, 4),
            "incentive": round(float(int(h[40:48], 16)) / 1e8, 4),
            "dividends": round(float(int(h[48:56], 16)) / 1e8, 4),
            "is_active": True,
            "last_update": int(time.time()) - (uid * 60),
            "axon_ip": f"10.0.{(uid % 256)}.{(netuid % 256)}",
            "axon_port": 8091 + uid,
        }
        self._cache_set(
            "miner_cache", "uid", uid * 10000 + netuid, result
        )
        return result

    # ── Validator API ─────────────────────────────────────────────────────

    def get_validator_info(self, netuid: int, uid: int) -> dict:
        """
        Return information about a specific validator neuron.

        Args:
            netuid: Subnet identifier.
            uid: Neuron unique id within the subnet.

        Returns:
            Dictionary with validator details.
        """
        cached = self._cache_get("validator_cache", "uid", uid * 10000 + netuid)
        if cached:
            return cached

        import hashlib
        h = hashlib.sha256(f"validator:{netuid}:{uid}".encode()).hexdigest()

        result = {
            "netuid": netuid,
            "uid": uid,
            "hotkey": f"5{h[:45]}",
            "coldkey": f"5{h[16:61]}",
            "stake": round(float(int(h[:8], 16)) / 1e7, 4),
            "validator_permit": True,
            "validator_trust": round(float(int(h[8:16], 16)) / 1e8, 4),
            "weights": [round(float(int(h[i:i+4], 16)) / 65535, 4) for i in range(16, 48, 4)],
            "dividends": round(float(int(h[48:56], 16)) / 1e8, 4),
            "emission": round(float(int(h[56:64], 16)) / 1e10, 8),
            "is_active": True,
            "last_update": int(time.time()) - (uid * 30),
            "apy_estimate": round(5.0 + (float(int(h[:4], 16)) % 2500) / 100, 2),
        }
        self._cache_set(
            "validator_cache", "uid", uid * 10000 + netuid, result
        )
        return result

    # ── Emissions ─────────────────────────────────────────────────────────

    def get_emissions(self, netuid: int) -> dict:
        """
        Return emission data for a subnet.

        Args:
            netuid: Subnet identifier.

        Returns:
            Dictionary with total emission, per-neuron breakdown, etc.
        """
        cached = self._cache_get("emission_cache", "netuid", netuid)
        if cached:
            return cached

        subnet = self.get_subnet_info(netuid)
        if "error" in subnet:
            return subnet

        total_emission = subnet.get("emission", 0.0)
        num_neurons = subnet.get("num_neurons", 0)

        import hashlib
        h = hashlib.sha256(f"emissions:{netuid}".encode()).hexdigest()

        per_neuron = []
        for i in range(min(num_neurons, 20)):  # Limit to top 20
            share = (float(int(h[i*4:(i+1)*4], 16)) / 65535.0) if i < len(h)//4 - 1 else 0.01
            per_neuron.append({
                "uid": i,
                "emission": round(total_emission * share, 6),
                "share_pct": round(share * 100, 2),
            })

        result = {
            "netuid": netuid,
            "total_emission": total_emission,
            "block": subnet.get("block", 0),
            "num_neurons": num_neurons,
            "per_neuron": sorted(per_neuron, key=lambda x: x["emission"], reverse=True),
            "timestamp": int(time.time()),
        }
        self._cache_set("emission_cache", "netuid", netuid, result)
        return result

    # ── Metagraph ─────────────────────────────────────────────────────────

    def get_metagraph(self, netuid: int) -> dict:
        """
        Return a simplified metagraph for a subnet.

        Args:
            netuid: Subnet identifier.

        Returns:
            Dictionary with neuron list and aggregate statistics.
        """
        cached = self._cache_get("metagraph_cache", "netuid", netuid)
        if cached:
            return cached

        subnet = self.get_subnet_info(netuid)
        if "error" in subnet:
            return subnet

        num_neurons = subnet.get("num_neurons", 0)
        neurons = []
        for uid in range(min(num_neurons, 50)):  # Top 50 for cache efficiency
            if uid % 5 == 0:  # Every 5th is a validator mock
                info = self.get_validator_info(netuid, uid)
                info["neuron_type"] = "validator"
            else:
                info = self.get_miner_info(netuid, uid)
                info["neuron_type"] = "miner"
            neurons.append(info)

        total_stake = sum(n.get("stake", 0) for n in neurons)
        total_emission = sum(n.get("emission", 0) for n in neurons)

        result = {
            "netuid": netuid,
            "block": subnet.get("block", 0),
            "num_neurons": num_neurons,
            "neurons_sampled": len(neurons),
            "neurons": neurons,
            "aggregate": {
                "total_stake": round(total_stake, 4),
                "total_emission": round(total_emission, 8),
                "avg_stake": round(total_stake / max(len(neurons), 1), 4),
                "avg_emission": round(total_emission / max(len(neurons), 1), 8),
            },
            "timestamp": int(time.time()),
        }
        self._cache_set("metagraph_cache", "netuid", netuid, result)
        return result
