# AUTO_TRADING — operator setup guide

This guide covers what to do **before** you let the swarm sign a real
Bittensor extrinsic on your behalf. It is not a tutorial on whether
you should — that is a personal financial decision, see
[`DISCLAIMER.md`](../DISCLAIMER.md).

## tl;dr — the four explicit gates

A live trade goes through every one of these. Missing any one keeps
you in paper mode:

| Gate | How to set it | Why |
|---|---|---|
| Wallet mode | Pass `--live` to `tao-swarm trade run` | The default mode is `WATCH_ONLY` (paper) |
| Strategy opt-in | Pass `--live-trading` | Forces `StrategyMeta.live_trading=True` |
| Environment | `export TAO_LIVE_TRADING=1` | Hard external switch, easy to flip off |
| Keystore | `--keystore-path <path>` | Where the encrypted seed lives |

On top of those, all guards from the paper path stay in force:
kill switch, position cap, daily-loss limit, ApprovalGate.

## 1. Set up a dedicated trading key

> **Do not put your main coldkey here.** Bittensor's
> `stake`/`unstake`/`transfer` extrinsics are coldkey-signed at the
> protocol level; whatever seed you store in the keystore *will* act
> as a coldkey on-chain. Use a dedicated, capped trading key — see
> [`CLAUDE.md`](../CLAUDE.md) rule 2.

Create a fresh Bittensor coldkey with `btcli wallet new_coldkey
--wallet.name tao-swarm-live`, fund it with **only** the position
cap amount you can afford to lose, and write down its 32-byte seed
in hex.

## 2. Initialise the keystore

```bash
tao-swarm keystore init \
    --path ~/.tao-swarm/live.keystore \
    --label live-finney
```

You will be prompted (hidden input) for:

- **Seed (hex)** — confirmed twice. With or without `0x` prefix.
- **Password** — confirmed twice. Min 8 chars; longer is better.
  This is what protects the seed at rest.

The file is written atomically with mode `0o600` (owner-only). The
plaintext seed is never written to disk.

To confirm the password without starting the trader:

```bash
tao-swarm keystore verify --path ~/.tao-swarm/live.keystore
```

To inspect non-secret metadata without the password:

```bash
tao-swarm keystore info --path ~/.tao-swarm/live.keystore
```

## 3. Backtest the strategy first

```bash
tao-swarm trade backtest \
    --strategy momentum_rotation \
    --snapshots ./data/historical_snapshots.json \
    --threshold-pct 0.05 \
    --slot-size-tao 1.0
```

`historical_snapshots.json` is a JSON list of `market_state` dicts
(`subnets` + `history`). The backtester reports total P&L, win rate,
max drawdown and pseudo-Sharpe. **No money moves in this step**, so
run it as many times as you want with different parameters.

## 4. Paper-run on live data

Before going live, run the strategy against the live read-only
collectors in paper mode. Same code, same loop, same ledger — but
the executor never reaches the signer:

```bash
tao-swarm --live --network finney trade run \
    --strategy momentum_rotation \
    --paper \
    --tick-interval-s 60 \
    --max-position-tao 1.0 \
    --max-daily-loss-tao 5.0 \
    --max-total-tao 10.0
```

Let it run for at least a day. Inspect the ledger:

```bash
tao-swarm trade status --ledger-db data/trades.db --limit 50
```

If the paper trades match what you'd expect a sane strategy to do,
proceed. If they don't, **fix the strategy or the parameters first.**
Going live with a misbehaving paper run is how money gets lost.

## 5. Go live (carefully)

```bash
export TAO_LIVE_TRADING=1
tao-swarm --live --network finney trade run \
    --strategy momentum_rotation \
    --live --live-trading \
    --keystore-path ~/.tao-swarm/live.keystore \
    --tick-interval-s 60 \
    --max-position-tao 1.0 \
    --max-daily-loss-tao 5.0 \
    --max-total-tao 10.0 \
    --kill-switch-path /run/tao-swarm.kill
```

The CLI will:

1. Prompt for the keystore password.
2. Print a final-confirmation block showing strategy name,
   live_trading flag, caps, keystore path, and `TAO_LIVE_TRADING`
   value.
3. Wait for you to type **`I UNDERSTAND`** (exact match, all caps).
4. Start the runner.

If you don't type the phrase exactly, the runner aborts and the
keystore handle is closed.

## 6. Kill switch

To halt trading from outside the process — if the strategy is
behaving badly, if you're going on vacation, or if you just want to
sleep — touch the kill-switch file:

```bash
touch /run/tao-swarm.kill
```

