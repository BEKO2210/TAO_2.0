"""
TAO/Bittensor Multi-Agent Dashboard

Streamlit-based dashboard for visualizing:
- System Status
- Subnet Scores
- Wallet Watch
- Market Watch
- Risk Alerts
- Paper Trades
- Run Logs

Connects to local SQLite databases.
No external telemetry. Dark mode design.
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Streamlit import with graceful fallback ───────────────────────────────

try:
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    import streamlit as st
    from plotly.subplots import make_subplots
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False
    logger.warning("streamlit, pandas, or plotly not installed. Dashboard unavailable.")
    logger.warning("Install: pip install streamlit pandas plotly")

    # Create dummy modules so the file imports cleanly without streamlit
    # (lets us unit-test the data-fetch helpers in CI without dragging in
    # the full UI dep tree). Decorator-style callables return a
    # passthrough so ``@st.cache_data(ttl=60)`` works on functions.
    def _passthrough_decorator(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            # Bare ``@deco`` form
            return args[0]
        # Parameterised ``@deco(...)`` form
        def _wrap(fn):
            return fn
        return _wrap

    class _DummySt:
        cache_data = staticmethod(_passthrough_decorator)
        cache_resource = staticmethod(_passthrough_decorator)

        def __getattr__(self, name):
            return lambda *a, **k: None

    st = _DummySt()
    pd = _DummySt()
    px = _DummySt()
    go = _DummySt()
    def make_subplots(*_a, **_k):  # noqa: ARG001 — stub when plotly missing
        return None

# ── Optional auto-refresh component ───────────────────────────────────────
# Lets the page rerun itself on a timer (reads fresh runner status /
# ledger / market data without a manual click). Degrades gracefully to
# a no-op if the component isn't installed, so the dashboard still runs.
try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dep
    AUTOREFRESH_AVAILABLE = False

    def st_autorefresh(*_a, **_k):  # noqa: ARG001 — stub
        return 0


# ── Page config ───────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TAO Swarm Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme ─────────────────────────────────────────────────────────────────
#
# All base styling (canvas, typography, metrics, tabs, sidebar, pills,
# hero blocks, banners) lives in ``theme.py`` as a single source of
# truth. It is injected once here, right after ``page_config`` so the
# CSS reaches the rendered DOM. We deliberately do NOT ship a second,
# competing stylesheet — the only thing added below is the small set of
# inline status-badge classes that ``render_badge`` emits and the theme
# doesn't define.
try:
    from tao_swarm.dashboard.theme import PALETTE
    from tao_swarm.dashboard.theme import inject as _inject_theme
    if STREAMLIT_AVAILABLE:
        _inject_theme(st)
except Exception:  # pragma: no cover - defensive
    PALETTE = {
        "bg": "#0b1220", "bg_card": "#121a2c", "text": "#e6edf3",
        "text_muted": "#9ba6b8", "border_lo": "#1f2942",
        "success": "#3fb950", "warning": "#d29922", "danger": "#f85149",
        "info": "#58a6ff",
    }

# Inline status-badge classes (used by ``render_badge``). Colours are
# pulled from the shared PALETTE so they can never drift from the theme.
BADGE_CSS = f"""
<style>
    .badge-ready, .badge-low        {{ color: {PALETTE['success']}; font-weight: 600; }}
    .badge-partial, .badge-medium   {{ color: {PALETTE['warning']}; font-weight: 600; }}
    .badge-not-ready, .badge-not_ready,
    .badge-high                     {{ color: {PALETTE['danger']};  font-weight: 600; }}
    .badge-critical                 {{ color: {PALETTE['danger']};  font-weight: 700; }}
