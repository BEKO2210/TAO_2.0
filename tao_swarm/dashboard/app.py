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

SIDEBAR_PAGES = [
    "System Status",
    "Subnet Scores",
    "Wallet Watch",
    "Market Watch",
    "Risk Alerts",
    "Trading",
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
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("State", label.upper())
        with col2:
            st.metric("Strategy", str(status.get("strategy", "—")))
        with col3:
            mode = "LIVE" if not status.get("paper", True) else "PAPER"
            st.metric("Mode", mode)
        with col4:
            ts = status.get("last_tick_ts")
            if ts:
                tick_str = datetime.fromtimestamp(
                    float(ts), tz=timezone.utc,
                ).strftime("%H:%M:%S")
            else:
                tick_str = "never"
            st.metric("Last tick", tick_str)

        cola, colb, colc, cold = st.columns(4)
        with cola:
            st.metric("Ticks", int(status.get("ticks", 0)))
        with colb:
            st.metric("Executed", int(status.get("executed", 0)))
        with colc:
            st.metric("Refused", int(status.get("refused", 0)))
        with cold:
            st.metric("Errors", int(status.get("errors", 0)))

        if status.get("halted_reason"):
            st.error(f"HALTED: {status['halted_reason']}")
        elif status.get("last_error"):
            st.warning(f"Last error: {status['last_error']}")

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
                st.toast("Kill switch triggered", icon="⛔")
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

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total trades", s["total_trades"])
    with col2:
        st.metric("Paper", s["paper_trades"])
    with col3:
        st.metric("Live", s["live_trades"])
    with col4:
        st.metric("Failed", s["failed_trades"])

    st.metric(
        "Realised P&L (TAO)",
        f"{s['realised_pnl_tao']:+.4f}",
    )

    if s["distinct_strategies"]:
        st.caption(
            "Strategies present: " + ", ".join(s["distinct_strategies"])
        )

    # ---- Equity curve ----------------------------------------------------
    all_trades = list(ledger.list_trades(strategy=selected_strategy, limit=2000))
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
    elif page == "Trading":
        render_trading()
    elif page == "Run Logs":
        render_run_logs()


if __name__ == "__main__":
    main()
