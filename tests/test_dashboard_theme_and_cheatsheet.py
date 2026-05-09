"""
Tests for the premium-theme + cheat-sheet helpers added in PR 2P.

The Streamlit-rendered look-and-feel can't be fully verified in
a headless test, but the helper functions ARE pure HTML / data
constructors — those we can lock in. The CI confirms:

- :func:`status_pill` returns the expected CSS classes per state.
- :func:`hero_block` builds well-formed grid markup.
- :func:`banner` only accepts known semantic kinds, with safe
  fallback to ``info``.
- :data:`PREMIUM_CSS` actually contains the class definitions the
  helpers reference (no orphan classes that would render unstyled).
- :func:`cheat_sheet_groups` returns deterministic, non-empty,
  copy-paste-safe data.
- :func:`how_to_interact_html` mentions every interaction surface
  (CLI, dashboard, files) so the operator doesn't miss one.
"""

from __future__ import annotations

import pytest

from tao_swarm.dashboard.cheat_sheet import (
    CheatGroup,
    CheatItem,
    cheat_sheet_groups,
    how_to_interact_html,
)
from tao_swarm.dashboard.theme import (
    PALETTE,
    PREMIUM_CSS,
    STATUS_COLORS,
    banner,
    hero_block,
    status_pill,
)

# ---------------------------------------------------------------------------
# Theme — palette + CSS sanity
# ---------------------------------------------------------------------------

def test_palette_has_required_keys():
    """Every helper that reads PALETTE depends on these keys."""
    required = {
        "bg", "bg_card", "bg_card_2", "border", "border_lo",
        "text", "text_muted",
        "primary", "success", "warning", "danger", "info",
    }
    assert required.issubset(set(PALETTE))


def test_palette_values_are_hex_colours():
    for k, v in PALETTE.items():
        assert isinstance(v, str), k
        assert v.startswith("#"), f"{k} = {v}"
        assert len(v) in (4, 7), f"{k} = {v}"


def test_premium_css_defines_all_pill_classes():
    """The status_pill helper emits these classes — they must
    actually be styled in the CSS or the page renders unstyled."""
    for cls in ("tao-pill", "tao-pill-success", "tao-pill-warning",
                "tao-pill-danger", "tao-pill-info", "tao-pill-muted"):
        assert f".{cls}" in PREMIUM_CSS or cls in PREMIUM_CSS


def test_premium_css_defines_hero_classes():
    for cls in ("tao-hero", "tao-hero-cell", "tao-hero-label",
                "tao-hero-value", "tao-hero-sub"):
        assert cls in PREMIUM_CSS


def test_premium_css_defines_banner_classes():
    for cls in ("tao-banner", "tao-banner-success", "tao-banner-warning",
                "tao-banner-danger", "tao-banner-info"):
        assert cls in PREMIUM_CSS


def test_premium_css_hides_streamlit_chrome():
    # The "remove Streamlit footer" rule must be present.
    assert "footer" in PREMIUM_CSS
    assert "MainMenu" in PREMIUM_CSS


# ---------------------------------------------------------------------------
# status_pill
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state,expected_class", [
    ("running", "tao-pill-success"),
    ("idle",    "tao-pill-info"),
    ("halted",  "tao-pill-danger"),
    ("error",   "tao-pill-warning"),
    ("offline", "tao-pill-muted"),
])
def test_status_pill_known_states_get_correct_class(state, expected_class):
    html = status_pill(state)
    assert expected_class in html


def test_status_pill_unknown_state_falls_back_to_muted():
    html = status_pill("foo-bar-bogus")
    assert "tao-pill-muted" in html


def test_status_pill_handles_none_and_empty():
    assert "tao-pill" in status_pill(None)  # type: ignore[arg-type]
    assert "tao-pill" in status_pill("")


def test_status_pill_uppercases_label():
    html = status_pill("running")
    assert "RUNNING" in html


def test_status_colors_mapping_is_consistent():
    """STATUS_COLORS keys must round-trip through status_pill."""
    for state in STATUS_COLORS:
        html = status_pill(state)
        cls, _ = STATUS_COLORS[state]
        assert f"tao-pill-{cls}" in html


