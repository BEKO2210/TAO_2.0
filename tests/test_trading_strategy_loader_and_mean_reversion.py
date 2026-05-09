"""
Tests for PR 2J:

- ``StrategyRegistry`` register/get/conflict semantics.
- ``load_strategy_plugins`` path-based discovery (zero packaging).
- ``register_builtins`` registers both momentum + mean-reversion.
- ``MeanReversionStrategy`` emits the inverse signal of momentum
  on the same input.

Plug-in tests build a tmp-dir with a ``*_strategy.py`` file on disk
and load it with ``paths=[tmp_path]`` — mirroring how an operator
would drop a custom strategy in a folder and point the CLI at it.
"""

from __future__ import annotations

import pytest

from tao_swarm.trading import (
    StrategyMeta,
    StrategyRegistry,
    load_strategy_plugins,
)
from tao_swarm.trading.strategies.mean_reversion import MeanReversionStrategy
from tao_swarm.trading.strategies.momentum_rotation import (
    MomentumRotationStrategy,
)
from tao_swarm.trading.strategy_loader import (
    ON_CONFLICT_ERROR,
    ON_CONFLICT_REPLACE,
)

# ---------------------------------------------------------------------------
# StrategyRegistry — basic register/get
# ---------------------------------------------------------------------------

def test_registry_starts_empty():
    reg = StrategyRegistry()
    assert len(reg) == 0
    assert reg.names() == ()


def test_registry_register_and_get():
    reg = StrategyRegistry()
    ok = reg.register("momentum_rotation", MomentumRotationStrategy)
    assert ok is True
    assert "momentum_rotation" in reg
    assert reg.get("momentum_rotation") is MomentumRotationStrategy


def test_registry_register_rejects_invalid_name():
    reg = StrategyRegistry()
    with pytest.raises(ValueError):
        reg.register("", MomentumRotationStrategy)
    with pytest.raises(ValueError):
        reg.register(None, MomentumRotationStrategy)  # type: ignore[arg-type]


def test_registry_register_rejects_non_strategy_class():
    reg = StrategyRegistry()

    class _NotAStrategy:
        pass

    with pytest.raises(ValueError):
        reg.register("bogus", _NotAStrategy)


def test_registry_get_missing_raises_keyerror():
    reg = StrategyRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


def test_registry_unregister():
    reg = StrategyRegistry()
    reg.register("x", MomentumRotationStrategy)
    assert reg.unregister("x") is True
    assert reg.unregister("x") is False  # already gone


def test_registry_conflict_skip_is_default():
    reg = StrategyRegistry()
    reg.register("x", MomentumRotationStrategy)
    ok = reg.register("x", MeanReversionStrategy)  # different class
    assert ok is False
    assert reg.get("x") is MomentumRotationStrategy  # original kept


def test_registry_conflict_replace_swaps_in_new():
    reg = StrategyRegistry()
    reg.register("x", MomentumRotationStrategy)
    ok = reg.register(
        "x", MeanReversionStrategy, on_conflict=ON_CONFLICT_REPLACE,
    )
    assert ok is True
    assert reg.get("x") is MeanReversionStrategy


def test_registry_conflict_error_raises():
    reg = StrategyRegistry()
    reg.register("x", MomentumRotationStrategy)
    with pytest.raises(ValueError):
        reg.register("x", MeanReversionStrategy, on_conflict=ON_CONFLICT_ERROR)


def test_registry_register_builtins():
    reg = StrategyRegistry()
    reg.register_builtins()
    assert "momentum_rotation" in reg
    assert "mean_reversion" in reg
    assert reg.get("momentum_rotation") is MomentumRotationStrategy
    assert reg.get("mean_reversion") is MeanReversionStrategy


def test_registry_accepts_duck_typed_strategy():
    """A class that doesn't subclass Strategy but implements meta()
    + evaluate() is accepted (the contract is duck-typed)."""

    class _Duck:
        STRATEGY_NAME = "duck"

        def meta(self):
            return StrategyMeta(
                name="duck", version="0.1",
                max_position_tao=1.0, max_daily_loss_tao=1.0,
            )

        def evaluate(self, _ms):
            return []

    reg = StrategyRegistry()
    reg.register("duck", _Duck)
    assert reg.get("duck") is _Duck


# ---------------------------------------------------------------------------
# load_strategy_plugins — path-based discovery
# ---------------------------------------------------------------------------

