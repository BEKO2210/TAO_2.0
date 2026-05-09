"""
Chain Read-Only Collector for Bittensor/TAO.

Provides read-only access to Bittensor chain data via SQLite cache.
All operations are non-destructive; no writes to the actual chain.
"""

import contextlib
import json
import logging
import os
import sqlite3
import time
from typing import Any, Optional

from src.collectors._base import BaseCollector

logger = logging.getLogger(__name__)


# Fallback finney endpoints — used by SubtensorApi (v10+) when the
# primary websocket connection drops. Order matters: first one that
# answers wins. Public endpoints, no auth required.
_DEFAULT_FALLBACK_ENDPOINTS: tuple[str, ...] = (
    "wss://entrypoint-finney.opentensor.ai:443",
    "wss://lite.sub.latent.to:443",
)

# Write-side SDK methods this collector must NEVER call. Enforced by
# tests/test_chain_readonly_collector.py::test_no_write_methods_called.
# Keep in sync with bittensor SDK v10 surface.
_WRITE_METHODS_DENYLIST: frozenset[str] = frozenset({
    "add_stake", "unstake", "transfer", "set_weights",
    "commit_weights", "reveal_weights", "add_proxy", "remove_proxy",
    "move_stake", "register", "burned_register", "serve_axon",
    "do_transfer", "do_set_weights", "do_stake",
})


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
        # Allow callers to override the fallback endpoint list (e.g. for
        # private subtensor nodes or test networks). Default covers
        # the two stable public finney endpoints.
        self._fallback_endpoints: tuple[str, ...] = tuple(
            config.get("fallback_endpoints", _DEFAULT_FALLBACK_ENDPOINTS),
        )
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

        Uses *only* read methods on the subtensor; this collector
        never instantiates a wallet or signs anything (enforced by
        ``_WRITE_METHODS_DENYLIST`` + the corresponding test). If a
        network error occurs, propagate the exception — the caller
        (CLI / agent) is expected to catch it and fall back gracefully
        rather than silently masking real chain issues as fake data.
        """
        with self._with_subtensor(bt) as sub:
            netuids = self._call_subnets(sub)
        return [{"netuid": int(n), "name": f"subnet_{int(n)}"} for n in netuids]

    def _live_metagraph(self, bt: Any, netuid: int, lite: bool = True) -> dict:
        """
        Pull a real metagraph from the chain via the SDK.

        ``lite=True`` (default) skips the V×N weight and bond matrices
        — those are multi-MB on busy subnets and would dominate the
        dashboard hot path. Pass ``lite=False`` only from paths that
        explicitly need ``W`` / ``B`` (the weight-copy detector planned
        for PR B; subnet quality scoring in PR C).
        """
        with self._with_subtensor(bt) as sub:
            mg = self._call_metagraph(sub, netuid=netuid, lite=lite)

        # Translate the SDK's tensor-shaped attributes to plain Python
        # so SQLite caching + JSON serialisation work without dragging
        # numpy/torch into our hot path. Each attr may be tensor or
        # list depending on SDK version — _to_list handles both.
        neurons_lite = []
        uids = self._to_list(getattr(mg, "uids", []))
        stake = self._to_list(getattr(mg, "S", []))
        emission = self._to_list(getattr(mg, "E", []))
        trust = self._to_list(getattr(mg, "T", []))
        ranks = self._to_list(getattr(mg, "R", []))
        consensus = self._to_list(getattr(mg, "C", []))
        incentive = self._to_list(getattr(mg, "I", []))
        validator_permit = self._to_list(getattr(mg, "validator_permit", []))
        last_update = self._to_list(getattr(mg, "last_update", []))
        active = self._to_list(getattr(mg, "active", []))

        for i, uid in enumerate(uids):
            neurons_lite.append({
                "uid": int(uid),
                "stake": float(stake[i]) if i < len(stake) else 0.0,
                "emission": float(emission[i]) if i < len(emission) else 0.0,
                "trust": float(trust[i]) if i < len(trust) else 0.0,
                "rank": float(ranks[i]) if i < len(ranks) else 0.0,
                "consensus": float(consensus[i]) if i < len(consensus) else 0.0,
                "incentive": float(incentive[i]) if i < len(incentive) else 0.0,
                "validator_permit": bool(validator_permit[i]) if i < len(validator_permit) else False,
                "last_update_block": int(last_update[i]) if i < len(last_update) else 0,
                "active": bool(active[i]) if i < len(active) else True,
            })

        # Roll up validators vs miners for the dashboard summary.
        validators = [n for n in neurons_lite if n["validator_permit"]]
        miners = [n for n in neurons_lite if not n["validator_permit"]]
        total_stake = sum(n["stake"] for n in neurons_lite)
        total_emission = sum(n["emission"] for n in neurons_lite)

        return {
            "netuid": netuid,
            "block": int(getattr(mg, "block", 0)),
            "num_neurons": len(neurons_lite),
            "neurons_sampled": len(neurons_lite),
            "neurons": neurons_lite,
            "validator_count": len(validators),
            "miner_count": len(miners),
            "aggregate": {
                "total_stake": round(total_stake, 4),
                "total_emission": round(total_emission, 8),
                "avg_stake": round(total_stake / max(len(neurons_lite), 1), 4),
                "avg_emission": round(total_emission / max(len(neurons_lite), 1), 8),
            },
            "_meta": self._meta(mode="live", network=self.network, lite=lite),
            "timestamp": int(time.time()),
        }

    @staticmethod
    def _call_metagraph(sub: Any, netuid: int, lite: bool) -> Any:
        """SDK shim — v10 uses ``metagraph(netuid, lite=...)``; legacy
        SDKs used ``get_metagraph(netuid)`` without the lite kwarg."""
        for name in ("metagraph", "get_metagraph"):
            method = getattr(sub, name, None)
            if callable(method):
                try:
                    return method(netuid=netuid, lite=lite)
                except TypeError:
                    return method(netuid=netuid)
        raise RuntimeError(
            "bittensor subtensor exposes neither metagraph() nor "
            "get_metagraph() — incompatible SDK version"
        )

    @staticmethod
    def _to_list(maybe_tensor: Any) -> list:
        """Convert a torch/numpy tensor (or already-a-list) to a Python
        list. Avoids importing torch / numpy at the top of this module."""
        tolist = getattr(maybe_tensor, "tolist", None)
        if callable(tolist):
            try:
                return list(tolist())
            except Exception:
                pass
        try:
            return list(maybe_tensor)
        except TypeError:
            return []

    @staticmethod
    def _call_subnets(sub: Any) -> list[int]:
        """
        Try v10's ``get_all_subnets_netuid`` first, then fall through to
        legacy method names. Raises if no compatible reader is present
        — never silently returns an empty list (that would look like a
        successful read of zero subnets, which is meaningfully wrong).
        """
        for name in ("get_all_subnets_netuid", "get_subnets",
                     "get_all_subnet_netuids"):
            method = getattr(sub, name, None)
            if callable(method):
                return list(method())
        raise RuntimeError(
            "bittensor subtensor exposes none of "
            "get_all_subnets_netuid / get_subnets / get_all_subnet_netuids "
            "— incompatible SDK version"
        )

    def _get_subtensor(self, bt: Any) -> Any:
        """
        Return a (cached) read-only subtensor for the configured network.

        Kept for backward compatibility with the original sync helper
        signature. New code should prefer ``_with_subtensor`` so the
        WSS connection lifetime is bounded.
        """
        if self._subtensor is None:
            self._subtensor = self._build_subtensor(bt)
        return self._subtensor

    def _build_subtensor(self, bt: Any) -> Any:
        """
        Construct the right read-only subtensor for the installed SDK.

        Bittensor SDK v10+ exposes ``SubtensorApi`` — a unified wrapper
        with built-in fallback endpoints, retry, and the v9→v10 method
        rename. Older SDKs (and our test stubs) only have
        ``bt.subtensor``. We try the modern path first and fall through
        gracefully so this collector keeps working across the supported
        SDK range (8.x through 10.x).
        """
        if hasattr(bt, "SubtensorApi"):
            try:
                return bt.SubtensorApi(
                    network=self.network,
                    fallback_endpoints=list(self._fallback_endpoints),
                    retry_forever=False,
                    log_verbose=False,
                )
            except TypeError:
                # Older v10 betas had a different kwarg surface; fall
                # back to the no-arg path so we still get the wrapper's
                # benefits even if fallback_endpoints isn't supported.
                return bt.SubtensorApi(network=self.network)
        # Legacy <v10
        return bt.subtensor(network=self.network)

    @contextlib.contextmanager
    def _with_subtensor(self, bt: Any) -> Any:
        """
        Yield a fresh subtensor and close it on exit.

        Use this for any new live read path. Long-held WSS connections
        get reaped by the finney node after ~10s of idle, so the
        previous "cache the subtensor for the lifetime of the
        collector" pattern produced silent stale-socket failures.
        Per-batch open-then-close keeps us a good citizen on shared
        public endpoints and gives reconnect-on-drop semantics for
        free.
        """
        sub = self._build_subtensor(bt)
        try:
            yield sub
        finally:
            close = getattr(sub, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:  # pragma: no cover - close best-effort
                    logger.debug("subtensor close failed: %s", exc)

    def get_subnet_info(self, netuid: int) -> dict:
        """
        Return detailed information for a specific subnet.

        In live mode, enriches with real on-chain economic parameters
        from the SDK: ``recycle`` (TAO required to register a miner),
        ``subnet_burn_cost`` (TAO required to create a new subnet),
        and the full ``hyperparameters`` block (tempo, immunity, kappa,
        rho, weight thresholds, …). In mock mode, retains the original
        synthetic values so existing tests and offline runs keep
        working unchanged.

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
                bt = _try_import_bittensor()
                if not self.use_mock_data and bt is not None:
                    self._enrich_subnet_info_live(result, bt, netuid)
                else:
                    # Synthetic fallback — flagged so downstream
                    # consumers can tell mock from live.
                    result["recycle_register"] = 0.1 * netuid
                    result["burn_cost"] = 0.05 * netuid
                    result["subnet_version"] = 1
                    result["created_at_block"] = s.get("block", 0) - 10000
                    result["_meta"] = self._meta(mode="mock")
                self._cache_set("subnet_cache", "netuid", netuid, result)
                return result

        logger.warning("Subnet netuid=%d not found", netuid)
        return {"error": f"Subnet {netuid} not found", "netuid": netuid}

    def _enrich_subnet_info_live(self, result: dict, bt: Any, netuid: int) -> None:
        """
        Pull the real economic parameters from the SDK and stamp them
        onto ``result``. Each call is wrapped individually so a
        failure in one (e.g. ``recycle`` not yet supported on the
        installed SDK) doesn't kill the others.
        """
        with self._with_subtensor(bt) as sub:
            result["recycle_register"] = self._safe_float(
                self._try_call(sub, "recycle", netuid=netuid)
            )
            result["burn_cost"] = self._safe_float(
                self._try_call(sub, "get_subnet_burn_cost")
            )
            hyperparams = self._try_call(sub, "get_subnet_hyperparameters", netuid=netuid)
            if hyperparams is not None:
                # SDK returns a NamedTuple-style object — convert to dict.
                asdict = getattr(hyperparams, "_asdict", None)
                if callable(asdict):
                    result["hyperparameters"] = dict(asdict())
                elif hasattr(hyperparams, "__dict__"):
                    result["hyperparameters"] = dict(hyperparams.__dict__)
                else:
                    result["hyperparameters"] = {"raw": str(hyperparams)}
        result["_meta"] = self._meta(mode="live", network=self.network)

    @staticmethod
    def _try_call(sub: Any, method_name: str, **kwargs: Any) -> Any:
        """Best-effort call to an SDK method — returns ``None`` on
        AttributeError / Exception so the caller can degrade gracefully."""
        method = getattr(sub, method_name, None)
        if not callable(method):
            return None
        try:
            return method(**kwargs)
        except Exception as exc:  # pragma: no cover - SDK-side errors are noisy
            logger.debug("SDK %s(%s) failed: %s", method_name, kwargs, exc)
            return None

    @staticmethod
    def _safe_float(value: Any) -> float:
        """Convert SDK Balance / int / None to a plain float."""
        if value is None:
            return 0.0
        # bittensor Balance objects expose .tao (float)
        tao_attr = getattr(value, "tao", None)
        if tao_attr is not None:
            try:
                return float(tao_attr)
            except (TypeError, ValueError):
                pass
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

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

        # Live path: pull a real lite metagraph from the chain when
        # use_mock_data is False and the SDK is installed. lite=True
        # skips the multi-MB W (weight) and B (bond) matrices — the
        # weight-copy detector pulls those separately via
        # ``get_metagraph_full`` so the dashboard hot path stays cheap.
        bt = _try_import_bittensor()
        if not self.use_mock_data and bt is not None:
            try:
                live_mg = self._live_metagraph(bt, netuid, lite=True)
                self._cache_set("metagraph_cache", "netuid", netuid, live_mg)
                return live_mg
            except Exception as exc:
                logger.warning(
                    "Live metagraph failed for netuid=%d: %s — falling back "
                    "to mock", netuid, exc,
                )

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