The next tick will refuse all proposals. The runner does not auto-
restart from a kill: the operator must delete the file manually.

You can also export `TAO_KILL_SWITCH=1` in the runner's environment
to the same effect.

## 7. What's audited

Every executed proposal — paper or live, success or failure — is
written to the SQLite ledger at `--ledger-db`. The schema is one
row per attempt:

| field | content |
|---|---|
| `strategy` | strategy name from `StrategyMeta` |
| `action` | `stake` / `unstake` / `transfer` (or `<verb>_failed` for failed live attempts) |
| `target` | `{netuid, hotkey}` JSON-encoded |
| `amount_tao`, `price_tao`, `realised_pnl_tao` | numeric columns |
| `paper` | 0 for live, 1 for paper |
| `tx_hash` | populated on successful live broadcasts only |
| `note` | strategy reasoning + chain message |

`tao-swarm trade status` summarises this for quick eyeballing.

## 8. Failure modes the runner can survive

The runner has its own circuit breaker (`max_consecutive_errors`,
default 3). If three ticks in a row raise — collector unreachable,
strategy bug, ledger I/O failure — the runner halts itself, marks
its state as `halted`, and refuses to tick again. Use
`runner.reset()` (or restart the process) to resume.

This is independent from the kill switch. The kill switch is for
**you**; the circuit breaker is for **the bot when something
upstream is broken**.

## 9. Cold-start reconciliation (PR 2G)

By default the runner's position book starts empty. After a
restart, the next tick would see `current_total_tao = 0`, the
position-cap arithmetic would be wrong by the entire amount you're
already staked, and the runner could overshoot the operator cap.

To fix this, pass your dedicated trading coldkey ss58 with
`--reconcile-from-coldkey`:

```bash
tao-swarm --live --network finney trade run \
    --strategy momentum_rotation \
    --live --live-trading \
    --keystore-path ~/.tao-swarm/live.keystore \
    --reconcile-from-coldkey 5YourTradingColdkeySS58... \
    --max-position-tao 1.0 \
    --max-total-tao 10.0
```

On the first tick, the runner calls
`Subtensor.get_stake_info_for_coldkey(coldkey_ss58)`, sums stake
per netuid across all delegated hotkeys, and writes the result
into its position book. The next proposal sees the right
`current_total_tao` and the cap holds.

Failure modes:

- **Reader unreachable** (websocket dropped, RPC times out) — the
  runner halts immediately with a clear `halted_reason`. It will
  not attempt to trade with an unverified book.
- **Coldkey has no stake** — empty book, business as usual.
- **Multiple delegated hotkeys on the same netuid** — summed; the
  cap arithmetic treats them as one aggregate position.

Reconciliation runs **once per process start**. If you suspect the
chain has diverged from your local book (concurrent manual trades,
chain reorg) restart the runner.

`status()` reports `last_reconcile_ts` and `reconciled_total_tao`
so the operator / dashboard can audit whether reconciliation has
happened in this process.

**Important** — the reconciled book loses the per-position `entry`
price; the chain doesn't tell us at what price you opened the
position. The momentum strategy doesn't need entry price; the
backtester (which runs in-memory only) is unaffected. Strategies
that compute realised P&L using entry must tolerate `entry=0.0`
on cold-start positions.

## 10. Slippage controls (PR 2H)

Bittensor staking uses an AMM-style alpha pool, so the realised
price moves between proposal and broadcast. Two optional fields on
:class:`TradeProposal` bound that risk:

```python
TradeProposal(
    ...,
    rate_tolerance=0.005,   # accept up to 0.5% slippage
    allow_partial=True,     # accept partial fill if liquidity is short
)
```

When `rate_tolerance` is set, the live signer passes
`safe_staking=True` (or `safe_unstaking=True`) plus the tolerance
value to the SDK. The chain refuses the extrinsic if the realised
rate would fall outside the tolerance — the operator's worst-case
slippage is bounded.

`allow_partial=True` flips `allow_partial_stake` so a large order
that exceeds available liquidity is filled to capacity rather than
failing entirely. Default is `False` (all-or-nothing).

Both default to `None` / `False`, so existing strategies continue
to use the SDK's safe-staking-off behaviour for backwards
compatibility.

## 11. Chain-truth verification (PR 2H)

The signer trusts the SDK's success/failure response by default.
With `--verify-broadcasts` (or `BittensorSigner(verify=True)`),
the signer takes a pre-broadcast snapshot of the on-chain stake,
runs the extrinsic, and re-reads the chain after submission to
confirm the observed delta matches the proposed direction within
tolerance (1% by default).