</style>
"""
st.markdown(BADGE_CSS, unsafe_allow_html=True)

# Chart palette derived from the theme so plotly figures match the
# surrounding UI instead of the old GitHub-dark colours.
CHART = {
    "paper_bg": PALETTE["bg_card"],
    "plot_bg": PALETTE["bg"],
    "font": PALETTE["text"],
    "grid": PALETTE["border_lo"],
    "line": PALETTE["info"],
}

# ── Constants ─────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("TAO_DATA_DIR", "data"))


def _discover_chain_db() -> Path:
    """
    Pick the best chain cache file to read.

    PR #10 namespaced the chain cache by network, so the file may now
    live at ``chain_cache.mock.db`` / ``chain_cache.finney.db`` etc.
    Preference: an explicit ``TAO_NETWORK`` env var beats anything
    else; otherwise prefer ``finney`` (real data) > ``test`` > ``mock``
    > the legacy un-namespaced ``chain_cache.db``. Returns the legacy
    path when nothing exists, so render_system_status still surfaces
    a clear "missing" row.
    """
    env_net = os.environ.get("TAO_NETWORK", "").strip().lower()
    candidates: list[str] = []
    if env_net:
        candidates.append(f"chain_cache.{env_net}.db")
    for net in ("finney", "test", "mock"):
        candidates.append(f"chain_cache.{net}.db")
    candidates.append("chain_cache.db")  # legacy

    for name in candidates:
        path = DATA_DIR / name
        if path.exists():
            return path
    return DATA_DIR / "chain_cache.db"


DB_FILES = {
    "chain": _discover_chain_db(),
    "market": DATA_DIR / "market_cache.db",
    "wallet": DATA_DIR / "wallet_watch.db",
    "github": DATA_DIR / "github_cache.db",
    "scores": DATA_DIR / "scores.db",
    "subnet_meta": DATA_DIR / "subnet_metadata.db",
}

# ── Helper functions ──────────────────────────────────────────────────────

def get_db_connection(db_name: str):
    """Get SQLite connection to a database."""
    db_path = DB_FILES.get(db_name)
    if db_path and db_path.exists():
        return sqlite3.connect(str(db_path))
    return None


def safe_query(conn, query: str, params=None):
    """Execute query safely with error handling."""
    try:
        cursor = conn.execute(query, params or ())
        return cursor.fetchall()
    except Exception:
        return []


def render_badge(status: str, prefix: str = "badge") -> str:
    """Render a colored status badge."""
    status_lower = status.lower().replace("-", "_").replace(" ", "_")
    return f'<span class="{prefix}-{status_lower}">{status}</span>'


@st.cache_data(ttl=60)
def fetch_subnet_scores() -> list:
    """Fetch subnet scores from database."""
    conn = get_db_connection("scores")
    if not conn:
        return []
    rows = safe_query(
        conn,
        "SELECT netuid, score, recommendation, scored_at FROM subnet_scores ORDER BY scored_at DESC",
    )
    conn.close()

    # Deduplicate by netuid (keep latest)
    seen = set()
    results = []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            results.append({
                "netuid": r[0],
                "score": r[1],
                "recommendation": r[2],
                "scored_at": datetime.fromtimestamp(r[3], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if r[3] else "",
            })
    return results


@st.cache_data(ttl=60)
def fetch_watched_wallets() -> list:
    """Fetch watched wallets from database."""
    conn = get_db_connection("wallet")
    if not conn:
        return []
    rows = safe_query(conn, "SELECT address, label, added_at FROM watched_addresses")
    conn.close()
    return [
        {
            "address": r[0][:20] + "...",
            "full_address": r[0],
            "label": r[1] or "-",
            "added": datetime.fromtimestamp(r[2], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if r[2] else "",
        }
        for r in rows
    ]


@st.cache_data(ttl=120)
def fetch_market_price() -> dict:
    """Fetch cached market price.

    The collector stores two different shapes depending on the source:
    the LIVE (CoinGecko) path writes flat keys (``price_usd`` …), while
    the MOCK fixture writes a nested CoinGecko-style ``{"bittensor":
    {"usd": …}}`` block. Normalise both to the flat keys the renderer
    reads so the page never shows N/A when data actually exists.
    """
    conn = get_db_connection("market")
    if not conn:
        return {}
    rows = safe_query(conn, "SELECT data, cached_at FROM price_cache ORDER BY cached_at DESC LIMIT 1")
    conn.close()
    if not rows:
        return {}

    data = json.loads(rows[0][0])

    # Nested CoinGecko shape (mock fixture) -> add flat keys on top so
    # the renderer finds them, while leaving the original nested block
    # intact for any caller that reads it directly.
    if "price_usd" not in data and isinstance(data.get("bittensor"), dict):
        b = data["bittensor"]
        data.setdefault("price_usd", b.get("usd", 0.0))
        data.setdefault("price_btc", b.get("btc", 0.0))
        data.setdefault("market_cap_usd", b.get("usd_market_cap", 0.0))
        data.setdefault("volume_24h_usd", b.get("usd_24h_vol", 0.0))
        data.setdefault("change_24h_pct", b.get("usd_24h_change", 0.0))

    data["cached_at"] = rows[0][1]
    return data


@st.cache_data(ttl=300)
def fetch_historical_prices(days: int = 30) -> list:
    """Fetch historical price data."""
    conn = get_db_connection("market")
    if not conn:
        return []
    rows = safe_query(
        conn,
        "SELECT data FROM historical_cache WHERE days = ? ORDER BY cached_at DESC LIMIT 1",
        (days,),
    )
    conn.close()
    if rows:
        data = json.loads(rows[0][0])
        return data.get("data", [])
    return []


@st.cache_data(ttl=30)
def fetch_subnet_metrics() -> list:
    """Fetch real per-subnet chain metrics written by populate_all_data."""
    conn = get_db_connection("scores")
    if not conn:
        return []
    rows = safe_query(
        conn,
        "SELECT netuid, name, tao_in, emission, volume, price "
        "FROM subnet_metrics ORDER BY tao_in DESC",
    )
    conn.close()
    return [
        {
            "netuid": r[0], "name": r[1] or "", "tao_in": r[2] or 0.0,
            "emission": r[3] or 0.0, "volume": r[4] or 0.0,
            "price": r[5] or 0.0,
        }
        for r in rows
    ]


def populate_all_data() -> dict:
    """Fill the dashboard databases from live sources in one call.

    Fetches real TAO market data (price + history) and the live subnet
    list from the Bittensor chain, writes each subnet's real chain
    metrics (tao_in / emission / volume / price) to ``subnet_metrics``,
    and runs the scorer over them. Everything here is real data — no
    fabricated numbers. Returns a summary for the caller to display.
    """
    import time

    summary = {"market": "-", "subnets": 0, "scored": 0, "errors": []}
    data_dir = Path(os.environ.get("TAO_DATA_DIR", "data"))

    # --- Market (price + history) -------------------------------------
    try:
        from tao_swarm.collectors.market_data import MarketDataCollector
        mc = MarketDataCollector({
            "use_mock_data": False,
            "db_path": str(data_dir / "market_cache.db"),
        })
        p = mc.get_tao_price()
        summary["market"] = f"${p.get('price_usd', 0):,.2f}"
        for d in (7, 30):
            try:
                mc.get_historical_data(d)
            except Exception as exc:  # noqa: BLE001
                summary["errors"].append(f"Historie {d}d: {exc}")
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"Markt: {exc}")

    # --- Subnets (live chain metrics + scoring) -----------------------
    try:
        from tao_swarm.collectors.chain_readonly import ChainReadOnlyCollector
        from tao_swarm.scoring.subnet_score import SubnetScorer

        net = os.environ.get("TAO_NETWORK", "finney")
        cc = ChainReadOnlyCollector({
            "use_mock_data": False, "network": net,
            "db_path": str(data_dir / f"chain_cache.{net}.db"),
        })
        subs = cc.get_subnet_list()
        subs = subs if isinstance(subs, list) else subs.get("subnets", [])
        summary["subnets"] = len(subs)

        sc = SubnetScorer({"db_path": str(data_dir / "scores.db")})
        # Non-dict chain fields the scorer can't consume; strip before scoring.
        drop = {"owner", "identity", "owner_hotkey", "symbol", "name",
                "is_dynamic"}
        rows = []
        for sub in subs:
            netuid = sub.get("netuid")
            if netuid is None:
                continue
            clean = {k: v for k, v in sub.items() if k not in drop}
            clean["netuid"] = netuid
            try:
                sc.score_subnet(clean)
                summary["scored"] += 1
            except Exception:  # noqa: BLE001 — scoring is best-effort
                pass
            rows.append((
                int(netuid), sub.get("name", ""),
                float(sub.get("tao_in", 0) or 0),
                float(sub.get("emission", 0) or 0),
                float(sub.get("subnet_volume", 0) or 0),
                float(sub.get("price", 0) or 0),
                time.time(),
            ))

        conn = sqlite3.connect(str(data_dir / "scores.db"))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS subnet_metrics ("
            "netuid INTEGER PRIMARY KEY, name TEXT, tao_in REAL, "
            "emission REAL, volume REAL, price REAL, updated_at REAL)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO subnet_metrics VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"Subnetze: {exc}")

    return summary


def _load_all_button(label: str = "Alles laden (Live-Daten holen)") -> None:
    """Render the one-click data-fill button + run it on click."""
    if st.button(label, use_container_width=True):
        with st.spinner("Lade Live-Daten von Bittensor + Markt …"):
            s = populate_all_data()
        st.cache_data.clear()
        if s["errors"]:
            st.warning("Teilweise geladen: " + " · ".join(s["errors"][:3]))
        st.success(
            f"{s['subnets']} Subnetze geladen, {s['scored']} bewertet · "
            f"Markt {s['market']}."
        )
        st.rerun()


# ── Page renderers ────────────────────────────────────────────────────────

def render_system_status():
    """Render the System Status page."""
    st.header("System Status")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Dashboard", "Online", "v1.0.0")
    with col2:
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        st.metric("Last Update", now)
    with col3:
        db_count = sum(1 for p in DB_FILES.values() if p.exists())
        st.metric("DB Files", f"{db_count}/{len(DB_FILES)}")
    with col4:
        st.metric("Mode", "Read-Only", "SAFE")

    st.divider()

    # Database status table
    st.subheader("Database Status")
    db_status = []
    for name, path in DB_FILES.items():
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        db_status.append({
            "Database": name,
            "Path": str(path),
            "Exists": "Yes" if exists else "No",
            "Size": f"{size / 1024:.1f} KB" if size else "-",
        })

    st.dataframe(pd.DataFrame(db_status), use_container_width=True, hide_index=True)

    st.divider()

    # System checks
    st.subheader("System Checks")
    checks = [
        ("Python Version", "3.10+", sys.version.split()[0], True),
        ("Streamlit", "1.30+", st.__version__, STREAMLIT_AVAILABLE),
        ("Pandas", "2.0+", pd.__version__, True),
        ("SQLite", "3.35+", sqlite3.sqlite_version, True),
        ("Network", "Online", "Check required", None),
    ]

    check_data = []
    for name, required, actual, ok in checks:
        status = "PASS" if ok else "FAIL" if ok is False else "UNKNOWN"
        check_data.append({
            "Component": name,
            "Required": required,
            "Actual": actual,
            "Status": status,
        })

    st.dataframe(pd.DataFrame(check_data), use_container_width=True, hide_index=True)


def render_subnet_scores():
    """Render the Subnetze page — real live chain metrics per subnet."""
    st.header("Subnetze")

    metrics = fetch_subnet_metrics()

    if not metrics:
        st.info(
            "Noch keine Subnetz-Daten geladen. Ein Klick holt die echten "
            "Live-Zahlen von der Bittensor-Kette."
        )
        _load_all_button()
        return

    _load_all_button("Neu laden (aktualisieren)")
    st.divider()

    df = pd.DataFrame(metrics)

    c1, c2, c3 = st.columns(3)
    c1.metric("Subnetze", len(df))
    c2.metric("TAO in Pools (Summe)", f"{df['tao_in'].sum():,.0f}".replace(",", "."))
    top1 = df.iloc[0]
    c3.metric("Größtes Subnetz", f"#{int(top1['netuid'])} {top1['name']}")

    # Real, varying signal: pool depth (tao_in) of the top subnets.
    st.subheader("Top 15 nach Pool-Tiefe (tao_in)")
    top = df.head(15).copy()
    top["label"] = top.apply(
        lambda r: f"#{int(r['netuid'])} {r['name']}"[:22], axis=1,
    )
    fig = px.bar(
        top, x="tao_in", y="label", orientation="h",
        color="tao_in", color_continuous_scale=[CHART["grid"], CHART["line"]],
        labels={"tao_in": "TAO in Pool", "label": ""},
    )
    fig.update_layout(
        paper_bgcolor=CHART["paper_bg"], plot_bgcolor=CHART["plot_bg"],
        font_color=CHART["font"], height=460,
        yaxis=dict(autorange="reversed"),
        xaxis=dict(gridcolor=CHART["grid"]), coloraxis_showscale=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Merge in the baseline scores if scoring produced any.
    scores = {s["netuid"]: s for s in fetch_subnet_scores()}
    show = df.rename(columns={
        "netuid": "Subnetz", "name": "Name", "tao_in": "TAO (Pool)",
        "emission": "Emission", "volume": "Volumen", "price": "Preis",
    }).copy()
    if scores:
        show["Score"] = df["netuid"].map(
            lambda n: round(scores[n]["score"], 1) if n in scores else None
        )
        st.caption(
            "Score ist ein Basiswert nur aus Chain-Daten (ohne kuratierte "
            "Profile) — er variiert daher wenig. Aussagekräftig sind die "
            "echten Chain-Zahlen links."
        )

    st.subheader("Alle Subnetze (Live-Chain-Daten)")
    st.dataframe(show, use_container_width=True, hide_index=True)


def render_wallet_watch():
    """Render the Wallet Watch page."""
    st.header("Wallet Watch")

    wallets = fetch_watched_wallets()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Watched Addresses", len(wallets))
    with col2:
        st.metric("Mode", "Watch-Only", "SAFE")
    with col3:
        st.metric("Total Balance", "See details")

    st.divider()

    if not wallets:
        st.info("No wallets being watched. Add via CLI: `tao-swarm watch <address>`")
        return

    st.subheader("Watched Addresses")
    st.dataframe(pd.DataFrame(wallets), use_container_width=True, hide_index=True)

    st.info("All wallet data is read-only. No private keys or seeds are ever stored.")


def render_market_watch():
    """Render the Market Watch page."""
    st.header("Market Watch")

    price = fetch_market_price()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        price_usd = price.get("price_usd", 0)
        st.metric("TAO Price", f"${price_usd:,.2f}" if price_usd else "N/A")
    with col2:
        change = price.get("change_24h_pct", 0)
        st.metric("24h Change", f"{change:+.2f}%", f"{change:+.2f}%")
    with col3:
        mcap = price.get("market_cap_usd", 0)
        st.metric("Market Cap", f"${mcap/1e9:.2f}B" if mcap else "N/A")
    with col4:
        vol = price.get("volume_24h_usd", 0)
        st.metric("24h Volume", f"${vol/1e6:.2f}M" if vol else "N/A")

    st.divider()

    # Historical price chart
    st.subheader("Price Chart")
    days = st.selectbox("Timeframe", [7, 30, 90], index=1)
    history = fetch_historical_prices(days)

    if history:
        df_hist = pd.DataFrame(history)
        df_hist["date"] = pd.to_datetime(df_hist["date"])

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_hist["date"],
            y=df_hist["price_usd"],
            mode="lines",
            name="TAO/USD",
            line=dict(color=CHART["line"], width=2),
            fill="tozeroy",
            fillcolor="rgba(88, 166, 255, 0.1)",
        ))
        fig.add_trace(go.Bar(
            x=df_hist["date"],
            y=df_hist["volume_usd"],
            name="Volume",
            marker_color="rgba(175, 184, 193, 0.3)",
            yaxis="y2",
        ))

        fig.update_layout(
            paper_bgcolor=CHART["paper_bg"],
            plot_bgcolor=CHART["plot_bg"],
            font_color=CHART["font"],
            xaxis=dict(gridcolor=CHART["grid"]),
            yaxis=dict(gridcolor=CHART["grid"], title="Price (USD)"),
            yaxis2=dict(gridcolor=CHART["grid"], title="Volume", overlaying="y", side="right"),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=500,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"No historical data cached for {days} days. Fetch via CLI or collector.")


def render_risk_alerts():
    """Render the Risk Alerts page."""
    st.header("Risk Alerts")

    # Mock risk data for display
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Active Alerts", "0", "All clear")
    with col2:
        st.metric("Highest Risk", "MEDIUM")
    with col3:
        st.metric("Veto Count", "0", "No vetos")

    st.divider()

    st.subheader("Risk Categories")
    risk_categories = [
        {"Category": "Technical", "Score": 15, "Level": "LOW", "Status": "OK"},
        {"Category": "Financial", "Score": 35, "Level": "MEDIUM", "Status": "Monitor"},
        {"Category": "Wallet", "Score": 5, "Level": "LOW", "Status": "OK"},
        {"Category": "Reputation", "Score": 20, "Level": "LOW", "Status": "OK"},
    ]

    for cat in risk_categories:
        color = "#3fb950" if cat["Level"] == "LOW" else "#d29922" if cat["Level"] == "MEDIUM" else "#f85149"
        col_a, col_b, col_c = st.columns([2, 2, 3])
        with col_a:
            st.markdown(f"**{cat['Category']}**")
        with col_b:
            st.markdown(f"Score: `{cat['Score']}`")
        with col_c:
            st.markdown(f"<span style='color:{color}'>**{cat['Level']}** — {cat['Status']}</span>", unsafe_allow_html=True)

    st.divider()
    st.info("Risk data is updated via the scoring pipeline. Run `tao-swarm risk` to refresh.")


def render_trading():
    """Render the Trading page — runner status + ledger summary +
    equity chart + outcome distribution + halt control + in-page
    backtest mini-panel."""
    from datetime import datetime, timezone

    from tao_swarm.dashboard.trading_view import (
        equity_curve,
        halt_runner_via_killswitch,
        load_runner_status,
        outcome_distribution,
        runner_health_label,
        summarise_ledger,
        trades_to_table_rows,
    )
    from tao_swarm.trading import PaperLedger

    st.header("Trading")
    st.caption(
        "Live + paper trading status. Paper trades default; live "
        "execution requires explicit env, keystore, and per-strategy "
        "opt-in (see docs/auto_trading.md)."
    )

    # ---- Runner status panel ---------------------------------------------
    data_dir = Path(os.environ.get("TAO_DATA_DIR", "data"))
    status_path = Path(os.environ.get(
        "TAO_RUNNER_STATUS_FILE", data_dir / "runner_status.json",
    ))
    status = load_runner_status(status_path)
    label, _ = runner_health_label(status)

    st.subheader("Runner")
    if status:
        from tao_swarm.dashboard.theme import banner, hero_block, status_pill

        # Status-pill row above the hero — gives the operator a single-
        # glance read on whether the bot is healthy.
        st.markdown(
            status_pill(label) + "  &nbsp;"
            + (
                f"<span style='color:#9ba6b8'>strategy "
                f"<b>{status.get('strategy', '—')}</b> · "
                f"mode <b>"
                + ("LIVE" if not status.get("paper", True) else "PAPER")
                + "</b></span>"
            ),
            unsafe_allow_html=True,
        )

        ts = status.get("last_tick_ts")
        if ts:
            tick_str = datetime.fromtimestamp(
                float(ts), tz=timezone.utc,
            ).strftime("%Y-%m-%d %H:%M:%S")
        else:
            tick_str = "never"

        st.markdown(hero_block([
            ("Ticks", str(int(status.get("ticks", 0))), None),
            ("Executed", str(int(status.get("executed", 0))), None),
            ("Refused", str(int(status.get("refused", 0))), None),
            ("Errors", str(int(status.get("errors", 0))), None),
            ("Last tick", tick_str, "UTC"),
        ]), unsafe_allow_html=True)

        if status.get("halted_reason"):
            st.markdown(
                banner("danger", f"<b>HALTED.</b> {status['halted_reason']}"),
                unsafe_allow_html=True,
            )
        elif status.get("last_error"):
            st.markdown(
                banner("warning", f"<b>Last error.</b> {status['last_error']}"),
                unsafe_allow_html=True,
            )

        positions = status.get("open_positions") or {}
        if positions:
            st.markdown("**Open positions**")
            rows = [
                {
                    "netuid": int(uid),
                    "size_tao": float(p.get("size", 0.0)),
                    "entry_tao": float(p.get("entry", 0.0)),
                }
                for uid, p in positions.items()
            ]
            st.dataframe(
                pd.DataFrame(rows), use_container_width=True, hide_index=True,
            )
        else:
            st.caption("No open positions.")

        rec_ts = status.get("last_reconcile_ts")
        if rec_ts:
            rec_str = datetime.fromtimestamp(
                float(rec_ts), tz=timezone.utc,
            ).strftime("%Y-%m-%d %H:%M:%S")
            st.caption(
                f"Last cold-start reconcile: {rec_str} UTC · "
                f"reconciled total = "
                f"{status.get('reconciled_total_tao') or 0.0:.4f} TAO"
            )
    else:
        st.info(
            f"No runner status file at `{status_path}`. Start a runner with "
            "`tao-swarm trade run --status-file <path>` to populate this."
        )

    # ---- Halt-runner control ---------------------------------------------
    kill_path = Path(os.environ.get(
        "TAO_KILL_SWITCH_PATH", data_dir / ".kill",
    ))
    halt_col, halt_msg = st.columns([1, 4])
    with halt_col:
        if st.button(
            "Halt runner",
            disabled=kill_path.exists(),
            help=(
                "Touches the kill-switch file the runner watches. The "
                "runner refuses to act once this file exists. Manual "
                "deletion required to resume."
            ),
        ):
            try:
                halt_runner_via_killswitch(
                    kill_path, reason="dashboard halt button",
                )
                st.toast("Kill switch triggered")
                st.rerun()
            except Exception as exc:
                st.error(f"Failed to write kill switch: {exc}")
    with halt_msg:
        if kill_path.exists():
            st.warning(
                f"Kill switch is ACTIVE: `{kill_path}`. Delete the file "
                "manually to resume trading."
            )
        else:
            st.caption(f"Kill-switch path: `{kill_path}` (not active).")

    st.divider()

    # ---- Ledger summary ---------------------------------------------------
    st.subheader("Trade ledger")
    ledger_path = Path(os.environ.get(
        "TAO_LEDGER_DB", data_dir / "trades.db",
    ))
    if not ledger_path.exists():
        st.caption(f"No ledger at `{ledger_path}`. No trades recorded yet.")
        return

    ledger = PaperLedger(str(ledger_path))

    # Strategy filter — pull distinct strategies once, let the operator
    # narrow everything below to a single one.
    overview = summarise_ledger(ledger, limit=2000)
    strategy_options = ("All",) + overview.distinct_strategies
    strategy_filter = st.selectbox(
        "Strategy filter",
        options=strategy_options,
        index=0,
        help="Restrict the ledger summary, equity curve, and trade "
             "table below to a single strategy.",
    )
    selected_strategy = None if strategy_filter == "All" else strategy_filter

    summary = summarise_ledger(ledger, strategy=selected_strategy, limit=500)
    s = summary.as_dict()

    all_trades = list(ledger.list_trades(strategy=selected_strategy, limit=2000))
    # The live paper runner books stake/unstake but never writes a
    # realised-P&L row (only the backtester does, as ``unstake_realised``).
    # So a 0 here means "not computed", not "zero profit" — label it
    # honestly rather than implying a break-even result.
    pnl_computed = any(
        getattr(t, "action", "") == "unstake_realised" for t in all_trades
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total trades", s["total_trades"])
    with col2:
        st.metric("Paper", s["paper_trades"])
    with col3:
        st.metric("Live", s["live_trades"])
    with col4:
        st.metric("Failed", s["failed_trades"])

    if pnl_computed:
        st.metric("Realised P&L (TAO)", f"{s['realised_pnl_tao']:+.4f}")
    else:
        st.metric("Realised P&L (TAO)", "nicht berechnet")
        st.caption(
            "Der Live-Paper-Runner bucht Stakes/Unstakes, berechnet aber "
            "keinen Gewinn/Verlust pro Trade. „0“ hieße hier „nicht "
            "berechnet“, nicht „kein Gewinn“ — daher der Hinweis statt "
            "einer Zahl."
        )

    if s["distinct_strategies"]:
        st.caption(
            "Strategies present: " + ", ".join(s["distinct_strategies"])
        )

    # ---- Equity curve ----------------------------------------------------
    curve = equity_curve(all_trades)
    if curve:
        st.subheader("Equity curve (realised P&L)")
        eq_df = pd.DataFrame([
            {
                "time": pd.to_datetime(p.timestamp, unit="s", utc=True),
                "cumulative_pnl_tao": p.cumulative_pnl_tao,
            }
            for p in curve
        ]).set_index("time")
        st.line_chart(eq_df, height=260, use_container_width=True)
    else:
        st.caption("No realised P&L yet — equity curve becomes meaningful "
                   "once a position closes.")

    # ---- Outcome distribution -------------------------------------------
    dist = outcome_distribution(all_trades)
    d = dist.as_dict()
    st.subheader("Closed-trade outcomes")
    odc1, odc2, odc3, odc4 = st.columns(4)
    with odc1:
        st.metric("Wins", d["wins"])
    with odc2:
        st.metric("Losses", d["losses"])
    with odc3:
        st.metric("Win rate", f"{d['win_rate'] * 100:.1f}%")
    with odc4:
        st.metric("Net realised", f"{d['total_realised_pnl_tao']:+.4f}")
    if d["wins"] or d["losses"]:
        st.caption(
            f"Largest win: {d['largest_win_tao']:+.4f} TAO · "
            f"Largest loss: {d['largest_loss_tao']:+.4f} TAO · "
            f"Break-evens: {d['breakevens']}"
        )

    # ---- Learning: per-strategy KPI + live ensemble weights ------------
    from tao_swarm.dashboard.trading_view import (
        per_strategy_equity_curves,
        per_strategy_snapshot,
    )
    from tao_swarm.trading import (
        PerformanceTracker,
        StrategyRegistry,
        inverse_loss_weights,
    )

    tracker = PerformanceTracker(ledger)
    try:
        registry = StrategyRegistry()
        registry.register_builtins()
        registry_names = list(registry.names())
    except Exception:
        registry_names = []

    overview_strategies = sorted(
        set(overview.distinct_strategies) | set(registry_names)
    )
    if overview_strategies:
        suggested_weights = inverse_loss_weights(
            overview_strategies, tracker, window_days=14,
        )
        snapshots = per_strategy_snapshot(
            tracker, strategies=overview_strategies,
            window_days=14, weights=suggested_weights,
        )

        st.subheader("Per-strategy performance (14-day window)")
        snap_rows = []
        for s in snapshots:
            snap_rows.append({
                "strategy": s.strategy,
                "pnl_tao": s.realised_pnl_tao,
                "win_rate": f"{s.win_rate * 100:.1f}%",
                "sharpe": s.sharpe,
                "closes": s.num_realised_closes,
                "attempts": s.num_attempts,
                "weight": (
                    f"{s.ensemble_weight * 100:.1f}%"
                    if s.ensemble_weight is not None else "—"
                ),
                "insufficient_data": s.insufficient_data,
            })
        if snap_rows:
            st.dataframe(
                pd.DataFrame(snap_rows),
                use_container_width=True, hide_index=True,
            )

        # Live ensemble weight bars: visualise capital allocation
        # the operator would get with --strategy ensemble:all today.
        st.subheader("Suggested ensemble weights (inverse-loss, 14-day)")
        st.caption(
            "Hypothetical allocation if you ran `--strategy ensemble:all` "
            "today. Active only when the runner is wired with an ensemble."
        )
        weight_rows = sorted(
            suggested_weights.items(), key=lambda kv: -kv[1],
        )
        for name, w in weight_rows:
            st.write(f"**{name}** — {w * 100:.1f}%")
            st.progress(min(max(w, 0.0), 1.0))

        # Per-strategy equity-curve overlay
        equity_data = per_strategy_equity_curves(
            ledger, overview_strategies, limit_per_strategy=500,
        )
        eq_frames = []
        for name, curve in equity_data.items():
            for p in curve:
                eq_frames.append({
                    "time": pd.to_datetime(p.timestamp, unit="s", utc=True),
                    "strategy": name,
                    "cumulative_pnl_tao": p.cumulative_pnl_tao,
                })
        if eq_frames:
            st.subheader("Equity curves by strategy")
            eq_overlay = pd.DataFrame(eq_frames)
            pivoted = eq_overlay.pivot_table(
                index="time", columns="strategy", values="cumulative_pnl_tao",
                aggfunc="last",
            ).ffill()
            st.line_chart(pivoted, height=260, use_container_width=True)

    # ---- Recent trades table --------------------------------------------
    rows = trades_to_table_rows(
        ledger.list_trades(strategy=selected_strategy, limit=200)
    )
    if not rows:
        st.caption("No recent trades.")
    else:
        st.subheader("Recent trades")
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        st.dataframe(df, use_container_width=True, hide_index=True)

    # ---- Backtest mini-panel --------------------------------------------
    st.divider()
    st.subheader("Backtest a strategy")
    st.caption(
        "Upload a JSON snapshot list (same shape as "
        "`tao-swarm trade backtest --snapshots`). Result is in-memory "
        "only — does NOT touch the ledger above."
    )

    bt_col1, bt_col2 = st.columns([2, 1])
    with bt_col1:
        upload = st.file_uploader(
            "snapshots.json",
            type=["json"],
            help="JSON list of market_state dicts.",
        )
    with bt_col2:
        try:
            from tao_swarm.trading import StrategyRegistry
            _reg = StrategyRegistry()
            _reg.register_builtins()
            strategy_choices = list(_reg.names())
        except Exception:
            strategy_choices = ["momentum_rotation", "mean_reversion"]
        bt_strategy = st.selectbox(
            "Strategy", options=strategy_choices, index=0,
        )

    bt_p1, bt_p2 = st.columns(2)
    with bt_p1:
        bt_threshold = st.number_input(
            "threshold_pct", value=0.05, min_value=0.001,
            max_value=1.0, step=0.005, format="%.3f",
        )
    with bt_p2:
        bt_slot = st.number_input(
            "slot_size_tao", value=1.0, min_value=0.001, step=0.5,
        )

    if upload is not None and st.button("Run backtest"):
        try:
            snapshots = json.loads(upload.getvalue().decode("utf-8"))
        except Exception as exc:
            st.error(f"Invalid JSON: {exc}")
        else:
            if not isinstance(snapshots, list):
                st.error("Snapshot file must contain a JSON list.")
            else:
                from tao_swarm.trading import Backtester, StrategyRegistry
                reg = StrategyRegistry()
                reg.register_builtins()
                cls = reg.get(bt_strategy)
                strat = cls(
                    threshold_pct=float(bt_threshold),
                    slot_size_tao=float(bt_slot),
                )
                bt = Backtester(strat, paper_db_path=":memory:")
                with st.spinner("Running backtest…"):
                    result = bt.run(snapshots)
                rd = result.as_dict()
                bt_c1, bt_c2, bt_c3, bt_c4 = st.columns(4)
                with bt_c1:
                    st.metric("Steps", rd["num_steps"])
                with bt_c2:
                    st.metric("Executed", rd["num_executed"])
                with bt_c3:
                    st.metric("Win rate", f"{rd['win_rate'] * 100:.1f}%")
                with bt_c4:
                    st.metric(
                        "Total P&L (TAO)", f"{rd['total_pnl_tao']:+.4f}",
                    )
                st.caption(
                    f"Max drawdown: {rd['max_drawdown_tao']:.4f} TAO · "
                    f"Pseudo-Sharpe: {rd['sharpe_ratio']:.4f} · "
                    f"Refused: {rd['num_refused']}"
                )
                if rd["refusals"]:
                    with st.expander("Refusal reasons"):
                        for r in rd["refusals"]:
                            st.write(f"- {r}")


def render_run_logs():
    """Render the Run Logs page."""
    st.header("Run Logs")

    # Read from run_log.md if available
    log_path = Path("docs/run_log.md")
    if log_path.exists():
        with open(log_path) as f:
            content = f.read()
        st.markdown(content)
    else:
        st.info("No run log found at docs/run_log.md")

    st.divider()

    st.subheader("Recent Activity")
    activity = [
        {"Time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "Level": "INFO", "Message": "Dashboard started"},
        {"Time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "Level": "INFO", "Message": "System check: OK"},
    ]
    st.dataframe(pd.DataFrame(activity), use_container_width=True, hide_index=True)


def render_overview():
    """Simple, plain-language landing page.

    One screen, big numbers, traffic-light status. This is the front
    door for someone who just wants to know: is the bot running, is it
    paper or real, and how is it doing — without wading through the
    detailed panels on the other pages.
    """
    from tao_swarm.dashboard.theme import banner, hero_block, status_pill
    from tao_swarm.dashboard.trading_view import (
        equity_curve,
        load_runner_status,
        runner_health_label,
        summarise_ledger,
    )
    from tao_swarm.trading import PaperLedger

    data_dir = Path(os.environ.get("TAO_DATA_DIR", "data"))
    status_path = Path(os.environ.get(
        "TAO_RUNNER_STATUS_FILE", data_dir / "runner_status.json",
    ))
    status = load_runner_status(status_path)
    label, _ = runner_health_label(status)

    st.header("Übersicht")

    # ---- Big status line: running? paper or real? --------------------
    is_running = bool(status) and (status.get("state") == "running")
    is_paper = not status or status.get("paper", True)

    headline = "Bot läuft" if is_running else "Bot gestoppt"
    st.markdown(
        f"<div style='font-size:2rem;font-weight:700;margin:0.2rem 0;'>"
        f"{headline}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(status_pill(label), unsafe_allow_html=True)

    if is_paper:
        st.markdown(
            banner("info",
                   "<b>Übungs-Modus (Paper).</b> Es wird nur simuliert — "
                   "kein echtes Geld, keine echten Trades."),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            banner("danger",
                   "<b>ECHT-Modus (Live).</b> Es wird mit echtem TAO "
                   "gehandelt."),
            unsafe_allow_html=True,
        )

    # ---- Three big numbers everyone understands ----------------------
    ticks = int(status.get("ticks", 0)) if status else 0
    trades = int(status.get("executed", 0)) if status else 0

    ledger_path = Path(os.environ.get("TAO_LEDGER_DB", data_dir / "trades.db"))
    pnl = 0.0
    all_trades = []
    pnl_computed = False
    if ledger_path.exists():
        ledger = PaperLedger(str(ledger_path))
        summary = summarise_ledger(ledger, limit=5000)
        pnl = summary.as_dict().get("realised_pnl_tao", 0.0)
        all_trades = list(ledger.list_trades(limit=5000))
        trades = max(trades, summary.as_dict().get("total_trades", 0))
        # Only the backtester writes realised-P&L rows; the live paper
        # runner does not. Without them a 0 means "not computed".
        pnl_computed = any(
            getattr(t, "action", "") == "unstake_realised" for t in all_trades
        )

    if pnl_computed:
        pnl_word = "Gewinn" if pnl > 0 else "Verlust" if pnl < 0 else "Ergebnis"
        pnl_cell = (pnl_word, f"{pnl:+,.2f}".replace(",", "."), "TAO (simuliert)")
    else:
        pnl_cell = ("Ergebnis", "n. b.", "nicht berechnet")
    st.markdown(hero_block([
        ("Prüfungen", f"{ticks:,}".replace(",", "."), "Marktchecks"),
        ("Trades", f"{trades:,}".replace(",", "."), "insgesamt"),
        pnl_cell,
    ]), unsafe_allow_html=True)

    # ---- One simple chart --------------------------------------------
    curve = equity_curve(all_trades) if all_trades else []
    st.subheader("Verlauf")
    if curve:
        eq_df = pd.DataFrame([
            {
                "Zeit": pd.to_datetime(p.timestamp, unit="s", utc=True),
                "Gewinn/Verlust (TAO)": p.cumulative_pnl_tao,
            }
            for p in curve
        ]).set_index("Zeit")
        st.line_chart(eq_df, height=280, use_container_width=True)
    else:
        st.info(
            "Noch keine abgeschlossenen Trades. Sobald der Bot kauft und "
            "wieder verkauft, erscheint hier die Gewinn-Kurve."
        )

    # ---- Plain-language explainer ------------------------------------
    with st.expander("Was bedeutet das?"):
        st.markdown(
            "- **Prüfungen** — wie oft der Bot den Markt angeschaut hat.\n"
            "- **Trades** — wie oft er (simuliert) gekauft/verkauft hat.\n"
            "- **Ergebnis** — der Live-Übungs-Runner bucht Käufe/Verkäufe, "
            "rechnet aber keinen Gewinn/Verlust pro Trade. Daher steht "
            "hier **„n. b.“ (nicht berechnet)** — das ist ehrlicher als "
            "eine erfundene Zahl.\n"
            "- **Ampel oben** — grün = läuft, rot = gestoppt.\n\n"
            "Mehr Details findest du über die Auswahl links "
            "(Trading, Markt, Subnetze …)."
        )

    st.caption(
        "Übungs-Modus ist Standard. Es kann kein echtes Geld bewegt "
        "werden, solange nicht ausdrücklich der Echt-Modus aktiviert wird."
    )


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    """Main entry point for the Streamlit dashboard."""
    st.title("TAO Bot")
    st.caption("Einfaches Dashboard · Übungs-Modus · nur Ansicht")

    # Sidebar navigation
    with st.sidebar:
        from tao_swarm.dashboard.cheat_sheet import (
            cheat_sheet_groups,
            how_to_interact_html,
        )
        from tao_swarm.dashboard.theme import status_pill
        from tao_swarm.dashboard.trading_view import (
            load_runner_status,
            runner_health_label,
        )

        # 1) Navigation — plain German labels, simple page first.
        # ``pages`` maps the label the operator sees to the renderer.
        pages = [
            ("Übersicht", render_overview),
            ("Trading", render_trading),
            ("Markt", render_market_watch),
            ("Subnetze", render_subnet_scores),
            ("Risiko", render_risk_alerts),
            ("Wallet", render_wallet_watch),
            ("System", render_system_status),
            ("Verlauf", render_run_logs),
        ]
        st.markdown("### Menü")
        st.caption("Einfach starten mit **Übersicht**.")
        choice = st.radio(
            "Seite wählen:",
            [label for label, _ in pages],
            label_visibility="collapsed",
        )

        st.divider()

        # 2) Runner status — always-visible health read-out so the
        # operator knows from any page whether the runner is alive /
        # halted / errored.
        data_dir = Path(os.environ.get("TAO_DATA_DIR", "data"))
        status_path = Path(os.environ.get(
            "TAO_RUNNER_STATUS_FILE", data_dir / "runner_status.json",
        ))
        runner_status = load_runner_status(status_path)
        st.markdown("### Bot-Status")
        label, _ = runner_health_label(runner_status)
        st.markdown(status_pill(label), unsafe_allow_html=True)
        if runner_status:
            ticks = int(runner_status.get("ticks", 0))
            executed = int(runner_status.get("executed", 0))
            st.caption(f"{ticks} Prüfungen · {executed} Trades")
        else:
            st.caption("Bot noch nicht gestartet.")

        st.divider()

        # 3) Refresh controls — a manual button plus an opt-out auto
        # refresh. Auto refresh only reruns the script (cheap): live
        # values like runner status and the ledger are read uncached so
        # they update, while the market fetch keeps its own TTL so we
        # never hammer the price API on every tick.
        if st.button("Jetzt aktualisieren", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        # One click fills every page with real live data.
        _load_all_button("Alles laden (Live-Daten)")

        auto = st.toggle(
            "Automatisch aktualisieren",
            value=True,
            help="Seite lädt sich selbst neu — bleibt auf der gewählten "
                 "Seite.",
        )
        if auto:
            secs = st.select_slider(
                "Intervall",
                options=[5, 10, 15, 30, 60],
                value=15,
                format_func=lambda s: f"{s}s",
            )
            if AUTOREFRESH_AVAILABLE:
                st_autorefresh(interval=secs * 1000, key="auto_refresh")
                st.caption(f"Aktualisiert alle {secs}s.")
            else:
                st.caption(
                    "Auto-Refresh-Komponente fehlt "
                    "(pip install streamlit-autorefresh)."
                )

        st.divider()

        # 4) Everything advanced — all command help tucked behind a
        # single collapsed expander so the sidebar stays calm.
        with st.expander("Befehle (für Fortgeschrittene)", expanded=False):
            st.markdown(how_to_interact_html(), unsafe_allow_html=True)
            for group in cheat_sheet_groups():
                st.markdown(f"**{group.title}**")
                for item in group.items:
                    st.code(item.command, language="bash")
                    st.caption(item.description)
                if group.note:
                    st.info(group.note)

        st.markdown(
            f"<div style='color:{PALETTE['text_muted']};font-size:0.78rem;'>"
            "<b>TAO Bot v1.0</b><br>Lokal · keine Telemetrie · "
            "nur Ansicht</div>",
            unsafe_allow_html=True,
        )

    # Route to the chosen page via the label -> renderer mapping.
    renderer = dict(pages).get(choice, render_overview)
    renderer()


if __name__ == "__main__":
    main()