_PLUGIN_TEMPLATE = '''
"""Tiny plug-in strategy for tests."""
from __future__ import annotations
from tao_swarm.trading.strategy_base import Strategy, StrategyMeta, TradeProposal


class CustomStrategy(Strategy):
    STRATEGY_NAME = "custom_test"
    AGENT_VERSION = "9.9.9"

    def meta(self):
        return StrategyMeta(
            name=self.STRATEGY_NAME, version=self.AGENT_VERSION,
            max_position_tao=1.0, max_daily_loss_tao=1.0,
        )

    def evaluate(self, _ms):
        return []
'''


def test_load_plugins_discovers_strategy_file(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "custom_strategy.py").write_text(_PLUGIN_TEMPLATE)

    reg = StrategyRegistry()
    summary = load_strategy_plugins(
        reg, paths=[plugin_dir], entry_point_group=None,
    )
    assert "custom_test" in reg
    assert summary.loaded == ["custom_test"]
    assert summary.errors == []


def test_load_plugins_skips_non_matching_filenames(tmp_path):
    """Loader only picks up *_strategy.py files."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "not_a_strategy_at_all.py").write_text(_PLUGIN_TEMPLATE)
    (plugin_dir / "real_strategy.py").write_text(_PLUGIN_TEMPLATE)

    reg = StrategyRegistry()
    load_strategy_plugins(reg, paths=[plugin_dir], entry_point_group=None)
    # Only the *_strategy.py file is discovered.
    assert "custom_test" in reg
    # The other file would have registered "custom_test" too — so we
    # expect exactly one registration.
    assert len(reg) == 1


def test_load_plugins_records_missing_directory(tmp_path):
    reg = StrategyRegistry()
    summary = load_strategy_plugins(
        reg, paths=[tmp_path / "no_such"], entry_point_group=None,
    )
    assert any("does not exist" in e["reason"] for e in summary.errors)


def test_load_plugins_skips_module_without_strategy_class(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "empty_strategy.py").write_text(
        '"""Has no strategy class."""\n'
    )
    reg = StrategyRegistry()
    summary = load_strategy_plugins(
        reg, paths=[plugin_dir], entry_point_group=None,
    )
    assert summary.loaded == []
    assert any(
        "no compatible Strategy class" in s["reason"]
        for s in summary.skipped
    )


def test_load_plugins_records_import_errors(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "broken_strategy.py").write_text(
        "import nonexistent_module_xyz_blah_blah\n"
    )
    reg = StrategyRegistry()
    summary = load_strategy_plugins(
        reg, paths=[plugin_dir], entry_point_group=None,
    )
    assert summary.loaded == []
    assert any("import failed" in e["reason"] for e in summary.errors)


def test_load_plugins_supports_env_var(monkeypatch, tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "env_strategy.py").write_text(_PLUGIN_TEMPLATE)
    monkeypatch.setenv("TAO_STRATEGY_PATHS", str(plugin_dir))
    reg = StrategyRegistry()
    load_strategy_plugins(reg, paths=None, entry_point_group=None)
    assert "custom_test" in reg


def test_load_plugins_two_dirs_same_filename_isolated(tmp_path):
    """Two plug-ins with the same filename in different dirs must
    not collide (sys.modules namespacing must isolate them)."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "x_strategy.py").write_text(_PLUGIN_TEMPLATE)
    (b / "x_strategy.py").write_text(
        _PLUGIN_TEMPLATE.replace("custom_test", "custom_test_b")
    )
    reg = StrategyRegistry()
    load_strategy_plugins(reg, paths=[a, b], entry_point_group=None)
    assert "custom_test" in reg
    assert "custom_test_b" in reg


# ---------------------------------------------------------------------------
# MeanReversionStrategy
# ---------------------------------------------------------------------------

def test_mean_reversion_meta_reports_risk_surface():
    s = MeanReversionStrategy(slot_size_tao=2.5, max_daily_loss_tao=10.0)
    m = s.meta()
    assert isinstance(m, StrategyMeta)
    assert m.name == "mean_reversion"
    assert m.max_position_tao == 2.5
    assert m.max_daily_loss_tao == 10.0
    assert "stake" in m.actions_used
    assert "unstake" in m.actions_used
    assert m.live_trading is False  # default opt-out


def test_mean_reversion_unstakes_on_positive_momentum():
    """Inverse of momentum-rotation: positive movement → unstake."""
    s = MeanReversionStrategy(threshold_pct=0.05, slot_size_tao=1.0)
    out = s.evaluate({
        "subnets": [{"netuid": 1, "tao_in": 110.0}],
        "history": {1: [(0.0, 100.0), (1.0, 110.0)]},
    })
    assert len(out) == 1
    assert out[0].action == "unstake"


