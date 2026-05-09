"""
Plug-in loader for the TAO/Bittensor Multi-Agent Swarm.

User-defined agents can live OUTSIDE this repo and be loaded into
the swarm at runtime via two mechanisms:

1. **Path-based discovery** (zero-packaging — drop a ``*_agent.py``
   file in a folder, set ``TAO_PLUGIN_PATHS`` or pass ``paths=``).
2. **Entry-point discovery** (production — install the user's
   package via pip, declare it in ``[project.entry-points."tao.agents"]``
   in ``pyproject.toml``).

Either way, the plug-in must obey the SPEC.md agent contract:
``run`` / ``get_status`` / ``validate_input`` methods plus
``AGENT_NAME`` / ``AGENT_VERSION`` constants. The loader validates
that contract before registration; non-compliant plug-ins are
skipped with a logged warning, never silently registered.

Plug-ins go through the **same** ApprovalGate as built-ins —
loading a plug-in does not raise its trust level. Plug-ins also
receive the shared ``AgentContext`` automatically (just like
built-ins), so they can pull system_check reports etc. without
extra wiring.

A worked example ships in ``examples/subnet_repo_health/``.

Usage
-----

Path-based, programmatic::

    from src.orchestrator import SwarmOrchestrator, load_plugins
    orch = SwarmOrchestrator({"use_mock_data": True})
    summary = load_plugins(orch, paths=["examples/subnet_repo_health"])
    print(summary)
    # → {"loaded": ["subnet_repo_health_agent"], "skipped": [...], "errors": [...]}

Path-based, env var::

    TAO_PLUGIN_PATHS=/home/user/my-agents:/path/two python -m src.cli.tao_swarm ...

Entry-point-based (user's own ``pyproject.toml``)::

    [project.entry-points."tao.agents"]
    subnet_repo_health = "subnet_repo_health_agent:SubnetRepoHealthAgent"

Then::

    summary = load_plugins(orch, entry_point_group="tao.agents")
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# When the same agent name comes from two sources, decide what wins.
ON_CONFLICT_SKIP = "skip"        # leave the existing one in place
ON_CONFLICT_REPLACE = "replace"  # newer wins
ON_CONFLICT_ERROR = "error"      # raise

_REQUIRED_METHODS = ("run", "get_status", "validate_input")


@dataclass
class PluginLoadSummary:
    """Structured report of a plug-in load pass."""

    loaded: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "loaded": list(self.loaded),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


def load_plugins(
    orchestrator: Any,
    paths: Iterable[str | Path] | None = None,
    entry_point_group: str | None = "tao.agents",
    on_conflict: str = ON_CONFLICT_SKIP,
    config: dict | None = None,
) -> PluginLoadSummary:
    """
    Discover and register external agent plug-ins.

    Args:
        orchestrator: A ``SwarmOrchestrator`` (or anything that
            quacks like one — must expose ``register_agent`` and
            an ``agents`` dict).
        paths: Iterable of directories to scan for ``*_agent.py``
            files. ``None`` means "use ``TAO_PLUGIN_PATHS`` env var,
            colon-separated".
        entry_point_group: ``[project.entry-points]`` group name
            to scan via ``importlib.metadata``. ``None`` to skip.
        on_conflict: What to do when a plug-in's ``AGENT_NAME``
            is already registered. One of ``ON_CONFLICT_SKIP``,
            ``ON_CONFLICT_REPLACE``, ``ON_CONFLICT_ERROR``.
        config: Config dict passed to each plug-in's ``__init__``.
            Defaults to the orchestrator's own config when present.

    Returns:
        A ``PluginLoadSummary`` listing what loaded, what was
        skipped (e.g. duplicates or contract violations), and what
        raised.
    """
    summary = PluginLoadSummary()

    # Resolve path list: explicit > env var > nothing
    if paths is None:
        env_paths = os.environ.get("TAO_PLUGIN_PATHS", "").strip()
        paths = [p for p in env_paths.split(os.pathsep) if p]
    if isinstance(paths, (str, Path)):
        paths = [paths]
    paths = [Path(p).expanduser().resolve() for p in paths]

    # Default per-plugin config to the orchestrator's own config so
    # plug-ins inherit ``use_mock_data`` etc. without extra wiring.
    plugin_config = config
    if plugin_config is None and hasattr(orchestrator, "config"):
        plugin_config = dict(orchestrator.config)
    plugin_config = plugin_config or {}

    # ---- Path-based discovery ---------------------------------------
    for path in paths:
        if not path.exists():
            summary.errors.append({
                "source": "path", "target": str(path),
                "reason": "directory does not exist",
            })
            continue
        if not path.is_dir():
            summary.errors.append({
                "source": "path", "target": str(path),
                "reason": "not a directory",
            })
            continue
        for py_file in sorted(path.glob("*_agent.py")):
            _load_path_module(
                py_file, orchestrator, plugin_config, on_conflict, summary,
            )

    # ---- Entry-point discovery --------------------------------------
    if entry_point_group:
        try:
            from importlib.metadata import entry_points
            try:
                eps = entry_points(group=entry_point_group)
            except TypeError:
                # Pre-3.10 returns a dict; emulate the new API
                eps = entry_points().get(entry_point_group, [])
            for ep in eps:
                _load_entry_point(
                    ep, orchestrator, plugin_config, on_conflict, summary,
                )
        except Exception as exc:  # pragma: no cover - importlib.metadata edge
            summary.errors.append({
                "source": "entry_points", "target": entry_point_group,
                "reason": f"entry_points lookup failed: {exc}",
            })

    return summary


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _load_path_module(
    py_file: Path,
    orchestrator: Any,
    plugin_config: dict,
    on_conflict: str,
    summary: PluginLoadSummary,
) -> None:
    """Import a ``*_agent.py`` file by path and register the agent class."""
    module_name = f"_tao_plugin_{py_file.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            summary.errors.append({
                "source": "path", "target": str(py_file),
                "reason": "spec_from_file_location returned None",
            })
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        summary.errors.append({
            "source": "path", "target": str(py_file),
            "reason": f"import failed: {exc}",
        })
        return

    agent_cls = _find_agent_class(module)
    if agent_cls is None:
        summary.skipped.append({
            "source": "path", "target": str(py_file),
            "reason": "no class with AGENT_NAME / required methods found",
        })
        return

    _instantiate_and_register(
        agent_cls, orchestrator, plugin_config, on_conflict,
        source=f"path:{py_file}", summary=summary,
    )


def _load_entry_point(
    ep: Any,
    orchestrator: Any,
    plugin_config: dict,
    on_conflict: str,
    summary: PluginLoadSummary,
) -> None:
    """Resolve and register a plug-in declared in an entry-points group."""
    target = f"{getattr(ep, 'group', '?')}:{getattr(ep, 'name', '?')}"
    try:
        loaded = ep.load()
    except Exception as exc:
        summary.errors.append({
            "source": "entry_point", "target": target,
            "reason": f"load failed: {exc}",
        })
        return

    # ``loaded`` is typically a class. If it's a module, scan for the
    # agent class. If it's already a class, use it directly.
    if inspect.ismodule(loaded):
        agent_cls = _find_agent_class(loaded)
    elif inspect.isclass(loaded):
        agent_cls = loaded if _looks_like_agent_class(loaded) else None
    else:
        agent_cls = None

    if agent_cls is None:
        summary.skipped.append({
            "source": "entry_point", "target": target,
            "reason": "entry point did not resolve to an agent class",
        })
        return

    _instantiate_and_register(
        agent_cls, orchestrator, plugin_config, on_conflict,
        source=f"entry_point:{target}", summary=summary,
    )


def _find_agent_class(module: Any) -> type | None:
    """
    Return the first class in ``module`` that satisfies the SPEC.md
    contract (run / get_status / validate_input methods + an
    ``AGENT_NAME`` either on the class or at module level).
    """
    module_agent_name = getattr(module, "AGENT_NAME", None)
    candidates: list[type] = []
    for name in dir(module):
        obj = getattr(module, name)
        if not inspect.isclass(obj):
            continue
        # Only consider classes defined in this module (not re-exports
        # of base classes from elsewhere).
        if obj.__module__ != module.__name__:
            continue
        if not _looks_like_agent_class(obj):
            continue
        # Prefer classes that themselves declare AGENT_NAME, fall back
        # to any class if the module declares it at module level.
        if getattr(obj, "AGENT_NAME", None) or module_agent_name:
            candidates.append(obj)

    if not candidates:
        return None
    # Deterministic pick: prefer the class whose name ends in ``Agent``,
    # then alphabetical.
    candidates.sort(key=lambda c: (not c.__name__.endswith("Agent"), c.__name__))
    return candidates[0]


def _looks_like_agent_class(cls: type) -> bool:
    """Cheap structural check for the SPEC.md agent contract."""
    return all(callable(getattr(cls, m, None)) for m in _REQUIRED_METHODS)


def _instantiate_and_register(
    agent_cls: type,
    orchestrator: Any,
    plugin_config: dict,
    on_conflict: str,
    source: str,
    summary: PluginLoadSummary,
) -> None:
    """Instantiate, validate, and register a single agent class."""
    try:
        instance = agent_cls(plugin_config)
    except TypeError:
        # Plug-ins may also accept zero args
        try:
            instance = agent_cls()
        except Exception as exc:
            summary.errors.append({
                "source": source, "target": agent_cls.__name__,
                "reason": f"instantiation failed: {exc}",
            })
            return
    except Exception as exc:
        summary.errors.append({
            "source": source, "target": agent_cls.__name__,
            "reason": f"instantiation failed: {exc}",
        })
        return

    # Resolve identity the same way the orchestrator does.
    name = (
        getattr(instance, "AGENT_NAME", None)
        or getattr(agent_cls, "AGENT_NAME", None)
        or getattr(sys.modules.get(agent_cls.__module__), "AGENT_NAME", None)
    )
    if not name:
        summary.skipped.append({
            "source": source, "target": agent_cls.__name__,
            "reason": "missing AGENT_NAME",
        })
        return

    # Conflict policy
    if name in getattr(orchestrator, "agents", {}):
        if on_conflict == ON_CONFLICT_SKIP:
            summary.skipped.append({
                "source": source, "target": name,
                "reason": "name already registered (on_conflict=skip)",
            })
            return
        if on_conflict == ON_CONFLICT_ERROR:
            raise ValueError(
                f"Plug-in agent name {name!r} from {source} conflicts "
                f"with already-registered agent. on_conflict=error."
            )
        # ON_CONFLICT_REPLACE: drop the existing one before registering
        try:
            del orchestrator.agents[name]
        except KeyError:
            pass

    try:
        orchestrator.register_agent(instance)
    except Exception as exc:
        summary.errors.append({
            "source": source, "target": name,
            "reason": f"register_agent failed: {exc}",
        })
        return

    summary.loaded.append(name)
    logger.info("Plug-in agent registered: %s (from %s)", name, source)
