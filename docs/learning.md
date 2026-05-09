# Learning layer — making the bot get better

PR 2M adds three independent capabilities that together make the
trader **adapt** to its own track record:

- **PerformanceTracker** reads the audit ledger and reports per-
  strategy P&L / win-rate / Sharpe over a rolling window.
- **EnsembleStrategy** runs multiple base strategies and weights
  their proposals by recent performance — winners get more capital,
  losers get throttled (but never to zero).
- **ConfidenceCalibrator** buckets historical proposals by emitted
  `confidence` and reports the realised win-rate per bucket.

None of these change the safety architecture. The Executor + Cap +
KillSwitch + DailyLoss + three-stage live opt-in still gate every
proposal. Learning is what arrives at the executor — the executor
still says yes or no.

## Honest expectations

**Learning needs trades.** A bot doing 5 trades/day takes weeks to
accumulate enough realised closes for the tracker to come out of
"insufficient_data" mode (default `min_trades=5`). Adaptive
weighting will look identical to uniform weighting until then.

**Don't tune aggressively.** The single biggest mistake operators
make is fitting parameters to recent noise. Defaults err on the
side of "no opinion": insufficient-data strategies get the uniform
baseline, weights have a floor so the worst loser still keeps a
small slice for regime change, and the tuner module (future PR)
will require walk-forward validation before any parameter change
ships.

**The tracker is read-only.** It never writes to the ledger; it
just summarises what's already there. You can run it on a
historical ledger to get a retrospective view.

## Quick start

```bash
# Look at recent performance per strategy:
tao-swarm trade learning-report \
    --ledger-db data/trades.db \
    --window-days 14

# Same as JSON for scripting:
tao-swarm trade learning-report --json
```

Output (illustrative):

```
  Learning report — window 14 days, max 200 trades, min 5 closes

    strategy                 attempts  closes     pnl_tao  win_rate    sharpe  data
    ----------------------  --------  ------  ----------  --------  -------  ----
    momentum_rotation             58      24    +12.4500     58.3%  +1.4520    ok
    mean_reversion                47      19     -3.2100     52.6%  -0.2104    ok
    custom_test                    3       2     +0.5000      0.0%  +0.0000  INSUF

  Suggested ensemble weights:
    momentum_rotation       ████████████████████··········  62.4%
    mean_reversion          ████████··························  25.6%
    custom_test             ████····························  12.0%
```

## Wiring the ensemble

Three lines turn two strategies into an adaptive ensemble:

```python
from tao_swarm.trading import (
    EnsembleStrategy, PerformanceTracker, PaperLedger,
    inverse_loss_weights,
)
from tao_swarm.trading.strategies.mean_reversion import MeanReversionStrategy
from tao_swarm.trading.strategies.momentum_rotation import MomentumRotationStrategy

ledger = PaperLedger("data/trades.db")
tracker = PerformanceTracker(ledger)

ensemble = EnsembleStrategy(
    bases={
        "momentum_rotation": MomentumRotationStrategy(slot_size_tao=1.0),
        "mean_reversion": MeanReversionStrategy(slot_size_tao=1.0),
    },
    tracker=tracker,
    weight_fn=inverse_loss_weights,
)
```

Then pass `ensemble` to the runner like any other strategy. The
`runner` writes new trades to the ledger; the tracker reads them on
the next tick; weights shift accordingly.

## Weight functions

Two are built in:

| Name | Behaviour |
|---|---|
| `uniform_weights(names, tracker)` | Equal weight per base. Ignores tracker. |
| `inverse_loss_weights(names, tracker, *, window_days=7, floor=0.05)` | Weight by recent realised P&L. Losers shrink toward `floor`, never to zero. Insufficient-data strategies get the uniform baseline. |

Custom weight functions are easy:

```python
def sharpe_weights(names, tracker):
    if tracker is None:
        return {n: 1.0 / len(names) for n in names}
    raw = {}
    for n in names:
        perf = tracker.stats_for(n)
        if perf.insufficient_data:
            continue
        raw[n] = max(0.0, perf.sharpe)
    if not raw:
        return {n: 1.0 / len(names) for n in names}
    total = sum(raw.values()) or 1.0
    return {n: raw.get(n, 0.0) / total for n in names}

ensemble = EnsembleStrategy(bases={...}, weight_fn=sharpe_weights, tracker=tracker)
```

## Dust-trade prevention

`EnsembleStrategy(min_weight=0.01)` skips any base whose weight
falls below the floor. Defaults to 1% — below that the proposal
amount is too small to be worth the on-chain fee. Set higher (e.g.
0.1) if you want only the top 2-3 contributors active per tick.

## Confidence calibration

Each strategy emits proposals with a `confidence` score in [0, 1].
The calibrator takes a list of `(confidence, realised_pnl)` pairs
and groups them into N buckets:

```python
from tao_swarm.trading import ConfidenceCalibrator

cal = ConfidenceCalibrator(ledger, num_buckets=5, min_samples_per_bucket=10)
buckets = cal.buckets_for(
    "momentum_rotation",
    confidence_pairs=[(0.5, 1.0), (0.8, 5.0), ...],
)
for b in buckets:
    print(b.bucket_lo, b.realised_win_rate, b.insufficient_data)
```

A well-calibrated strategy lands close to the diagonal: high-
confidence buckets show high realised win-rates, low-confidence
buckets show low ones. A poorly-calibrated strategy may be flat or
inverted — that's the signal to redesign the strategy's confidence
function (or downweight high-confidence trades when you don't
trust them).

The calibrator does not auto-modify strategy behaviour. It exposes
the data; the operator (or a future tuner) decides what to do.

## What's NOT in this PR

- **Auto-tuning of strategy parameters.** A walk-forward Bayesian /
  grid-search tuner is the natural next step (PR 2N), but it needs
  out-of-sample validation to avoid overfitting. Until then, tune
  parameters manually using `tao-swarm trade backtest` against
  hold-out snapshot windows.
- **Regime detection.** Detecting trending vs choppy regimes and
  switching strategies based on regime is a clean follow-up
  (PR 2O). The current ensemble approximates this by weight: in a
  trending regime momentum's recent P&L wins, in a choppy regime
  mean-reversion's does, and the inverse-loss weight function
  follows the wind.
- **Reinforcement learning.** Full RL is overkill for this domain
  and routinely underperforms simple ensembles in production
  trading. Not on the roadmap.

## Source map

| Concern | File |
|---|---|
| Performance tracker | [`tao_swarm/trading/learning/tracker.py`](../tao_swarm/trading/learning/tracker.py) |
| Ensemble + weight functions | [`tao_swarm/trading/learning/ensemble.py`](../tao_swarm/trading/learning/ensemble.py) |
| Confidence calibrator | [`tao_swarm/trading/learning/calibration.py`](../tao_swarm/trading/learning/calibration.py) |
| CLI report | `tao_swarm/cli/tao_swarm.py` (`trade learning-report`) |
| Tests | [`tests/test_trading_learning.py`](../tests/test_trading_learning.py) |
