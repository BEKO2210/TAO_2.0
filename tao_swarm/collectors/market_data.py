"""
Market Data Collector for TAO/Bittensor.

Fetches price, volume, and market data from public CoinGecko API.
No API keys required for basic endpoints.
All data is cached in a local SQLite database.
"""

import json
import logging
import os
import sqlite3
import time

import requests

from tao_swarm.collectors._base import BaseCollector

logger = logging.getLogger(__name__)

# CoinGecko public API endpoints
COINGECKO_API_BASE = "https://api.coingecko.com/api/v3"
TAO_COIN_ID = "bittensor"

# Mock fixture data so the collector can run offline. Numbers are
# stable, plausible, and stamped with a clear ``_meta.mode == "mock"``
# downstream so consumers can tell.
_MOCK_PRICE: dict = {
    "bittensor": {
        "usd": 350.0,
        "usd_market_cap": 2_500_000_000.0,
        "usd_24h_vol": 75_000_000.0,
        "usd_24h_change": -2.9,
        "btc": 0.00525,
        "last_updated_at": 1_715_000_000,
    }
}


class MarketDataCollector(BaseCollector):
    """
    Collects TAO market data from public APIs.

    Uses CoinGecko's free tier (no API key needed). When
    ``use_mock_data`` is True (the default), returns stable fixture
    values without touching the network — keeps the test suite and
    air-gapped runs deterministic.
    """

    SOURCE_NAME = "market_data"

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the market data collector.

        Args:
            config: Configuration dictionary with keys:
                - 'use_mock_data': bool — force fixture data (default True)
                - 'db_path': SQLite database path
                - 'request_timeout': HTTP timeout in seconds (default 15)
                - 'cache_ttl': Cache time-to-live in seconds (default 120)
                - 'coingecko_api_key': Optional CoinGecko API key
        """
        config = config or {}
        # Override BaseCollector defaults that this collector specialises.
        config.setdefault("cache_ttl", 120)
        config.setdefault("timeout", config.get("request_timeout", 15))
        super().__init__(config)
        self.config = config
        self.db_path = config.get("db_path", "data/market_cache.db")
        self.api_key = config.get("coingecko_api_key", "")

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        logger.info(
            "MarketDataCollector initialized (use_mock_data=%s)",
            self.use_mock_data,
        )

    # ── Database ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create market data cache tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_cache (
                    coin_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS volume_cache (
                    coin_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS historical_cache (
                    coin_id TEXT NOT NULL,
                    days INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL,
                    PRIMARY KEY (coin_id, days)
                )
            """)
            conn.commit()

    def _cache_get(self, table: str, key_col: str, key_val: str) -> dict | None:
        """Retrieve cached data if not expired."""
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

    # ── API helpers ───────────────────────────────────────────────────────

    def _api_headers(self) -> dict:
        """Build API request headers."""
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-cg-pro-api-key"] = self.api_key
        return headers

    def _api_request(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a GET request to the CoinGecko API."""
        url = f"{COINGECKO_API_BASE}/{endpoint}"
        try:
            resp = requests.get(
                url, headers=self._api_headers(), params=params, timeout=self.timeout
            )
            if resp.status_code == 429:
                logger.warning("CoinGecko rate limit hit, waiting 10s...")
                time.sleep(10)
                resp = requests.get(
                    url, headers=self._api_headers(), params=params, timeout=self.timeout
                )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            logger.error("API request failed for %s: %s", endpoint, exc)
            return {"error": str(exc)}

    # ── Public API ────────────────────────────────────────────────────────

    def get_tao_price(self) -> dict:
        """
        Get current TAO price data.

        Returns:
            Dictionary with price in USD, BTC, market cap, etc., plus
            a ``_meta`` block describing whether the data came from
            mock or live.
        """
        cached = self._cache_get("price_cache", "coin_id", TAO_COIN_ID)
        if cached:
            return cached

        mode = self._resolve_mode()
        if mode == "mock":
            data = {**_MOCK_PRICE, "_meta": self._meta(mode)}
            self._cache_set("price_cache", "coin_id", TAO_COIN_ID, data)
            return data

        data = self._api_request(
            "simple/price",
            {
                "ids": TAO_COIN_ID,
                "vs_currencies": "usd,btc,eth",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
                "include_24hr_change": "true",
            },
        )

        if "error" in data:
            return data

        tao_data = data.get(TAO_COIN_ID, {})
        result = {
            "coin_id": TAO_COIN_ID,
            "price_usd": tao_data.get("usd", 0.0),
            "price_btc": tao_data.get("btc", 0.0),
            "price_eth": tao_data.get("eth", 0.0),
            "market_cap_usd": tao_data.get("usd_market_cap", 0.0),
            "volume_24h_usd": tao_data.get("usd_24h_vol", 0.0),
            "change_24h_pct": tao_data.get("usd_24h_change", 0.0),
            "timestamp": int(time.time()),
            "_meta": self._meta(mode, api=COINGECKO_API_BASE),
        }
        self._cache_set("price_cache", "coin_id", TAO_COIN_ID, result)
        return result

    def get_volume(self) -> dict:
        """
        Get TAO trading volume data.

        Returns:
            Dictionary with 24h volume and volume change.
        """
        cached = self._cache_get("volume_cache", "coin_id", TAO_COIN_ID)
        if cached:
            return cached

        data = self._api_request(
            f"coins/{TAO_COIN_ID}",
            {"localization": "false", "tickers": "false", "community_data": "false"},
        )

        if "error" in data:
            return data

        market_data = data.get("market_data", {})
        result = {
            "coin_id": TAO_COIN_ID,
            "volume_24h_usd": market_data.get("total_volume", {}).get("usd", 0.0),
            "volume_change_24h": market_data.get("volume_change_24h", 0.0),
            "volume_change_24h_in_currency": market_data.get("volume_change_24h_in_currency", {}).get("usd", 0.0),
            "timestamp": int(time.time()),
        }
        self._cache_set("volume_cache", "coin_id", TAO_COIN_ID, result)
        return result

    def get_market_data(self) -> dict:
        """
        Get complete market data for TAO.

        Returns:
            Comprehensive market data including price, volume, market cap,
            supply, price change, and rankings.
        """
        price = self.get_tao_price()
        volume = self.get_volume()

        # Fetch additional coin data
        data = self._api_request(
            f"coins/{TAO_COIN_ID}",
            {"localization": "false", "tickers": "false", "community_data": "true"},
        )

        market_data_info = data.get("market_data", {}) if "error" not in data else {}
        community = data.get("community_data", {}) if "error" not in data else {}

        result = {
            "coin_id": TAO_COIN_ID,
            "symbol": "tao",
            "name": "Bittensor",
            "price": {
                "usd": price.get("price_usd", 0.0),
                "btc": price.get("price_btc", 0.0),
                "eth": price.get("price_eth", 0.0),
            },
            "market_cap": {
                "usd": price.get("market_cap_usd", 0.0),
            },
            "volume": {
                "24h_usd": volume.get("volume_24h_usd", 0.0),
                "24h_change_pct": volume.get("volume_change_24h", 0.0),
            },
            "price_change": {
                "24h_pct": price.get("change_24h_pct", 0.0),
                "7d_pct": market_data_info.get("price_change_percentage_7d", 0.0),
                "30d_pct": market_data_info.get("price_change_percentage_30d", 0.0),
            },
            "supply": {
                "circulating": market_data_info.get("circulating_supply", 0.0),
                "total": market_data_info.get("total_supply", 0.0),
                "max": market_data_info.get("max_supply", 0.0),
            },
            "market_cap_rank": market_data_info.get("market_cap_rank", 0),
            "coingecko_rank": data.get("coingecko_rank", 0),
            "community": {
                "twitter_followers": community.get("twitter_followers", 0),
                "reddit_subscribers": community.get("reddit_subscribers", 0),
                "telegram_channel_user_count": community.get("telegram_channel_user_count", 0),
            },
            "timestamp": int(time.time()),
        }
        return result

    def get_historical_data(self, days: int = 30) -> list:
        """
        Get historical price data for TAO.

        Args:
            days: Number of days of history (1, 7, 30, 90, 365).

        Returns:
            List of daily OHLC-style price entries.
        """
        cached = self._cache_get("historical_cache", "days", days)
        if cached and "data" in cached:
            return cached["data"]

        data = self._api_request(
            f"coins/{TAO_COIN_ID}/market_chart",
            {"vs_currency": "usd", "days": str(days)},
        )

        if "error" in data:
            return []

        prices = data.get("prices", [])
        market_caps = data.get("market_caps", [])
        volumes = data.get("total_volumes", [])

        result = []
        for i, price_entry in enumerate(prices):
            ts, price = price_entry
            entry = {
                "timestamp": int(ts / 1000),
                "date": time.strftime("%Y-%m-%d", time.gmtime(ts / 1000)),
                "price_usd": price,
                "market_cap_usd": market_caps[i][1] if i < len(market_caps) else 0.0,
                "volume_usd": volumes[i][1] if i < len(volumes) else 0.0,
            }
            result.append(entry)

        self._cache_set(
            "historical_cache", "days", days, {"coin_id": TAO_COIN_ID, "days": days, "data": result}
        )
        logger.info("Fetched %d days of historical data (%d entries)", days, len(result))
        return result
