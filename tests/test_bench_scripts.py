"""
Smoke tests for the ``scripts/bench_*.py`` scripts.

The benchmarks aren't run in the default test suite (they take a few
seconds and are noisy), but the scripts must always be importable and
their ``main()`` must execute without error in mock mode. Tests here
use small iteration counts (monkeypatched) so they finish in a normal
test budget while still exercising the full benchmark path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repo root on path so `import scripts.bench_*` works in tests.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# _bench harness
# ---------------------------------------------------------------------------

def test_benchmark_context_manager_records_total_time():
    from scripts._bench import Benchmark

    with Benchmark("smoke", iterations=10) as b:
        for _ in range(10):
            pass
    assert b.iterations == 10
    assert b.total_seconds >= 0
    assert b.calls_per_sec > 0
    assert b.per_call_us >= 0


def test_benchmark_record_collects_samples_for_percentiles():
    from scripts._bench import Benchmark

    with Benchmark("p", iterations=5) as b:
        for _ in range(5):
            b.record(0.001)
    stats = b.stats()
    assert "sample_stats" in stats
    assert stats["sample_stats"]["samples"] == 5
    assert stats["sample_stats"]["p50_us"] == 1000.0


def test_dump_results_writes_json_with_env_summary(tmp_path, monkeypatch):
    from scripts import _bench
    from scripts._bench import Benchmark, dump_results

    monkeypatch.setattr(_bench, "RESULTS_DIR", tmp_path)
    with Benchmark("ok", iterations=3) as b:
        pass
    out_path = dump_results([b], category="smoke", extra={"note": "test"})

    payload = json.loads(out_path.read_text())
    assert payload["category"] == "smoke"
    assert payload["extra"] == {"note": "test"}
    assert payload["env"]["python"]
    assert len(payload["benchmarks"]) == 1
    assert payload["benchmarks"][0]["name"] == "ok"


def test_print_table_runs_without_crashing(capsys):
    from scripts._bench import Benchmark, print_table

    with Benchmark("foo", iterations=1) as b:
        pass
    print_table([b], title="smoke")
    captured = capsys.readouterr()
    assert "smoke" in captured.out
    assert "foo" in captured.out


# ---------------------------------------------------------------------------
# bench scripts: main() runs end-to-end with shrunk iterations
# ---------------------------------------------------------------------------

def _shrink_benchmark_iterations(monkeypatch, max_iters: int = 5) -> None:
    """Patch Benchmark.__init__ to clamp iterations so the bench scripts'
    main() finishes in a normal test budget. Cap is small enough that
    inner loops still execute their bodies but big enough that
    statistics don't divide by zero."""
    from scripts import _bench

    real_init = _bench.Benchmark.__init__

    def shrunk_init(self, name, iterations=1000, **kw):
        real_init(self, name=name, iterations=min(iterations, max_iters), **kw)

    monkeypatch.setattr(_bench.Benchmark, "__init__", shrunk_init)


def test_bench_approval_gate_main_runs(tmp_path, monkeypatch):
    from scripts import _bench
    monkeypatch.setattr(_bench, "RESULTS_DIR", tmp_path)
    _shrink_benchmark_iterations(monkeypatch)

    import scripts.bench_approval_gate as bench
    bench.main()

    # Side effects: at least one JSON results file written.
    files = list(tmp_path.glob("approval_gate-*.json"))
    assert len(files) == 1


def test_bench_agents_main_runs(tmp_path, monkeypatch):
    from scripts import _bench
    monkeypatch.setattr(_bench, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr("scripts.bench_agents.WARM_REPEATS", 2)

    import scripts.bench_agents as bench
    bench.main()

    files = list(tmp_path.glob("agents-*.json"))
    assert len(files) == 1


def test_bench_orchestrator_main_runs(tmp_path, monkeypatch):
    from scripts import _bench
    monkeypatch.setattr(_bench, "RESULTS_DIR", tmp_path)
    _shrink_benchmark_iterations(monkeypatch, max_iters=2)

    import scripts.bench_orchestrator as bench
    bench.main()

    files = list(tmp_path.glob("orchestrator-*.json"))
    assert len(files) == 1


def test_bench_live_skips_without_env_var(monkeypatch, capsys):
    """Without TAO_BENCH_LIVE the script must exit clean (sys.exit(0))
    and not attempt any network calls. Crucial for default ``make
    bench`` not hammering external services."""
    monkeypatch.delenv("TAO_BENCH_LIVE", raising=False)
    import scripts.bench_live as bench
    with pytest.raises(SystemExit) as exc:
        bench.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "TAO_BENCH_LIVE" in captured.out


def test_bench_live_honours_off_value(monkeypatch, capsys):
    monkeypatch.setenv("TAO_BENCH_LIVE", "no")
    import scripts.bench_live as bench
    with pytest.raises(SystemExit) as exc:
        bench.main()
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# Module-level smoke
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("modname", [
    "scripts.bench_approval_gate",
    "scripts.bench_agents",
    "scripts.bench_orchestrator",
    "scripts.bench_live",
])
def test_bench_modules_importable(modname):
    """Catch typos / missing imports the moment they're introduced."""
    __import__(modname)
