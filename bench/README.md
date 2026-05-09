# Benchmarks

Run with `make bench` from the repo root. Each script also runs standalone:

```
python -m scripts.bench_approval_gate     # ApprovalGate throughput
python -m scripts.bench_agents            # per-agent task latency
python -m scripts.bench_orchestrator      # workload personas
TAO_BENCH_LIVE=1 python -m scripts.bench_live   # opt-in network calls
```

Each run writes a `bench/results/<category>-<unix-ts>.json` snapshot with
the per-benchmark timings plus a small environment record (Python version,
platform, git SHA). The directory itself is gitignored — commit individual
baseline files manually with `git add -f bench/results/<file>` when you want
to lock a baseline into the repo.

## Realism notes

The benchmarks are designed to mirror what users actually do, not what's
easy to time in a tight loop:

- **`bench_approval_gate`** uses three traffic mixes — research session
  (95% SAFE / 4% CAUTION / 1% DANGER), operator setup (80/15/5), and an
  adversarial DANGER-only stream as a worst-case baseline.
- **`bench_agents`** times each agent in three flavours: cold (fresh
  instance), warm_same (same input — best case, cache hits), and
  warm_varied (different inputs each call — what you'd actually pay
  iterating over a list of subnets / addresses).
- **`bench_orchestrator`** drives the orchestrator with three workload
  personas: researcher (discover → score → risk-review × 5 candidates),
  operator (system_check → miner_setup → validator_setup → wallet_watch
  — exercises the context bus), and watcher (tight wallet+market loop).
- **`bench_live`** is opt-in via `TAO_BENCH_LIVE=1`. It clears caches
  between iterations so we measure the actual round-trip cost, not a
  1µs SQLite hit. Expect run-to-run variance.
