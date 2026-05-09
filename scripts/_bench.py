"""
Tiny shared benchmark harness for ``scripts/bench_*.py``.

Goals:

- Plain Python, no external deps. The benchmarks have to run in the
  same environment the swarm runs in (CPython 3.10+, stdlib only).
- Reproducible-ish output: a stable text table to stdout for humans,
  plus a JSON dump under ``bench/results/`` so we can diff baselines
  across PRs.
- Every benchmark file uses the same ``Benchmark`` context manager so
  the table looks the same regardless of which script ran.

Usage:

    from scripts._bench import Benchmark, dump_results

    with Benchmark("my_thing") as b:
        for _ in range(b.iterations):
            do_thing()

    dump_results([b], category="approval_gate")
"""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "bench" / "results"


def format_results_path(path: Path) -> str:
    """Format ``path`` relative to the repo root when possible, else fall
    back to the absolute path. Lets benchmark output stay terse without
    crashing when tests redirect ``RESULTS_DIR`` outside the repo tree."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


@dataclass
class Benchmark:
    """
    Time a block of work and record per-iteration latency stats.

    Use as a context manager. The wrapped code is responsible for
    looping ``iterations`` times — the harness only times the
    overall block plus pre/post setup, then computes per-call
    statistics.
    """

    name: str
    iterations: int = 1000
    setup_seconds: float = 0.0
    total_seconds: float = 0.0
    samples: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __enter__(self) -> "Benchmark":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.total_seconds = time.perf_counter() - self._start

    def record(self, latency_seconds: float) -> None:
        """Optional: feed individual sample timings for percentiles."""
        self.samples.append(latency_seconds)

    @property
    def per_call_us(self) -> float:
        """Average per-iteration latency in microseconds."""
        if self.iterations == 0 or self.total_seconds == 0:
            return 0.0
        return (self.total_seconds * 1_000_000) / self.iterations

    @property
    def calls_per_sec(self) -> float:
        if self.total_seconds == 0:
            return 0.0
        return self.iterations / self.total_seconds

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "iterations": self.iterations,
            "total_seconds": round(self.total_seconds, 6),
            "per_call_us": round(self.per_call_us, 3),
            "calls_per_sec": round(self.calls_per_sec, 1),
            "metadata": self.metadata,
        }
        if self.samples:
            sorted_samples = sorted(self.samples)
            n = len(sorted_samples)
            out["sample_stats"] = {
                "min_us": round(sorted_samples[0] * 1_000_000, 3),
                "p50_us": round(statistics.median(sorted_samples) * 1_000_000, 3),
                "p95_us": round(sorted_samples[int(n * 0.95)] * 1_000_000, 3) if n > 1 else 0.0,
                "max_us": round(sorted_samples[-1] * 1_000_000, 3),
                "samples": n,
            }
        return out


def print_table(benchmarks: list[Benchmark], title: str = "") -> None:
    """Render a fixed-width table to stdout."""
    if title:
        print()
        print("=" * 78)
        print(f"  {title}")
        print("=" * 78)
    header = f"{'name':<42} {'iters':>7} {'us/call':>10} {'calls/s':>10}"
    print(header)
    print("-" * len(header))
    for b in benchmarks:
        print(
            f"{b.name[:42]:<42} {b.iterations:>7} "
            f"{b.per_call_us:>10.2f} {b.calls_per_sec:>10.1f}"
        )


def dump_results(
    benchmarks: list[Benchmark],
    category: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    """
    Write a JSON snapshot under ``bench/results/<category>-<ts>.json``.

    The file carries the benchmark stats plus a small environment
    record (Python version, platform, repo head SHA if discoverable),
    so a baseline file is enough on its own to reproduce the context.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    payload: dict[str, Any] = {
        "category": category,
        "timestamp": ts,
        "env": _env_summary(),
        "benchmarks": [b.stats() for b in benchmarks],
    }
    if extra:
        payload["extra"] = extra
    out_path = RESULTS_DIR / f"{category}-{ts}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    return out_path


def _env_summary() -> dict[str, Any]:
    """Collect the minimum identifying info for a benchmark run."""
    try:
        import subprocess
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except Exception:
        sha = "unknown"
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "git_sha": sha,
        "cwd": str(REPO_ROOT),
    }
