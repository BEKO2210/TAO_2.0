"""
Agent capabilities (skills) declaration — LLM-free orchestration pattern.

Each agent can declare a module-level ``AGENT_CAPABILITIES`` list of
``Capability`` entries. The TaskRouter discovers them on
``register_agent`` and adds them to its task→agent map automatically;
the dashboard / CLI can render a self-describing "what can the swarm
do?" view without any hand-maintained registry.

This is the LLM-free analogue of:

- Claude Agent SDK skills
- AutoGen tool annotations
- CrewAI's "task" registration

The router still uses pure dict lookup — no LLM picks the agent —
but agents stop being implicit and become **self-describing**.

Usage in an agent module:

    from tao_swarm.orchestrator.capabilities import Capability

    AGENT_NAME = "subnet_scoring_agent"
    AGENT_VERSION = "1.0.0"
    AGENT_CAPABILITIES = [
        Capability(
            task_type="subnet_scoring",
            description="Score a subnet across 15 weighted criteria.",
            inputs={"subnet_id": "int", "params": "dict | None"},
            outputs={"total_score": "float", "breakdown": "dict",
                     "recommendation": "dict"},
        ),
    ]

Plug-ins follow the same pattern. The plug-in loader picks them up
just like built-ins.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Capability:
    """
    A single thing an agent can do.

    Fields are deliberately small — this is metadata, not a schema
    enforcement layer. ``inputs`` / ``outputs`` are free-form
    ``dict[str, str]`` so agents can describe their shape without
    being locked into a specific type system.
    """

    task_type: str
    description: str = ""
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    # Free-form tags so the dashboard / CLI can group capabilities.
    # E.g. ``tags=["chain-read", "scoring"]`` for the subnet scorer.
    tags: list[str] = field(default_factory=list)
    # Optional version pinning so a router can warn on stale
    # task_type expectations after an agent's capability changes.
    version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def discover_capabilities(agent_or_module: Any) -> list[Capability]:
    """
    Pull ``AGENT_CAPABILITIES`` from an agent instance, its class, or
    the defining module.

    Returns ``[]`` if nothing is declared. Items that aren't already
    ``Capability`` instances get coerced via ``Capability(**item)`` so
    plug-in authors can declare them as plain dicts if they prefer.

    Per-instance precedence over class over module — same resolution
    order the orchestrator uses for ``AGENT_NAME``.
    """
    import sys

    sources: list[Any] = [agent_or_module, type(agent_or_module)]
    module = sys.modules.get(getattr(type(agent_or_module), "__module__", ""))
    if module is not None:
        sources.append(module)

    declared: list[Any] = []
    for src in sources:
        candidate = getattr(src, "AGENT_CAPABILITIES", None)
        if candidate:
            declared = list(candidate)
            break

    out: list[Capability] = []
    for item in declared:
        if isinstance(item, Capability):
            out.append(item)
        elif isinstance(item, dict):
            try:
                out.append(Capability(**item))
            except TypeError as exc:
                logger.warning(
                    "Invalid Capability dict on %r: %s — %s",
                    agent_or_module, item, exc,
                )
        else:
            logger.warning(
                "Skipping AGENT_CAPABILITIES entry of type %s on %r — "
                "expected Capability or dict",
                type(item).__name__, agent_or_module,
            )
    return out
