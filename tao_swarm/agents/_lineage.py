"""
Tiny helper for agents that want to pull from the upstream
``AgentContext`` bus.

The pattern across every "downstream" agent is the same:

1. Maybe-grab the bus (it might not be wired up — single-agent
   tests, ad-hoc invocations).
2. For each expected upstream key, fetch it; record whether it
   was present.
3. Return a small dict of ``{key: value_or_default}`` plus a
   ``upstream_seen`` list the agent stamps into ``_meta``.

This module owns that pattern so individual agents don't drift
into 9 slightly different implementations of the same idea. It's
deliberately read-only and side-effect-free; the orchestrator's
``AgentContext`` already does deep-copy on read.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class UpstreamPull:
    """Result of one round of upstream-context pulls.

    ``values`` maps each requested key to what came back from the
    bus (or the supplied default). ``seen`` lists only the keys
    that resolved to non-default values — i.e. the keys whose
    upstream agent had actually published. Agents stamp ``seen``
    into their output's ``_meta.upstream_seen`` so operators can
    tell whether the run was contextualised or stand-alone.
    """

    values: dict[str, Any] = field(default_factory=dict)
    seen: list[str] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def has(self, key: str) -> bool:
        return key in self.seen

    def as_meta(self) -> dict[str, Any]:
        return {"upstream_seen": list(self.seen)}


def pull_upstream(
    agent: Any,
    requested: dict[str, str | None],
) -> UpstreamPull:
    """Pull a fixed list of keys from ``agent.context``.

    Args:
        agent: The agent instance. Must have an ``AgentContext`` at
            ``self.context`` after orchestrator-driven init; if the
            attribute is missing or ``None`` we treat that as "no
            upstream" and return empty values.
        requested: Mapping of ``label -> dotted_context_key``. The
            label is a free-form name the agent uses internally
            (e.g. ``"hardware"``); the value is the bus key
            (e.g. ``"system_check_agent.hardware_report"``). A
            ``None`` value means "use the label as the key".

    Returns:
        :class:`UpstreamPull` with values + seen list.
    """
    out = UpstreamPull()
    ctx = getattr(agent, "context", None)
    if ctx is None:
        return out
    for label, key in requested.items():
        bus_key = key if key else label
        try:
            value = ctx.get(bus_key)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("upstream pull failed for %s: %s", bus_key, exc)
            value = None
        out.values[label] = value
        if value is not None:
            out.seen.append(label)
    return out
