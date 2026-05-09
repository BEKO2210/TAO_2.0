"""
Benchmark: live-collector latency against real upstreams.

Opt-in only — set ``TAO_BENCH_LIVE=1`` to run. Without that env var
the script prints a one-line note and exits clean, so a default
``make bench`` doesn't accidentally hammer external services or
fail on hosts without internet.

What it measures:

- ``chain_readonly`` against ``finney`` mainnet via the bittensor
  SDK (lazy-imported; the script gracefully reports if the SDK
  isn't installed instead of crashing).
- ``market_data`` against CoinGecko's free public endpoint.
- ``github_repos`` against GitHub's unauthenticated public API
  (60 req/hr — keep iterations low; the script honours that limit).

Each measurement clears the local SQLite cache before timing so we
see the actual round-trip cost, not a 1µs cache hit. Numbers will
differ run-to-run; treat them as ranges, not point estimates.

Usage:
    TAO_BENCH_LIVE=1 python -m scripts.bench_live
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._bench import Benchmark, dump_results, format_results_path, print_table  # noqa: E402

logging.disable(logging.CRITICAL)


def _gate_or_exit() -> None:
    if os.environ.get("TAO_BENCH_LIVE", "").lower() not in ("1", "true", "yes", "on"):
        print(
            "live benchmarks skipped — set TAO_BENCH_LIVE=1 to run.\n"
            "    These calls hit real upstreams (bittensor finney,\n"
            "    CoinGecko, GitHub API). Numbers will vary by network.\n"
        )
        sys.exit(0)


def _bench_chain(tmp_dir: Path) -> Benchmark | None:
    """Time a fresh ``get_subnet_list`` against finney."""
    from tao_swarm.collectors.chain_readonly import (
        ChainReadOnlyCollector,
        _try_import_bittensor,
    )
    if _try_import_bittensor() is None:
        print("  [skip] bittensor SDK not installed — `pip install bittensor`")
        return None

    db = tmp_dir / "chain.db"
    with Benchmark("chain_readonly.get_subnet_list (finney)", iterations=3) as b:
        for _ in range(b.iterations):
            # Wipe between iterations so we measure the live RPC, not
            # the SQLite cache hit.
            for f in tmp_dir.glob("chain*.db*"):
                try:
                    f.unlink()
                except OSError:
                    pass
            c = ChainReadOnlyCollector({
                "db_path": str(db),
                "use_mock_data": False,
                "network": "finney",
                "timeout": 30,
            })
            t0 = time.perf_counter()
            try:
                c.get_subnet_list()
            except Exception as exc:
                b.metadata.setdefault("errors", []).append(str(exc)[:120])
            b.record(time.perf_counter() - t0)
    return b


def _bench_market(tmp_dir: Path) -> Benchmark | None:
    from tao_swarm.collectors.market_data import MarketDataCollector
    db = tmp_dir / "market.db"
    with Benchmark("market_data.get_tao_price (coingecko)", iterations=3) as b:
        for _ in range(b.iterations):
            try:
                db.unlink()
            except OSError:
                pass
            c = MarketDataCollector({
                "db_path": str(db),
                "use_mock_data": False,
                "request_timeout": 15,
            })
            t0 = time.perf_counter()
            try:
                c.get_tao_price()
            except Exception as exc:
                b.metadata.setdefault("errors", []).append(str(exc)[:120])
            b.record(time.perf_counter() - t0)
    return b


def _bench_github(tmp_dir: Path) -> Benchmark | None:
    """Time an unauthenticated GitHub repo lookup. Capped at 5 calls
    so we don't burn through the 60/hr unauth rate limit."""
    from tao_swarm.collectors.github_repos import GitHubRepoCollector
    db = tmp_dir / "github.db"
    with Benchmark("github_repos.get_repo_info (unauth)", iterations=3) as b:
        for _ in range(b.iterations):
            try:
                db.unlink()
            except OSError:
                pass
            c = GitHubRepoCollector({
                "db_path": str(db),
                "use_mock_data": False,
                "request_timeout": 15,
            })
            t0 = time.perf_counter()
            try:
                c.get_repo_info("https://github.com/opentensor/bittensor")
            except Exception as exc:
                b.metadata.setdefault("errors", []).append(str(exc)[:120])
            b.record(time.perf_counter() - t0)
    return b


def main() -> None:
    _gate_or_exit()

    # Use an isolated cache dir so the bench can't pollute or be
    # polluted by other runs.
    bench_cache = Path(__file__).resolve().parent.parent / "bench" / "_cache"
    if bench_cache.exists():
        shutil.rmtree(bench_cache)
    bench_cache.mkdir(parents=True, exist_ok=True)

    benchmarks: list[Benchmark] = []
    for fn in (_bench_chain, _bench_market, _bench_github):
        b = fn(bench_cache)
        if b is not None:
            benchmarks.append(b)

    if not benchmarks:
        print("nothing to report — every collector skipped (deps missing?)")
        sys.exit(0)

    print_table(benchmarks, title="Live collector latency (network round-trip)")
    out_path = dump_results(benchmarks, category="live_collectors")
    print()
    print(f"  results: {format_results_path(out_path)}")


if __name__ == "__main__":
    main()