```bash
tao-swarm trade run \
    --strategy momentum_rotation --live --live-trading \
    --keystore-path ~/.tao-swarm/live.keystore \
    --reconcile-from-coldkey 5xxx \
    --verify-broadcasts \
    ...
```

Outcomes:

- **Match within tolerance** → action recorded as `stake` /
  `unstake` with note `verified: ...`.
- **Mismatch** (sign wrong, or magnitude off by more than tolerance)
  → action recorded as `stake_verification_failed` /
  `unstake_verification_failed`, note prefixed with
  `VERIFY-MISMATCH:`. The broadcast itself was accepted; this is a
  forensic flag, not a transaction abort.
- **Read failure** (post-broadcast RPC drops) → `verified=None`,
  note explains "post-broadcast read unavailable". Doesn't affect
  the broadcast outcome.

The verification step adds one extra RPC round-trip per live
trade, so the operator can opt out for low-latency strategies.

## 12. Dashboard panel (PR 2I)

The Streamlit dashboard's **Trading** page shows the current
runner state plus an aggregated view of the trade ledger. To wire
it up, run the trader with `--status-file`:

```bash
tao-swarm trade run \
    --strategy momentum_rotation \
    --status-file data/runner_status.json \
    ...
```

After every tick the runner writes its status (state, ticks,
executed/refused counters, open positions, last reconcile, halted
reason) atomically to that path. Open the dashboard
(`tao-swarm dashboard`) → **Trading** to see:

- A 4-column KPI block: state badge, strategy name, mode (PAPER /
  LIVE), last tick time.
- Counters row: ticks / executed / refused / errors.
- Halt / error banners if the runner has tripped.
- Open positions table (per-netuid size + entry).
- Cold-start reconcile timestamp + reconciled total TAO.
- Ledger summary: total / paper / live / failed counts, realised
  P&L, distinct strategies present.
- Recent trades table (last 200) with truncated tx_hash for
  readability.

The dashboard is read-only — it never writes to the ledger or
sends signals to the runner. To stop the runner use Ctrl-C, the
kill-switch file, or `runner.stop()` programmatically.

Override the discovery paths via env vars:

- `TAO_RUNNER_STATUS_FILE` — overrides
  `data/runner_status.json`.
- `TAO_LEDGER_DB` — overrides `data/trades.db`.

## 13. What the runner does NOT do

- **Reconcile mid-flight.** Reconciliation is one-shot at startup.
  If your dedicated trading key gets used by another tool while
  the runner is running, the local book will drift. Don't share
  the keystore.
- **Slippage modelling in the backtester.** The backtester assumes
  a fill at the proposal's `price_tao`. The slippage controls in
  section 10 only affect live broadcasts.
- **Multi-strategy ensembles.** One strategy per runner process for
  now. You can run several runner processes pointing at different
  ledgers if you want a basket; cap budgets are not shared
  automatically.

## 14. Where to look in the source

| Concern | File |
|---|---|
| Wallet modes | [`tao_swarm/trading/modes.py`](../tao_swarm/trading/modes.py) |
| Guards (kill, cap, loss) | [`tao_swarm/trading/guards.py`](../tao_swarm/trading/guards.py) |
| Paper ledger | [`tao_swarm/trading/ledger.py`](../tao_swarm/trading/ledger.py) |
| Strategy contract | [`tao_swarm/trading/strategy_base.py`](../tao_swarm/trading/strategy_base.py) |
| Built-in strategy | [`tao_swarm/trading/strategies/momentum_rotation.py`](../tao_swarm/trading/strategies/momentum_rotation.py) |
| Backtester | [`tao_swarm/trading/backtest.py`](../tao_swarm/trading/backtest.py) |
| Executor | [`tao_swarm/trading/executor.py`](../tao_swarm/trading/executor.py) |
| Keystore | [`tao_swarm/trading/keystore.py`](../tao_swarm/trading/keystore.py) |
| Live signer | [`tao_swarm/trading/signer.py`](../tao_swarm/trading/signer.py) |
| Runner loop | [`tao_swarm/trading/runner.py`](../tao_swarm/trading/runner.py) |
| Cold-start reconciliation | [`tao_swarm/trading/reconcile.py`](../tao_swarm/trading/reconcile.py) |
| Dashboard panel | [`tao_swarm/dashboard/trading_view.py`](../tao_swarm/dashboard/trading_view.py) |
| CLI | [`tao_swarm/cli/tao_swarm.py`](../tao_swarm/cli/tao_swarm.py) |

If you change any of these, run the full test suite — every layer
has a dedicated `tests/test_trading_*.py`.
