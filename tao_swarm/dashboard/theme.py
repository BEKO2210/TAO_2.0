"""
Premium dashboard theme — custom CSS + helper widgets.

Streamlit's default components are functional but visually
generic. This module ships a single-file theme that:

- Switches typography to a system-font stack with Inter fallback
- Cards-up bare metrics into subtle bordered tiles with hover state
- Adds semantic status pills (ready / running / halted / error)
- Hides Streamlit's own footer + main-menu chrome
- Tightens spacing and rounds corners consistently

Pure presentation — no business logic. Helpers like
``status_pill()`` and ``kpi_card()`` return HTML strings the
caller emits via ``st.markdown(..., unsafe_allow_html=True)``.

Why a separate module
=====================

The CSS lives next to its helpers so theme changes don't bleed
into the page-rendering code in :mod:`tao_swarm.dashboard.app`.
Tests import the helpers and assert on output structure without
needing Streamlit installed.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Color palette — single source of truth so HTML helpers stay in sync
# ---------------------------------------------------------------------------

PALETTE = {
    "bg":         "#0b1220",   # canvas background, deeper than #0d1117
    "bg_card":    "#121a2c",   # card surfaces
    "bg_card_2":  "#1a2540",   # nested / hover state
    "border":     "#2a3553",
    "border_lo":  "#1f2942",
    "text":       "#e6edf3",
    "text_muted": "#9ba6b8",
    "primary":    "#7c5cff",   # purple — accent for active state
    "success":    "#3fb950",
    "warning":    "#d29922",
    "danger":     "#f85149",
    "info":       "#58a6ff",
}

# Semantic status mapping for runner state badges.
STATUS_COLORS = {
    "running": ("success", "✓"),
    "idle":    ("info",    "○"),
    "halted":  ("danger",  "■"),
    "error":   ("warning", "!"),
    "offline": ("muted",   "·"),
}


# ---------------------------------------------------------------------------
# CSS — injected once at app start
# ---------------------------------------------------------------------------

PREMIUM_CSS = f"""
<style>
/* --- Reset Streamlit chrome we don't need --- */
#MainMenu, footer, header[data-testid="stHeader"] {{ visibility: hidden; }}
[data-testid="stToolbar"] {{ display: none !important; }}

/* --- Typography --- */
html, body, [class*="css"] {{
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI",
                 system-ui, sans-serif !important;
    font-feature-settings: "tnum" 1, "ss01" 1;
}}
.stApp {{
    background-color: {PALETTE["bg"]};
    color: {PALETTE["text"]};
}}

/* Headers — tighter, more deliberate hierarchy */
h1 {{
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    color: {PALETTE["text"]} !important;
    margin-top: 0.5rem !important;
}}
h2 {{
    font-weight: 600 !important;
    letter-spacing: -0.01em !important;
    color: {PALETTE["text"]} !important;
    margin-top: 1.5rem !important;
    border-bottom: 1px solid {PALETTE["border_lo"]};
    padding-bottom: 0.4rem;
}}
h3 {{
    font-weight: 600 !important;
    color: {PALETTE["text"]} !important;
    font-size: 1.05rem !important;
    margin-top: 1rem !important;
}}

/* --- Sidebar --- */
[data-testid="stSidebar"] {{
    background-color: {PALETTE["bg_card"]};
    border-right: 1px solid {PALETTE["border_lo"]};
}}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {{
    color: {PALETTE["text_muted"]};
}}

/* --- Metric cards --- */
[data-testid="stMetric"] {{
    background-color: {PALETTE["bg_card"]};
    border: 1px solid {PALETTE["border_lo"]};
    border-radius: 12px;
    padding: 16px 18px;
    transition: border-color 120ms ease, transform 120ms ease;
}}
[data-testid="stMetric"]:hover {{
    border-color: {PALETTE["border"]};
}}
[data-testid="stMetricLabel"] {{
    color: {PALETTE["text_muted"]} !important;
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}}
[data-testid="stMetricValue"] {{
    color: {PALETTE["text"]} !important;
    font-weight: 700 !important;
    font-size: 1.55rem !important;
    font-feature-settings: "tnum" 1;
}}
[data-testid="stMetricDelta"] {{ font-weight: 600 !important; }}

