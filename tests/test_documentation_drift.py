"""
Regression: ``DocumentationAgent`` must not drift between its
README and KIMI agent lists, and must cover every agent that
actually exists in ``src/agents/``.

The audit (2026-05-09) flagged the agent's two hand-typed lists as
a guaranteed drift source. PR #N consolidated them into a single
``_AGENT_DESCRIPTIONS`` table plus a live discovery pass over
``src/agents/``. These tests lock that in:

1. ``_discover_agent_names`` returns the same set as the static
   ``_AGENT_DESCRIPTIONS`` keys (no agent missing a description,
   no description without an agent).
2. ``_list_agents`` and ``_get_kimi_agents`` cover the same agents
   in the same order — the two views can't drift.
3. Every line in both outputs has a non-trivial description (not
   "(no description)").
"""

from __future__ import annotations

import re

from tao_swarm.agents.documentation_agent import DocumentationAgent


def _agent_names_from_line_block(rendered: str) -> list[str]:
    """Extract the agent name from each rendered line.

    README lines look like ``- **<name>**: <desc>``; KIMI lines look
    like ``- <name>: <desc>``. Pull the bare name in either shape.
    """
    names: list[str] = []
    for line in rendered.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        m = re.match(r"^- \*?\*?(?P<name>[a-z_]+)\*?\*?:", line)
        assert m, f"unexpected line shape: {line!r}"
        names.append(m.group("name"))
    return names


def test_discovery_matches_description_table_exactly():
    agent = DocumentationAgent({})
    discovered = set(agent._discover_agent_names())
    described = set(agent._AGENT_DESCRIPTIONS.keys())
    missing_desc = discovered - described
    extra_desc = described - discovered
    assert not missing_desc, (
        f"agent(s) discovered in src/agents/ but missing from "
        f"DocumentationAgent._AGENT_DESCRIPTIONS: {sorted(missing_desc)}"
    )
    assert not extra_desc, (
        f"description entries with no matching agent file: "
        f"{sorted(extra_desc)}"
    )


def test_readme_and_kimi_lists_cover_same_agents():
    agent = DocumentationAgent({})
    readme_names = _agent_names_from_line_block(agent._list_agents())
    kimi_names = _agent_names_from_line_block(agent._get_kimi_agents())
    assert readme_names == kimi_names, (
        f"README and KIMI agent lists drifted:\n"
        f"  README: {readme_names}\n"
        f"  KIMI  : {kimi_names}"
    )


def test_every_rendered_line_has_real_description():
    agent = DocumentationAgent({})
    for label, rendered in (
        ("README", agent._list_agents()),
        ("KIMI", agent._get_kimi_agents()),
    ):
        assert "(no description)" not in rendered, (
            f"{label} list contains a fallback '(no description)' — "
            f"every agent must have a description in _AGENT_DESCRIPTIONS"
        )
