"""
Tests for the dashboard's pure-Python data-fetch helpers.

The dashboard module imports cleanly even without streamlit thanks to
the passthrough fallback in ``app.py`` (``@st.cache_data(ttl=60)``
becomes a no-op decorator). That lets us unit-test the fetch helpers
in CI without dragging in the full streamlit / pandas / plotly UI
dependency tree.

Coverage:

- ``_discover_chain_db`` honours ``TAO_NETWORK`` and prefers
  finney > test > mock > legacy.
- ``get_db_connection`` returns None for missing files (no exceptions).
- ``safe_query`` swallows malformed SQL into an empty list rather than
  exploding the page renderer.
- ``fetch_subnet_scores`` deduplicates by netuid (keeps latest).
- ``fetch_watched_wallets`` returns address+label rows.
- ``fetch_market_price`` round-trips JSON cache rows + tags cached_at.
- ``fetch_historical_prices`` returns the inner ``data`` array.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import time
from pathlib import Path

import pytest

import src.dashboard.app as dash


@pytest.fixture(autouse=True)
def _reset_streamlit_caches():
    """
    Clear ``@st.cache_data`` caches before every test in this module.

    The dashboard's ``fetch_*`` helpers are decorated with
    ``@st.cache_data(ttl=...)``. When streamlit is installed (the
    real CI install), the cache persists across tests in the same
    process, which makes a test that seeds DB ``X`` see the data
    from a previous test that seeded DB ``Y``. Locally without
    streamlit, the decorator is a no-op and the bug stays hidden.

    Clearing both ``cache_data`` and ``cache_resource`` (where they
    exist) guarantees a clean slate per test regardless of which
    streamlit version is installed.
    """
    for name in ("cache_data", "cache_resource"):
        attr = getattr(dash.st, name, None)
        clear = getattr(attr, "clear", None) if attr is not None else None
        if callable(clear):
            try:
                clear()
            except Exception:
                pass
    yield

# ---------------------------------------------------------------------------
# _discover_chain_db
# ---------------------------------------------------------------------------

def _make_empty_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sqlite3.connect(str(path)).close()


def test_discover_chain_db_prefers_explicit_env_var(tmp_path, monkeypatch):
    monkeypatch.setattr(dash, "DATA_DIR", tmp_path)
    monkeypatch.setenv("TAO_NETWORK", "test")
    _make_empty_db(tmp_path / "chain_cache.test.db")
    _make_empty_db(tmp_path / "chain_cache.finney.db")
    assert dash._discover_chain_db().name == "chain_cache.test.db"


def test_discover_chain_db_falls_back_to_finney(tmp_path, monkeypatch):
    monkeypatch.setattr(dash, "DATA_DIR", tmp_path)
    monkeypatch.delenv("TAO_NETWORK", raising=False)
    _make_empty_db(tmp_path / "chain_cache.mock.db")
    _make_empty_db(tmp_path / "chain_cache.finney.db")
    # finney beats mock when no env var is set
    assert dash._discover_chain_db().name == "chain_cache.finney.db"


def test_discover_chain_db_uses_legacy_when_namespaced_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(dash, "DATA_DIR", tmp_path)
    monkeypatch.delenv("TAO_NETWORK", raising=False)
    _make_empty_db(tmp_path / "chain_cache.db")
    assert dash._discover_chain_db().name == "chain_cache.db"


def test_discover_chain_db_returns_legacy_path_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(dash, "DATA_DIR", tmp_path)
    monkeypatch.delenv("TAO_NETWORK", raising=False)
    # Nothing exists yet — must return a path, not None, so render code
    # has something to render "missing" against.
    result = dash._discover_chain_db()
    assert result.name == "chain_cache.db"
    assert not result.exists()


# ---------------------------------------------------------------------------
# get_db_connection / safe_query
# ---------------------------------------------------------------------------

def test_get_db_connection_returns_none_for_missing_file(tmp_path, monkeypatch):
    monkeypatch.setitem(dash.DB_FILES, "scores", tmp_path / "nope.db")
    assert dash.get_db_connection("scores") is None


def test_get_db_connection_opens_existing_file(tmp_path, monkeypatch):
    db = tmp_path / "scores.db"
    sqlite3.connect(str(db)).close()
    monkeypatch.setitem(dash.DB_FILES, "scores", db)
    conn = dash.get_db_connection("scores")
    assert conn is not None
    conn.close()


def test_safe_query_returns_empty_list_on_bad_sql(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    out = dash.safe_query(conn, "SELECT * FROM nonexistent_table")
    assert out == []
    conn.close()


def test_safe_query_returns_rows_on_good_query(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (k INTEGER, v TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
    conn.commit()
    out = dash.safe_query(conn, "SELECT k, v FROM t ORDER BY k")
    assert out == [(1, "a"), (2, "b")]
    conn.close()


# ---------------------------------------------------------------------------
# fetch_subnet_scores
# ---------------------------------------------------------------------------

def _seed_scores_db(path: Path, rows: list[tuple]) -> None:
    """rows: list of (netuid, score, recommendation, scored_at)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE subnet_scores (netuid INTEGER, score REAL, "
        "recommendation TEXT, scored_at REAL)"
    )
    conn.executemany(
        "INSERT INTO subnet_scores VALUES (?, ?, ?, ?)", rows,
    )
    conn.commit()
    conn.close()


def test_fetch_subnet_scores_returns_empty_when_no_db(tmp_path, monkeypatch):
    monkeypatch.setitem(dash.DB_FILES, "scores", tmp_path / "missing.db")
    assert dash.fetch_subnet_scores() == []


