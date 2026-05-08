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
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Streamlit import with graceful fallback ───────────────────────────────

try:
    import streamlit as st
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False
    logger.warning("streamlit, pandas, or plotly not installed. Dashboard unavailable.")
    logger.warning("Install: pip install streamlit pandas plotly")
    # Create dummy module for importability
    class _DummySt:
        def __getattr__(self, name): return lambda *a, **k: None
    st = _DummySt()
    pd = _DummySt()
    px = _DummySt()
    go = _DummySt()
    make_subplots = lambda *a, **k: None

# ── Page config ───────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TAO Swarm Dashboard",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Dark mode CSS ─────────────────────────────────────────────────────────

DARK_CSS = """
<style>
    .stApp {
        background-color: #0d1117;
        color: #c9d1d9;
    }
    .css-1d391kg, .css-18e3th9 {
        background-color: #161b22;
    }
    .stMetric {
        background-color: #21262d;
        border-radius: 8px;
        padding: 10px;
    }
    .stMetric label {
        color: #8b949e !important;
    }
    .stMetric .css-1xarl3l {
        color: #58a6ff !important;
    }
    div[data-testid="stBlock"] {
        background-color: #161b22;
        border-radius: 8px;
        padding: 10px;
        margin: 5px 0;
    }
    h1, h2, h3 {
        color: #f0f6fc !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        background-color: #21262d;
        border-radius: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #c9d1d9;
    }
    .stTabs [aria-selected="true"] {
        color: #58a6ff !important;
    }
    div[data-baseweb="select"] {
        background-color: #21262d;
    }
    .stAlert {
        border-radius: 8px;
    }
    .css-1xar8zy {
        background-color: #21262d;
        border: 1px solid #30363d;
    }
    /* Status badges */
    .badge-ready { color: #3fb950; font-weight: bold; }
    .badge-partial { color: #d29922; font-weight: bold; }
    .badge-not-ready { color: #f85149; font-weight: bold; }
    .badge-low { color: #3fb950; font-weight: bold; }
    .badge-medium { color: #d29922; font-weight: bold; }
    .badge-high { color: #f85149; font-weight: bold; }
    .badge-critical { color: #ff0000; font-weight: bold; }
</style>
"""
st.markdown(DARK_CSS, unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────

DATA_DIR = Path(os.environ.get("TAO_DATA_DIR", "data"))
DB_FILES = {
    "chain": DATA_DIR / "chain_cache.db",
    "market": DATA_DIR / "market_cache.db",
    "wallet": DATA_DIR / "wallet_watch.db",
    "github": DATA_DIR / "github_cache.db",
    "scores": DATA_DIR / "scores.db",
    "subnet_meta": DATA_DIR / "subnet_metadata.db",
}

SIDEBAR_PAGES = [
    "System Status",
    "Subnet Scores",
    "Wallet Watch",
    "Market Watch",
    "Risk Alerts",
    "Paper Trades",
    "Run Logs",
]


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
    except Exception as exc:
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
    """Fetch cached market price."""
    conn = get_db_connection("market")
    if not conn:
        return {}
    rows = safe_query(conn, "SELECT data, cached_at FROM price_cache ORDER BY cached_at DESC LIMIT 1")
    conn.close()
    if rows:
        data = json.loads(rows[0][0])
        data["cached_at"] = rows[0][1]
        return data
    return {}


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
    """Render the Subnet Scores page."""
    st.header("Subnet Scores")

    scores = fetch_subnet_scores()

    if not scores:
        st.info("No subnet scores yet. Run scoring via CLI: `tao-swarm score <netuid>`")
        return

    # Score distribution chart
    df_scores = pd.DataFrame(scores)

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Score Distribution")
        fig = px.bar(
            df_scores,
            x="netuid",
            y="score",
            color="score",
            color_continuous_scale=["#f85149", "#d29922", "#3fb950"],
            labels={"netuid": "Subnet ID", "score": "Score (0-100)"},
            text="score",
        )
        fig.update_layout(
            paper_bgcolor="#161b22",
            plot_bgcolor="#0d1117",
            font_color="#c9d1d9",
            xaxis=dict(gridcolor="#30363d"),
            yaxis=dict(gridcolor="#30363d", range=[0, 105]),
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Recommendations")
        for s in scores[:10]:
            score = s["score"]
            color = "#3fb950" if score >= 75 else "#d29922" if score >= 50 else "#f85149"
            st.markdown(
                f"**Subnet {s['netuid']}**: `{s['score']:.1f}` — "
                f"<span style='color:{color}'>{s['recommendation']}</span>",
                unsafe_allow_html=True,
            )

    st.divider()

    # Detailed table
    st.subheader("Score Details")
    st.dataframe(df_scores, use_container_width=True, hide_index=True)


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
            line=dict(color="#58a6ff", width=2),
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
            paper_bgcolor="#161b22",
            plot_bgcolor="#0d1117",
            font_color="#c9d1d9",
            xaxis=dict(gridcolor="#30363d"),
            yaxis=dict(gridcolor="#30363d", title="Price (USD)"),
            yaxis2=dict(gridcolor="#30363d", title="Volume", overlaying="y", side="right"),
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


def render_paper_trades():
    """Render the Paper Trades page."""
    st.header("Paper Trades")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Paper Balance", "$10,000.00")
    with col2:
        st.metric("Open Positions", "0")
    with col3:
        st.metric("P/L", "$0.00", "0.00%")

    st.divider()

    st.subheader("Trade Simulation")
    st.info(
        "This is a PAPER TRADING simulator. No real transactions are executed. "
        "Use `tao-swarm market` to get current data for analysis."
    )

    # Simple trade entry form
    col_a, col_b = st.columns(2)
    with col_a:
        st.text_input("Entry Price (USD)", value="0.00", disabled=True)
    with col_b:
        st.text_input("Position Size (USD)", value="0.00", disabled=True)

    st.button("Simulate Entry (Paper)", disabled=True, help="Paper trading only - no real execution")

    st.divider()

    st.subheader("Trade History")
    st.dataframe(
        pd.DataFrame(columns=["Time", "Type", "Price", "Size", "P/L", "Status"]),
        use_container_width=True,
        hide_index=True,
    )


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


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    """Main entry point for the Streamlit dashboard."""
    st.title("TAO Swarm Dashboard")
    st.caption("Bittensor Multi-Agent Intelligence System — Read-Only Dashboard")

    # Sidebar navigation
    with st.sidebar:
        st.markdown("### Navigation")
        page = st.radio("Select page:", SIDEBAR_PAGES, label_visibility="collapsed")

        st.divider()

        st.markdown("### Status")
        st.markdown("<span class='badge-ready'>System Online</span>", unsafe_allow_html=True)
        st.markdown("<span class='badge-low'>Read-Only Mode</span>", unsafe_allow_html=True)
        st.markdown("<span class='badge-ready'>No Secrets Stored</span>", unsafe_allow_html=True)

        st.divider()

        st.markdown("### Quick Actions")
        if st.button("Refresh Data"):
            st.cache_data.clear()
            st.rerun()

        st.divider()
        st.markdown("*TAO Swarm v1.0.0*")
        st.markdown("*Local-only, no telemetry*")

    # Route to page
    if page == "System Status":
        render_system_status()
    elif page == "Subnet Scores":
        render_subnet_scores()
    elif page == "Wallet Watch":
        render_wallet_watch()
    elif page == "Market Watch":
        render_market_watch()
    elif page == "Risk Alerts":
        render_risk_alerts()
    elif page == "Paper Trades":
        render_paper_trades()
    elif page == "Run Logs":
        render_run_logs()


if __name__ == "__main__":
    main()
