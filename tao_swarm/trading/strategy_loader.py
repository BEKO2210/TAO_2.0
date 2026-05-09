"""
Plug-in loader for trading strategies.

Mirrors :mod:`tao_swarm.orchestrator.plugin_loader` for the
strategy surface. Strategies live OUTSIDE this repo can be
registered into a :class:`StrategyRegistry` at runtime via:

1. **Path-based discovery** — drop a ``*_strategy.py`` file in a
   directory and pass that directory via ``paths=`` or set the
   ``TAO_STRATEGY_PATHS`` env var.
2. **Entry-point discovery** — install the user's package via
   pip, declare it in ``[project.entry-points."tao.strategies"]``
   in ``pyproject.toml``.

A strategy plug-in MUST be a class that:

- Is a subclass of :class:`tao_swarm.trading.strategy_base.Strategy`,
  OR duck-types ``meta()`` and ``evaluate(market_state)`` plus a
  ``STRATEGY_NAME`` class attribute.
- Can be constructed without arguments (the operator passes
  parameters via the CLI / config; defaults must be sane). If the
  strategy needs operator parameters, accept them as keyword
  arguments with reasonable defaults.

Plug-in strategies go through the same :class:`Executor` and the
same three-stage live authorisation as built-ins. Loading a
strategy does NOT raise its trust level — paper is still default,
``StrategyMeta.live_trading`` still has to be ``True``, and
``TAO_LIVE_TRADING`` still has to be set in the env.

Usage
-----

::

    from tao_swarm.trading import StrategyRegistry, load_strategy_plugins

    reg = StrategyRegistry()
    reg.register_builtins()                 # momentum, mean-reversion
    summary = load_strategy_plugins(
        reg, paths=["/path/to/my_strategies"],
    )
    strategy_cls = reg.get("my_custom_strategy")
    strategy = strategy_cls(slot_size_tao=2.0)
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import logging
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tao_swarm.trading.strategy_base import Strategy

logger = logging.getLogger(__name__)


ON_CONFLICT_SKIP = "skip"
ON_CONFLICT_REPLACE = "replace"
ON_CONFLICT_ERROR = "error"

_REQUIRED_METHODS = ("meta", "evaluate")


@dataclass
class StrategyLoadSummary:
    """Structured report of a strategy plug-in load pass."""

    loaded: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "loaded": list(self.loaded),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
        }


class StrategyRegistry:
    """Name → strategy-class registry. Thin and explicit on purpose.

    Strategies are stored as classes (not instances) so the operator
    can construct them with run-specific parameters (slot size,
    threshold, watchlist, etc.) at the CLI layer.
    """

    def __init__(self) -> None:
        self._classes: dict[str, type] = {}

    def register(
        self,
        name: str,
        strategy_cls: type,
        *,
        on_conflict: str = ON_CONFLICT_SKIP,
    ) -> bool:
        """Register a strategy class under ``name``.

        Returns ``True`` if the registration took effect, ``False``
        if it was skipped (duplicate + ``on_conflict='skip'``).
        Raises if ``on_conflict='error'`` and ``name`` is already
        present.
        """
        if not name or not isinstance(name, str):
            raise ValueError(f"strategy name must be a non-empty string, got {name!r}")
        if not _is_strategy_compatible(strategy_cls):
            raise ValueError(
                f"strategy class {strategy_cls!r} does not implement "
                "the Strategy contract (meta() and evaluate())"
            )
        if name in self._classes:
            if on_conflict == ON_CONFLICT_ERROR:
                raise ValueError(f"strategy {name!r} already registered")
            if on_conflict == ON_CONFLICT_SKIP:
                logger.info(
                    "skipping duplicate strategy %r (already registered)", name,
                )
                return False
            # else REPLACE
            logger.info("replacing strategy %r registration", name)
        self._classes[name] = strategy_cls
        return True

    def unregister(self, name: str) -> bool:
        return self._classes.pop(name, None) is not None

    def get(self, name: str) -> type:
        if name not in self._classes:
            raise KeyError(
                f"strategy {name!r} not registered; available: "
                f"{sorted(self._classes)}"
            )
        return self._classes[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._classes))

    def __contains__(self, name: str) -> bool:
        return name in self._classes

    def __len__(self) -> int:
        return len(self._classes)

    def register_builtins(self) -> None:
        """Register the strategies that ship in this repo.

        Imported lazily so callers that only want the registry
        skeleton don't pull the strategy implementations into their
        import graph.
        """
        from tao_swarm.trading.strategies.mean_reversion import (
            MeanReversionStrategy,
        )
        from tao_swarm.trading.strategies.momentum_rotation import (
            MomentumRotationStrategy,
        )

        self.register(
            getattr(MomentumRotationStrategy, "AGENT_NAME", "momentum_rotation"),
            MomentumRotationStrategy,
            on_conflict=ON_CONFLICT_REPLACE,
        )
        self.register(
            getattr(MeanReversionStrategy, "STRATEGY_NAME", "mean_reversion"),
            MeanReversionStrategy,
            on_conflict=ON_CONFLICT_REPLACE,
        )


def load_strategy_plugins(
    registry: StrategyRegistry,
    paths: Iterable[str | Path] | None = None,
    entry_point_group: str | None = "tao.strategies",
    on_conflict: str = ON_CONFLICT_SKIP,
) -> StrategyLoadSummary:
    """Discover external strategy classes and register them.

    Args:
        registry: Where to put the discovered classes.
        paths: Iterable of directories to scan for ``*_strategy.py``.
            ``None`` means "use ``TAO_STRATEGY_PATHS`` env var".
        entry_point_group: ``[project.entry-points]`` group name to
            scan via ``importlib.metadata``. ``None`` to skip.
        on_conflict: ``skip`` / ``replace`` / ``error`` for duplicates.
    """
    summary = StrategyLoadSummary()

    if paths is None:
        env_paths = os.environ.get("TAO_STRATEGY_PATHS", "").strip()
        paths = [p for p in env_paths.split(os.pathsep) if p]
    if isinstance(paths, (str, Path)):
        paths = [paths]
    paths = [Path(p).expanduser().resolve() for p in paths]

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
        for py_file in sorted(path.glob("*_strategy.py")):
            _load_path_module(py_file, registry, on_conflict, summary)

    if entry_point_group:
        try:
            from importlib.metadata import entry_points
            try:
                eps = entry_points(group=entry_point_group)
            except TypeError:
                eps = entry_points().get(entry_point_group, [])
            for ep in eps:
                _load_entry_point(ep, registry, on_conflict, summary)
        except Exception as exc:  # pragma: no cover - importlib.metadata edge
            summary.errors.append({
                "source": "entry_points", "target": entry_point_group,
                "reason": f"entry_points lookup failed: {exc}",
            })

    return summary


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _is_strategy_compatible(cls: Any) -> bool:
    """A class is compatible if it subclasses Strategy OR duck-types
    the required methods."""
    if not inspect.isclass(cls):
        return False
    if issubclass(cls, Strategy):
        return True
    return all(callable(getattr(cls, m, None)) for m in _REQUIRED_METHODS)


def _resolve_name(strategy_cls: type) -> str | None:
    for attr in ("STRATEGY_NAME", "AGENT_NAME"):
        name = getattr(strategy_cls, attr, None)
        if isinstance(name, str) and name:
            return name
    return None


def _find_strategy_class(module: Any) -> type | None:
    """Pick the most suitable strategy class from a loaded module.

    Preference order:
    1. A class with both ``STRATEGY_NAME`` and matching contract.
    2. Any subclass of :class:`Strategy` defined in the module.
    """
    candidates: list[type] = []
    for _name, value in vars(module).items():
        if not inspect.isclass(value):
            continue
        if value.__module__ != module.__name__:
            continue
        if _is_strategy_compatible(value) and not inspect.isabstract(value):
            candidates.append(value)
    if not candidates:
        return None
    # Prefer classes with an explicit STRATEGY_NAME attribute.
    explicit = [c for c in candidates if getattr(c, "STRATEGY_NAME", None)]
    return explicit[0] if explicit else candidates[0]


def _load_path_module(
    py_file: Path,
    registry: StrategyRegistry,
    on_conflict: str,
    summary: StrategyLoadSummary,
) -> None:
    parent_tag = hashlib.sha1(
        str(py_file.parent).encode("utf-8", "replace")
    ).hexdigest()[:8]
    module_name = f"_tao_strategy_plugin_{py_file.stem}_{parent_tag}"
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

    cls = _find_strategy_class(module)
    if cls is None:
        summary.skipped.append({
            "source": "path", "target": str(py_file),
            "reason": "no compatible Strategy class found",
        })
        return

    _register(cls, registry, on_conflict, source=f"path:{py_file}",
              summary=summary)


def _load_entry_point(
    ep: Any,
    registry: StrategyRegistry,
    on_conflict: str,
    summary: StrategyLoadSummary,
) -> None:
    target = f"{getattr(ep, 'group', '?')}:{getattr(ep, 'name', '?')}"
    try:
        loaded = ep.load()
    except Exception as exc:
        summary.errors.append({
            "source": "entry_point", "target": target,
            "reason": f"load failed: {exc}",
        })
        return
    cls: type | None
    if inspect.isclass(loaded):
        cls = loaded
    elif inspect.ismodule(loaded):
        cls = _find_strategy_class(loaded)
    else:
        cls = None
    if cls is None or not _is_strategy_compatible(cls):
        summary.skipped.append({
            "source": "entry_point", "target": target,
            "reason": "entry-point did not resolve to a Strategy class",
        })
        return
    _register(cls, registry, on_conflict, source=f"entry_point:{target}",
              summary=summary)


def _register(
    cls: type,
    registry: StrategyRegistry,
    on_conflict: str,
    *,
    source: str,
    summary: StrategyLoadSummary,
) -> None:
    name = _resolve_name(cls)
    if not name:
        summary.skipped.append({
            "source": source, "target": cls.__name__,
            "reason": "class has no STRATEGY_NAME or AGENT_NAME",
        })
        return
    try:
        ok = registry.register(name, cls, on_conflict=on_conflict)
    except ValueError as exc:
        summary.errors.append({
            "source": source, "target": name, "reason": str(exc),
        })
        return
    if ok:
        summary.loaded.append(name)
    else:
        summary.skipped.append({
            "source": source, "target": name,
            "reason": "duplicate name (on_conflict=skip)",
        })