def test_fetch_subnet_scores_dedupes_by_netuid_keeping_latest(tmp_path, monkeypatch):
    db = tmp_path / "scores.db"
    now = time.time()
    _seed_scores_db(db, [
        (12, 50.0, "CONDITIONAL", now - 100),
        (12, 75.0, "RECOMMENDED", now),       # newest for 12
        (5,  60.0, "CONDITIONAL", now - 50),
    ])
    monkeypatch.setitem(dash.DB_FILES, "scores", db)

    out = dash.fetch_subnet_scores()
    by_netuid = {row["netuid"]: row for row in out}
    assert set(by_netuid) == {5, 12}
    # Newest score for netuid 12 must win (75.0 / RECOMMENDED).
    assert by_netuid[12]["score"] == 75.0
    assert by_netuid[12]["recommendation"] == "RECOMMENDED"


# ---------------------------------------------------------------------------
# fetch_watched_wallets
# ---------------------------------------------------------------------------

def _seed_wallets_db(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE watched_addresses (address TEXT, label TEXT, added_at REAL)"
    )
    conn.executemany(
        "INSERT INTO watched_addresses VALUES (?, ?, ?)", rows,
    )
    conn.commit()
    conn.close()


def test_fetch_watched_wallets_returns_truncated_address_and_label(tmp_path, monkeypatch):
    db = tmp_path / "wallet_watch.db"
    addr = "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"
    _seed_wallets_db(db, [(addr, "cold1", time.time())])
    monkeypatch.setitem(dash.DB_FILES, "wallet", db)

    out = dash.fetch_watched_wallets()
    assert len(out) == 1
    row = out[0]
    assert row["full_address"] == addr
    # Truncated to "first20chars..." per the renderer's display logic
    assert row["address"] == addr[:20] + "..."
    assert row["label"] == "cold1"


def test_fetch_watched_wallets_handles_null_label(tmp_path, monkeypatch):
    db = tmp_path / "wallet_watch.db"
    _seed_wallets_db(db, [("5SomeAddress", None, time.time())])
    monkeypatch.setitem(dash.DB_FILES, "wallet", db)

    out = dash.fetch_watched_wallets()
    assert out[0]["label"] == "-"


# ---------------------------------------------------------------------------
# fetch_market_price + fetch_historical_prices
# ---------------------------------------------------------------------------

def _seed_market_db(path: Path, price_data: dict, hist_data: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE price_cache (coin_id TEXT, data TEXT, cached_at REAL)"
    )
    conn.execute(
        "INSERT INTO price_cache VALUES (?, ?, ?)",
        ("bittensor", json.dumps(price_data), time.time()),
    )
    if hist_data is not None:
        conn.execute(
            "CREATE TABLE historical_cache (coin_id TEXT, days INTEGER, "
            "data TEXT, cached_at REAL)"
        )
        conn.execute(
            "INSERT INTO historical_cache VALUES (?, ?, ?, ?)",
            ("bittensor", 30, json.dumps(hist_data), time.time()),
        )
    conn.commit()
    conn.close()


def test_fetch_market_price_round_trips_json_and_adds_cached_at(tmp_path, monkeypatch):
    db = tmp_path / "market_cache.db"
    _seed_market_db(db, {"bittensor": {"usd": 350.0}, "_meta": {"mode": "mock"}})
    monkeypatch.setitem(dash.DB_FILES, "market", db)

    out = dash.fetch_market_price()
    assert out["bittensor"]["usd"] == 350.0
    # The dashboard injects cached_at on top of the deserialized payload
    assert "cached_at" in out
    # Mode tag from PR #11 must survive the round-trip
    assert out["_meta"]["mode"] == "mock"


def test_fetch_market_price_returns_empty_when_no_db(tmp_path, monkeypatch):
    monkeypatch.setitem(dash.DB_FILES, "market", tmp_path / "missing.db")
    assert dash.fetch_market_price() == {}


def test_fetch_historical_prices_returns_inner_data_array(tmp_path, monkeypatch):
    db = tmp_path / "market_cache.db"
    hist = {"data": [
        {"timestamp": 1, "price": 100.0},
        {"timestamp": 2, "price": 105.0},
    ]}
    _seed_market_db(db, {"bittensor": {"usd": 100.0}}, hist_data=hist)
    monkeypatch.setitem(dash.DB_FILES, "market", db)

    series = dash.fetch_historical_prices(days=30)
    assert len(series) == 2
    assert series[0]["price"] == 100.0
    assert series[1]["timestamp"] == 2


# ---------------------------------------------------------------------------
# render_badge: pure formatter, no streamlit dep
# ---------------------------------------------------------------------------

def test_render_badge_normalises_status_to_css_class():
    assert dash.render_badge("READY") == '<span class="badge-ready">READY</span>'
    assert dash.render_badge("Not Ready") == '<span class="badge-not_ready">Not Ready</span>'
    assert dash.render_badge("LOW", prefix="risk") == '<span class="risk-low">LOW</span>'


# ---------------------------------------------------------------------------
# Module-level smoke: dashboard imports without streamlit
# ---------------------------------------------------------------------------

def test_dashboard_imports_without_streamlit():
    """Reload the module to make sure the import path is robust to a
    second pass — the @cache_data passthrough decorator must still
    work on re-import."""
    importlib.reload(dash)
    assert hasattr(dash, "fetch_subnet_scores")
    assert callable(dash.fetch_subnet_scores)
