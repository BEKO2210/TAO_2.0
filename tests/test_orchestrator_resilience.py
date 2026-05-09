"""
Tests for ``src.orchestrator.resilience`` and the orchestrator
integration that consumes it.

The contract (recap):

- ``timeout_s`` on a task → ``TaskTimeoutError`` if the agent doesn't
  finish in time. Tasks without ``timeout_s`` execute exactly as before
  (no behavioural change).
- ``retry_policy`` → retries on the configured exception classes with
  exponential backoff + jitter. Retries are cancel-aware (the backoff
  sleep observes the cancel token).
- ``cancel_token`` → cooperative bail. Set before / between /  during
  backoff, the orchestrator raises ``InterruptedError`` for the
  caller to handle. Pure CPU-bound agent code that ignores the token
  is NOT killed (Python lacks thread interruption); the token is the
  cooperative half of the contract.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from tao_swarm.orchestrator import (
    CancelToken,
    RetryPolicy,
    SwarmOrchestrator,
    TaskTimeoutError,
)
from tao_swarm.orchestrator.resilience import (
    from_task_field,
    run_with_resilience,
    run_with_timeout,
)

# ---------------------------------------------------------------------------
# CancelToken
# ---------------------------------------------------------------------------

def test_cancel_token_starts_unset():
    tok = CancelToken()
    assert tok.is_set() is False


def test_cancel_token_cancel_sets_and_is_idempotent():
    tok = CancelToken()
    tok.cancel()
    assert tok.is_set() is True
    tok.cancel()  # idempotent
    assert tok.is_set() is True


def test_cancel_token_wait_returns_true_immediately_when_set():
    tok = CancelToken()
    tok.cancel()
    assert tok.wait(timeout=10.0) is True  # returns immediately


def test_cancel_token_wait_times_out_when_unset():
    tok = CancelToken()
    t0 = time.perf_counter()
    assert tok.wait(timeout=0.05) is False
    assert time.perf_counter() - t0 >= 0.04


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------

def test_retry_policy_clamps_negative_max_retries():
    p = RetryPolicy(max_retries=-1)
    assert p.max_retries == 0


def test_retry_policy_clamps_excessive_max_retries():
    p = RetryPolicy(max_retries=999)
    assert p.max_retries == 5  # documented cap


def test_retry_policy_default_retries_only_io_errors():
    p = RetryPolicy()
    assert ConnectionError in p.retry_on
    assert TimeoutError in p.retry_on
    assert ValueError not in p.retry_on


def test_retry_policy_sleep_grows_exponentially():
    p = RetryPolicy(backoff_factor=1.0, backoff_jitter=0.0)
    assert p.sleep_seconds(0) == pytest.approx(1.0)
    assert p.sleep_seconds(1) == pytest.approx(2.0)
    assert p.sleep_seconds(2) == pytest.approx(4.0)


def test_from_task_field_accepts_dict():
    p = from_task_field({"max_retries": 3, "backoff_factor": 0.1})
    assert isinstance(p, RetryPolicy)
    assert p.max_retries == 3


def test_from_task_field_accepts_none_returns_none():
    assert from_task_field(None) is None


def test_from_task_field_rejects_garbage():
    with pytest.raises(TypeError):
        from_task_field("not a dict or RetryPolicy")


# ---------------------------------------------------------------------------
# run_with_timeout
# ---------------------------------------------------------------------------

def test_run_with_timeout_returns_value_when_fast():
    assert run_with_timeout(lambda: 42, timeout_s=1.0) == 42


def test_run_with_timeout_raises_on_slow_function():
    def slow():
        time.sleep(1.0)
        return "done"

    with pytest.raises(TaskTimeoutError) as exc:
        run_with_timeout(slow, timeout_s=0.05, agent_name="slowpoke")
    assert exc.value.agent_name == "slowpoke"
    assert exc.value.timeout_s == 0.05


def test_run_with_timeout_zero_disables_timeout():
    """timeout_s=0 should mean 'no timeout', not 'fail immediately'."""
    assert run_with_timeout(lambda: "ok", timeout_s=0) == "ok"
    assert run_with_timeout(lambda: "ok", timeout_s=None) == "ok"


# ---------------------------------------------------------------------------
# run_with_resilience: timeout + retry + cancel composition
# ---------------------------------------------------------------------------

def test_resilience_no_policy_just_calls_once():
    fn = MagicMock(return_value="ok")
    out = run_with_resilience(fn)
    assert out == "ok"
    assert fn.call_count == 1


def test_resilience_retries_on_configured_exception():
    """Two failures, then success on the third try."""
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("simulated transient")
        return "recovered"

    out = run_with_resilience(
        flaky,
        retry_policy=RetryPolicy(
            max_retries=3, backoff_factor=0.001, backoff_jitter=0,
        ),
        agent_name="flaky_agent",
    )
    assert out == "recovered"
    assert calls["n"] == 3


def test_resilience_does_not_retry_on_non_configured_exception():
    fn = MagicMock(side_effect=ValueError("permanent — won't retry"))
    with pytest.raises(ValueError):
        run_with_resilience(
            fn,
            retry_policy=RetryPolicy(max_retries=3, backoff_factor=0.001),
        )
    # Only the initial attempt — ValueError isn't in default retry_on
    assert fn.call_count == 1


def test_resilience_exhausts_retries_and_raises_last_exception():
    fn = MagicMock(side_effect=ConnectionError("always fails"))
    with pytest.raises(ConnectionError, match="always fails"):
        run_with_resilience(
            fn,
            retry_policy=RetryPolicy(
                max_retries=2, backoff_factor=0.001, backoff_jitter=0,
            ),
        )
    assert fn.call_count == 3  # 1 initial + 2 retries


def test_resilience_cancel_before_start_short_circuits():
    fn = MagicMock(return_value="should-not-run")
    tok = CancelToken()
    tok.cancel()
    with pytest.raises(InterruptedError):
        run_with_resilience(fn, cancel_token=tok)
    assert fn.call_count == 0


def test_resilience_cancel_during_backoff_breaks_out():
    """Set the cancel token from another thread while a retry sleep is
    in progress. The resilience wrapper must observe the token and
    raise InterruptedError instead of sleeping out the full backoff."""
    fn = MagicMock(side_effect=ConnectionError("always"))
    tok = CancelToken()

    def cancel_after(delay):
        time.sleep(delay)
        tok.cancel()

    threading.Thread(target=cancel_after, args=(0.05,), daemon=True).start()

    t0 = time.perf_counter()
    with pytest.raises(InterruptedError):
        run_with_resilience(
            fn,
            retry_policy=RetryPolicy(
                max_retries=5, backoff_factor=2.0, backoff_jitter=0,
            ),
            cancel_token=tok,
        )
    elapsed = time.perf_counter() - t0
    # We should bail well before the 2s+4s+8s backoff would complete
    assert elapsed < 1.0


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------

class _FakeAgent:
    """Minimal agent that respects timeouts / failures we configure."""

    AGENT_NAME = "fake_agent"
    AGENT_VERSION = "1.0.0"

    def __init__(self, config=None):
        self.config = config or {}
        self.calls = 0
        self.delay = self.config.get("delay", 0)
        self.fail_n_times = self.config.get("fail_n_times", 0)
        self.exc_type = self.config.get("exc_type", ConnectionError)

    def run(self, task):
        self.calls += 1
        if self.fail_n_times > 0:
            self.fail_n_times -= 1
            raise self.exc_type("simulated failure")
        if self.delay:
            time.sleep(self.delay)
        return {"status": "complete", "calls": self.calls}

    def get_status(self):
        return {"state": "idle", "calls": self.calls}

    def validate_input(self, task):
        return True, ""


def _orch_with(agent: _FakeAgent) -> SwarmOrchestrator:
    """Build an orchestrator and route ``fake_task`` to the test agent."""
    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(agent)
    orch.task_router._task_map["fake_task"] = "fake_agent"
    return orch


def test_orchestrator_task_with_timeout_records_error_on_slow_agent():
    """A slow agent + tight timeout produces a status=error result —
    the run does not crash the orchestrator."""
    agent = _FakeAgent({"delay": 0.5})
    orch = _orch_with(agent)
    out = orch.execute_task({"type": "fake_task", "timeout_s": 0.05})
    assert out["status"] == "error"
    assert "timeout" in out["error"].lower() or "did not complete" in out["error"].lower()


def test_orchestrator_task_with_retry_eventually_succeeds():
    agent = _FakeAgent({"fail_n_times": 2, "exc_type": ConnectionError})
    orch = _orch_with(agent)
    out = orch.execute_task({
        "type": "fake_task",
        "retry_policy": {"max_retries": 3, "backoff_factor": 0.001,
                          "backoff_jitter": 0},
    })
    assert out["status"] == "success"
    assert out["output"]["calls"] == 3


def test_orchestrator_retry_does_not_retry_unconfigured_exception():
    agent = _FakeAgent({"fail_n_times": 99, "exc_type": ValueError})
    orch = _orch_with(agent)
    out = orch.execute_task({
        "type": "fake_task",
        "retry_policy": {"max_retries": 3, "backoff_factor": 0.001},
    })
    assert out["status"] == "error"
    assert agent.calls == 1   # no retry — ValueError not in default retry_on


def test_orchestrator_cancel_run_aborts_subsequent_tasks():
    """After cancel_run(), the next execute_task observes the run-wide
    token and raises InterruptedError, which the orchestrator surfaces
    as an error result."""
    agent = _FakeAgent()
    orch = _orch_with(agent)
    orch.arm_cancel_token()
    orch.cancel_run()
    out = orch.execute_task({"type": "fake_task"})
    assert out["status"] == "error"
    assert "cancel" in out["error"].lower()
    assert agent.calls == 0  # never reached


def test_arm_cancel_token_resets_for_next_run():
    """After arming a fresh token, the orchestrator runs cleanly even
    if a previous token was cancelled."""
    agent = _FakeAgent()
    orch = _orch_with(agent)
    orch.arm_cancel_token()
    orch.cancel_run()
    orch.arm_cancel_token()  # fresh token for the next run
    out = orch.execute_task({"type": "fake_task"})
    assert out["status"] == "success"


def test_orchestrator_default_path_unchanged_when_no_resilience_fields():
    """Tasks without timeout_s / retry_policy / cancel_token execute
    via the original code path (no resilience wrapper)."""
    agent = _FakeAgent()
    orch = _orch_with(agent)
    out = orch.execute_task({"type": "fake_task"})
    assert out["status"] == "success"
    assert out["output"]["calls"] == 1


def test_orchestrator_per_task_cancel_token_fires_independently_of_run():
    """A task-specific cancel_token can pre-cancel a single task without
    affecting the run-wide channel."""
    agent = _FakeAgent()
    orch = _orch_with(agent)
    tok = CancelToken()
    tok.cancel()
    out = orch.execute_task({"type": "fake_task", "cancel_token": tok})
    assert out["status"] == "error"
    assert "cancel" in out["error"].lower()
    # A second task without a cancel token still runs fine
    out2 = orch.execute_task({"type": "fake_task"})
    assert out2["status"] == "success"