def test_mean_reversion_stakes_on_negative_momentum():
    """Inverse of momentum-rotation: negative movement → stake."""
    s = MeanReversionStrategy(threshold_pct=0.05, slot_size_tao=1.0)
    out = s.evaluate({
        "subnets": [{"netuid": 1, "tao_in": 80.0}],
        "history": {1: [(0.0, 100.0), (1.0, 80.0)]},
    })
    assert len(out) == 1
    assert out[0].action == "stake"


def test_mean_reversion_inverts_momentum_strategy_on_same_input():
    """Same market_state → mean-reversion emits the OPPOSITE action
    from momentum-rotation. That's the whole point of the abstraction."""
    state = {
        "subnets": [{"netuid": 1, "tao_in": 110.0}],
        "history": {1: [(0.0, 100.0), (1.0, 110.0)]},
    }
    mom = MomentumRotationStrategy(threshold_pct=0.05).evaluate(state)
    rev = MeanReversionStrategy(threshold_pct=0.05).evaluate(state)
    assert len(mom) == 1 and len(rev) == 1
    assert mom[0].action == "stake"
    assert rev[0].action == "unstake"


def test_mean_reversion_silent_inside_deadband():
    s = MeanReversionStrategy(threshold_pct=0.10)
    # Only 5% movement, threshold is 10% → no signal.
    out = s.evaluate({
        "subnets": [{"netuid": 1, "tao_in": 105.0}],
        "history": {1: [(0.0, 100.0), (1.0, 105.0)]},
    })
    assert out == []


def test_mean_reversion_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        MeanReversionStrategy(threshold_pct=0)
    with pytest.raises(ValueError):
        MeanReversionStrategy(slot_size_tao=0)
    with pytest.raises(ValueError):
        MeanReversionStrategy(max_daily_loss_tao=0)
    with pytest.raises(ValueError):
        MeanReversionStrategy(slot_size_tao=2, max_position_tao=1)


def test_mean_reversion_watchlist_filters_other_netuids():
    s = MeanReversionStrategy(threshold_pct=0.05, watchlist=[1])
    out = s.evaluate({
        "subnets": [
            {"netuid": 1, "tao_in": 110.0},
            {"netuid": 2, "tao_in": 110.0},
        ],
        "history": {
            1: [(0.0, 100.0), (1.0, 110.0)],
            2: [(0.0, 100.0), (1.0, 110.0)],
        },
    })
    assert len(out) == 1
    assert out[0].target["netuid"] == 1


def test_mean_reversion_skips_bad_tao_in_values():
    s = MeanReversionStrategy(threshold_pct=0.05)
    out = s.evaluate({
        "subnets": [
            {"netuid": 1, "tao_in": None},
            {"netuid": 2, "tao_in": float("nan")},
            {"netuid": 3, "tao_in": -10.0},
        ],
        "history": {
            1: [(0.0, 100.0), (1.0, 110.0)],
            2: [(0.0, 100.0), (1.0, 110.0)],
            3: [(0.0, 100.0), (1.0, 110.0)],
        },
    })
    assert out == []


def test_mean_reversion_live_trading_flag_propagates_to_meta():
    s = MeanReversionStrategy(live_trading=True)
    assert s.meta().live_trading is True


# ---------------------------------------------------------------------------
# CLI _load_strategy uses the registry
# ---------------------------------------------------------------------------

def test_cli_load_strategy_finds_mean_reversion():
    """The CLI's _load_strategy goes through the registry and must
    now find both built-ins."""
    from tao_swarm.cli.tao_swarm import _load_strategy

    s = _load_strategy("mean_reversion", threshold_pct=0.05)
    assert isinstance(s, MeanReversionStrategy)


def test_cli_load_strategy_unknown_name_raises_clear_error():
    from click import ClickException

    from tao_swarm.cli.tao_swarm import _load_strategy

    with pytest.raises(ClickException):
        _load_strategy("does_not_exist")


def test_cli_load_strategy_loads_plugin_from_path(tmp_path):
    """Path-based plug-in flow: drop a *_strategy.py and load it."""
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "cli_strategy.py").write_text(_PLUGIN_TEMPLATE)

    from tao_swarm.cli.tao_swarm import _load_strategy

    s = _load_strategy("custom_test", plugin_paths=(str(plugin_dir),))
    # Constructed with no kwargs; class is the duck-typed plug-in.
    assert s.meta().name == "custom_test"
