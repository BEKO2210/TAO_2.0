# Trading-strategy plug-ins

Two built-in strategies ship in this repo:

| Name | Hypothesis | When to use |
|---|---|---|
| `momentum_rotation` | Sustained `tao_in` flow predicts continued flow. Stake into rising subnets, unstake from falling. | Trending regimes, when capital flow signals real shifts. |
| `mean_reversion` | Sharp short-term swings revert. Unstake from rising, stake into falling. | Choppy regimes; pairs naturally with `momentum_rotation`. |

Operators with a different thesis can drop their own strategy in
without modifying this repo. PR 2J landed two discovery paths:

1. **Path-based** — drop a `*_strategy.py` file in a directory.
   Quickest to iterate; no packaging needed.
2. **Entry-point** — install your strategy as a real package and
   declare it in `[project.entry-points."tao.strategies"]`.
   Production-grade; survives upgrades.

Plug-in strategies go through **the same** executor and **the same**
three-stage live authorisation as built-ins. Loading a plug-in does
NOT raise its trust level: paper-trade is still the default,
`StrategyMeta.live_trading` still has to be `True`, and
`TAO_LIVE_TRADING=1` still has to be in the environment.

## The contract

A strategy plug-in is a class that:

1. Subclasses `tao_swarm.trading.strategy_base.Strategy` **OR** duck-
   types `meta()` and `evaluate(market_state)`.
2. Defines a `STRATEGY_NAME` (or `AGENT_NAME`) string class attribute.
3. Can be constructed with reasonable defaults — operator parameters
   come in as keyword arguments.
4. Is concrete (not abstract).

`meta()` returns a `StrategyMeta` describing the strategy's risk
surface (max position, max daily loss, declared actions, opt-in
to live trading).

`evaluate(market_state)` takes the market dict and returns a list
of `TradeProposal` objects.

## Path-based discovery (zero packaging)

```python
# /home/operator/strategies/whale_follow_strategy.py
from __future__ import annotations
from tao_swarm.trading.strategy_base import Strategy, StrategyMeta, TradeProposal


class WhaleFollowStrategy(Strategy):
    STRATEGY_NAME = "whale_follow"
    AGENT_VERSION = "0.1.0"

    def __init__(self, *, slot_size_tao: float = 1.0,
                 max_position_tao: float = 1.0,
                 max_daily_loss_tao: float = 5.0):
        self._slot = slot_size_tao
        self._max_pos = max_position_tao
        self._max_loss = max_daily_loss_tao

    def meta(self) -> StrategyMeta:
        return StrategyMeta(
            name=self.STRATEGY_NAME,
            version=self.AGENT_VERSION,
            max_position_tao=self._max_pos,
            max_daily_loss_tao=self._max_loss,
            actions_used=("stake",),
        )

    def evaluate(self, market_state):
        # ...your logic here...
        return []
```

Run with the plug-in path:

```bash
TAO_STRATEGY_PATHS=/home/operator/strategies \
tao-swarm trade run --strategy whale_follow ...
```

The loader walks each directory, imports every `*_strategy.py`
file, picks the first concrete `Strategy`-compatible class with a
`STRATEGY_NAME` attribute, and registers it.

## Entry-point discovery (production)

In your strategy's `pyproject.toml`:

```toml
[project.entry-points."tao.strategies"]
whale_follow = "my_strategies.whale_follow:WhaleFollowStrategy"
```

After `pip install`, the loader picks it up automatically:

```bash
tao-swarm trade run --strategy whale_follow ...
```

## Conflict resolution

If two sources register the same strategy name (a built-in and a
plug-in, or two plug-ins), the registry's default is **skip** —
the first registration wins, the second is logged and ignored.

For testing or staged rollouts, override:

```python
from tao_swarm.trading import StrategyRegistry, load_strategy_plugins
from tao_swarm.trading.strategy_loader import ON_CONFLICT_REPLACE

reg = StrategyRegistry()
reg.register_builtins()
load_strategy_plugins(
    reg, paths=["/path/to/staging"],
    on_conflict=ON_CONFLICT_REPLACE,
)
```

## Tests for your plug-in

Recommended pattern — the same `Strategy` ABC + `TradeProposal`
validation works in tests without any swarm machinery:

```python
def test_whale_follow_emits_signal():
    s = WhaleFollowStrategy(slot_size_tao=2.0)
    state = {
        "subnets": [{"netuid": 1, "tao_in": 100_000.0}],
        "history": {1: [(0.0, 90_000.0), (1.0, 100_000.0)]},
    }
    out = s.evaluate(state)
    assert all(p.action == "stake" for p in out)
```

For the full executor integration, instantiate `Executor` with
in-memory `PaperLedger`, scripted `TradeProposal`s, and assert on
`ExecResult.status`. See `tests/test_trading_skeleton.py` and
`tests/test_trading_runner.py` for working examples.

## Source map

| Concern | File |
|---|---|
| Strategy ABC + value types | [`tao_swarm/trading/strategy_base.py`](../tao_swarm/trading/strategy_base.py) |
| Built-in `momentum_rotation` | [`tao_swarm/trading/strategies/momentum_rotation.py`](../tao_swarm/trading/strategies/momentum_rotation.py) |
| Built-in `mean_reversion` | [`tao_swarm/trading/strategies/mean_reversion.py`](../tao_swarm/trading/strategies/mean_reversion.py) |
| Registry + plug-in loader | [`tao_swarm/trading/strategy_loader.py`](../tao_swarm/trading/strategy_loader.py) |
| Tests | [`tests/test_trading_strategy_loader_and_mean_reversion.py`](../tests/test_trading_strategy_loader_and_mean_reversion.py) |