/* --- Buttons --- */
.stButton > button {{
    background-color: {PALETTE["bg_card_2"]};
    color: {PALETTE["text"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 10px;
    font-weight: 500;
    transition: all 150ms ease;
}}
.stButton > button:hover {{
    border-color: {PALETTE["primary"]};
    color: {PALETTE["primary"]};
    transform: translateY(-1px);
}}
.stButton > button:active {{ transform: translateY(0); }}

/* --- Selectbox + inputs --- */
[data-baseweb="select"] {{
    background-color: {PALETTE["bg_card"]} !important;
    border-radius: 10px !important;
}}
.stTextInput input, .stNumberInput input {{
    background-color: {PALETTE["bg_card"]} !important;
    border: 1px solid {PALETTE["border_lo"]} !important;
    color: {PALETTE["text"]} !important;
    border-radius: 10px !important;
}}

/* --- Tabs --- */
.stTabs [data-baseweb="tab-list"] {{
    background-color: {PALETTE["bg_card"]};
    border-radius: 12px;
    padding: 4px;
    gap: 4px;
}}
.stTabs [data-baseweb="tab"] {{
    background-color: transparent;
    color: {PALETTE["text_muted"]};
    border-radius: 8px;
    padding: 8px 14px;
}}
.stTabs [aria-selected="true"] {{
    background-color: {PALETTE["bg_card_2"]} !important;
    color: {PALETTE["text"]} !important;
}}

/* --- DataFrame / table --- */
[data-testid="stDataFrame"] {{
    border: 1px solid {PALETTE["border_lo"]};
    border-radius: 12px;
    overflow: hidden;
}}

/* --- Alerts (info / warning / error / success) --- */
[data-testid="stAlert"] {{
    border-radius: 10px !important;
    border-left-width: 3px !important;
    padding: 12px 14px !important;
}}

/* --- Custom status pills (rendered via status_pill helper) --- */
.tao-pill {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    border: 1px solid transparent;
}}
.tao-pill-success {{
    color: {PALETTE["success"]};
    background-color: rgba(63,185,80,0.14);
    border-color: rgba(63,185,80,0.25);
}}
.tao-pill-warning {{
    color: {PALETTE["warning"]};
    background-color: rgba(210,153,34,0.14);
    border-color: rgba(210,153,34,0.25);
}}
.tao-pill-danger {{
    color: {PALETTE["danger"]};
    background-color: rgba(248,81,73,0.14);
    border-color: rgba(248,81,73,0.25);
}}
.tao-pill-info {{
    color: {PALETTE["info"]};
    background-color: rgba(88,166,255,0.14);
    border-color: rgba(88,166,255,0.25);
}}
.tao-pill-muted {{
    color: {PALETTE["text_muted"]};
    background-color: rgba(155,166,184,0.10);
    border-color: rgba(155,166,184,0.18);
}}

/* --- Hero KPI block: bigger numbers, no card --- */
.tao-hero {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 16px;
    margin: 8px 0 20px 0;
}}
.tao-hero-cell {{
    background-color: {PALETTE["bg_card"]};
    border: 1px solid {PALETTE["border_lo"]};
    border-radius: 14px;
    padding: 18px 20px;
}}
.tao-hero-label {{
    color: {PALETTE["text_muted"]};
    font-size: 0.74rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 6px;
}}
.tao-hero-value {{
    color: {PALETTE["text"]};
    font-weight: 700;
    font-size: 1.75rem;
    line-height: 1.1;
    font-feature-settings: "tnum" 1;
}}
.tao-hero-sub {{
    color: {PALETTE["text_muted"]};
    font-size: 0.78rem;
    margin-top: 4px;
}}

/* --- Section banner (info / warn / danger) --- */
.tao-banner {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-radius: 12px;
    border-left: 3px solid;
    margin: 10px 0 16px 0;
    font-size: 0.92rem;
}}
.tao-banner-success {{ background-color: rgba(63,185,80,0.08); border-color: {PALETTE["success"]}; }}
.tao-banner-warning {{ background-color: rgba(210,153,34,0.08); border-color: {PALETTE["warning"]}; }}
.tao-banner-danger  {{ background-color: rgba(248,81,73,0.10); border-color: {PALETTE["danger"]};  }}
.tao-banner-info    {{ background-color: rgba(88,166,255,0.08); border-color: {PALETTE["info"]};    }}
</style>
"""


# ---------------------------------------------------------------------------
# HTML helpers (testable; return strings)
# ---------------------------------------------------------------------------

def status_pill(state: str) -> str:
    """Render a runner-state pill for embedding in markdown.

    Maps ``running / idle / halted / error / offline`` to one of the
    semantic colour classes defined in :data:`PREMIUM_CSS`.
    Unknown states fall back to the muted style.
    """
    state = (state or "").lower().strip()
    info = STATUS_COLORS.get(state)
    if info is None:
        info = ("muted", "·")
    cls, glyph = info
    label = state.upper() if state else "OFFLINE"
    return (
        f'<span class="tao-pill tao-pill-{cls}">'
        f'<span aria-hidden="true">{glyph}</span> {label}'
        '</span>'
    )


def hero_block(cells: list[tuple[str, str, str | None]]) -> str:
    """Render a hero KPI grid.

    Args:
        cells: list of ``(label, value, sub)`` triples. ``sub`` may
            be ``None`` to omit the secondary line.
    """
    inner_parts: list[str] = []
    for label, value, sub in cells:
        sub_html = (
            f'<div class="tao-hero-sub">{sub}</div>' if sub else ""
        )
        inner_parts.append(
            '<div class="tao-hero-cell">'
            f'<div class="tao-hero-label">{label}</div>'
            f'<div class="tao-hero-value">{value}</div>'
            f'{sub_html}'
            '</div>'
        )
    return '<div class="tao-hero">' + "".join(inner_parts) + "</div>"


def banner(kind: str, text: str) -> str:
    """Render a coloured banner. ``kind`` ∈ {success, warning, danger, info}."""
    if kind not in ("success", "warning", "danger", "info"):
        kind = "info"
    return f'<div class="tao-banner tao-banner-{kind}">{text}</div>'


def inject(st: Any) -> None:
    """Inject the premium CSS into a Streamlit page.

    Pass the Streamlit module (``import streamlit as st``); we don't
    import it at module level so this file is unit-testable without
    Streamlit installed.
    """
    st.markdown(PREMIUM_CSS, unsafe_allow_html=True)