# ---------------------------------------------------------------------------
# hero_block
# ---------------------------------------------------------------------------

def test_hero_block_renders_each_cell():
    html = hero_block([
        ("Ticks", "12", None),
        ("P&L", "+1.234", "TAO"),
    ])
    assert html.count("tao-hero-cell") == 2
    assert "Ticks" in html
    assert "P&L" in html
    assert "TAO" in html


def test_hero_block_omits_sub_when_none():
    html = hero_block([("Label", "1", None)])
    assert "tao-hero-sub" not in html


def test_hero_block_includes_sub_when_provided():
    html = hero_block([("Label", "1", "secondary")])
    assert "tao-hero-sub" in html
    assert "secondary" in html


def test_hero_block_empty_input():
    html = hero_block([])
    assert "tao-hero" in html
    assert "tao-hero-cell" not in html


# ---------------------------------------------------------------------------
# banner
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["success", "warning", "danger", "info"])
def test_banner_uses_correct_class(kind):
    html = banner(kind, "hello")
    assert f"tao-banner-{kind}" in html
    assert "hello" in html


def test_banner_unknown_kind_falls_back_to_info():
    html = banner("nonsense", "x")
    assert "tao-banner-info" in html


# ---------------------------------------------------------------------------
# cheat_sheet_groups
# ---------------------------------------------------------------------------

def test_cheat_sheet_groups_returns_non_empty_list():
    groups = cheat_sheet_groups()
    assert len(groups) >= 5
    assert all(isinstance(g, CheatGroup) for g in groups)


def test_cheat_sheet_every_group_has_at_least_one_item():
    for group in cheat_sheet_groups():
        assert len(group.items) >= 1, f"empty group: {group.title}"
        for item in group.items:
            assert isinstance(item, CheatItem)
            assert item.command, f"empty command in {group.title}"
            assert item.description, f"empty description in {group.title}"


def test_cheat_sheet_includes_paper_and_live_groups():
    titles = [g.title for g in cheat_sheet_groups()]
    assert any("Paper" in t for t in titles), titles
    assert any("Live" in t for t in titles), titles
    assert any("Keystore" in t for t in titles), titles


def test_cheat_sheet_live_group_carries_warning_note():
    """The live-trading group MUST mention the typed-confirmation
    safety phrase — otherwise the cheat-sheet would imply the
    operator can yolo it."""
    live = next(
        g for g in cheat_sheet_groups()
        if g.title.startswith("Live-Trading")
    )
    assert live.note, "Live-Trading group must carry a warning note"
    assert "I UNDERSTAND" in live.note


def test_cheat_sheet_keystore_group_warns_about_recovery():
    keystore = next(
        g for g in cheat_sheet_groups()
        if "Keystore" in g.title
    )
    assert keystore.note
    assert "recovery" in keystore.note.lower() or "Recovery" in keystore.note


def test_cheat_sheet_groups_have_unique_titles():
    titles = [g.title for g in cheat_sheet_groups()]
    assert len(titles) == len(set(titles))


def test_cheat_sheet_group_as_dict_serialisable():
    import json
    for group in cheat_sheet_groups():
        json.dumps(group.as_dict())


def test_cheat_sheet_commands_are_safe_singletons():
    """No multi-line commands in the cheat-sheet (would break copy
    paste in many terminals) — multi-line forms use backslash
    continuations rendered on one logical line."""
    for group in cheat_sheet_groups():
        for item in group.items:
            # We allow backslash-continued commands but no actual
            # newlines mid-string.
            assert "\n" not in item.command, item.command


# ---------------------------------------------------------------------------
# how_to_interact_html
# ---------------------------------------------------------------------------

def test_how_to_interact_mentions_all_three_surfaces():
    html = how_to_interact_html().lower()
    assert "cli" in html
    assert "dashboard" in html
    # files = kill switch / status / ledger
    assert "kill" in html
    assert "status" in html
    assert "ledger" in html


def test_how_to_interact_explicitly_no_chat():
    """The intro must communicate 'kein Chat-NLU, bewusst' so the
    operator doesn't waste time looking for a chat box."""
    html = how_to_interact_html()
    assert "Chat" in html or "NLU" in html
