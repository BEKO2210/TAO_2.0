"""
Resilience primitives for ``SwarmOrchestrator.execute_task``.

Three additions, all opt-in via the per-task ``retry_policy`` /
``timeout_s`` / ``cancel_token`` fields:

- **Timeout** — wraps the agent.run call in a single-future
  ``ThreadPoolExecutor`` so a stuck agent gets ``TimeoutError`` after
  ``task["timeout_s"]`` seconds instead of hanging the whole
  ``execute_run``.
- **Retry with exponential backoff** — declarative policy on the task
  dict. Retries on a configurable tuple of exception classes
  (default: nothing — opt-in only). Backoff includes jitter to avoid
  thundering herd when the same external dep is failing.
- **Cooperative cancellation** — a ``CancelToken`` (``threading.Event``
  wrapper) that callers can ``cancel()`` to stop a long-running run.
  Agents that loop over many items can poll
  ``self.cancel_token.is_set()`` between iterations and return early.

None of these change behaviour for callers that don't opt in. Tasks
without ``timeout_s`` / ``retry_policy`` / ``cancel_token`` execute
exactly as before.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cooperative cancellation
# ---------------------------------------------------------------------------

class CancelToken:
    """
    Cooperative cancel signal for a single task or run.

    Wraps ``threading.Event`` so the API stays small and we can grow it
    later (reason field, propagate to children, …) without breaking
    callers. Pass via ``task['cancel_token']`` or set
    ``orchestrator.cancel_token`` for run-wide cancellation.

    Usage on the agent side::

        def run(self, task):
            tok = task.get("cancel_token")
            for item in items:
                if tok and tok.is_set():
                    return {"status": "cancelled"}
                process(item)
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Mark the token cancelled. Idempotent."""
        self._event.set()

    def is_set(self) -> bool:
        """True iff ``cancel()`` was called."""
        return self._event.is_set()

    # Compatibility with the threading.Event interface so existing
    # ``event.wait(timeout)`` patterns work too.
    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """
    Per-task retry declaration.

    Agents themselves stay simple — they don't loop. The orchestrator
    runs the retry loop around ``agent.run``.

    Fields
    ------
    max_retries:
        Maximum number of retries *after* the initial attempt. ``0``
        means "no retries" (one total attempt). Values > 5 are
        clamped — multiplicative backoff makes anything bigger
        meaningless in practice.
    backoff_factor:
        Base in seconds. Sleep before retry ``n`` is
        ``backoff_factor * (2 ** n)`` plus jitter.
    backoff_jitter:
        Random multiplicative jitter in ``[1 - jitter, 1 + jitter]``
        applied to each backoff. Defaults to 0.25.
    retry_on:
        Exception classes that trigger a retry. Defaults to
        ``(ConnectionError, TimeoutError)`` — transient I/O. Pure
        Python errors like ``ValueError`` should never be retried,
        because the answer won't change.
    """

    max_retries: int = 0
    backoff_factor: float = 0.5
    backoff_jitter: float = 0.25
    retry_on: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            self.max_retries = 0
        if self.max_retries > 5:
            self.max_retries = 5
        if self.backoff_factor < 0:
            self.backoff_factor = 0
        if not 0 <= self.backoff_jitter <= 1:
            self.backoff_jitter = 0.25

    def sleep_seconds(self, attempt_index: int) -> float:
        """Return the sleep duration before retry ``attempt_index``
        (0-indexed). Includes jitter."""
        base = self.backoff_factor * (2 ** attempt_index)
        if self.backoff_jitter == 0:
            return base
        delta = base * self.backoff_jitter
        return max(0.0, base + random.uniform(-delta, delta))


def from_task_field(value: Any) -> RetryPolicy | None:
    """
    Coerce a per-task ``retry_policy`` field into a ``RetryPolicy``.

    Accepts ``None`` (no retry), a ``RetryPolicy``, or a plain dict
    with the same field names.
    """
    if value is None:
        return None
    if isinstance(value, RetryPolicy):
        return value
    if isinstance(value, dict):
        return RetryPolicy(**{
            k: v for k, v in value.items()
            if k in {"max_retries", "backoff_factor",
                     "backoff_jitter", "retry_on"}
        })
    raise TypeError(
        "task['retry_policy'] must be RetryPolicy, dict, or None — got "
        f"{type(value).__name__}"
    )


# ---------------------------------------------------------------------------
# Timeout-wrapped invocation
# ---------------------------------------------------------------------------

# A small dedicated pool for timeout watchdogs. We don't use the
# orchestrator's main pool because that's for parallel execute_run;
# the timeout watchdog runs even in sequential mode.
_TIMEOUT_POOL = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="tao-timeout",
)


class TaskTimeoutError(TimeoutError):
    """Raised when a task exceeds its declared ``timeout_s``."""

    def __init__(self, agent_name: str, timeout_s: float) -> None:
        super().__init__(
            f"Agent {agent_name!r} did not complete within "
            f"{timeout_s}s timeout"
        )
        self.agent_name = agent_name
        self.timeout_s = timeout_s


def run_with_timeout(
    fn: Callable[[], Any],
    timeout_s: float,
    agent_name: str = "<unknown>",
) -> Any:
    """
    Run ``fn`` and raise ``TaskTimeoutError`` if it exceeds
    ``timeout_s`` seconds.

    Implementation detail: we submit to a small dedicated thread pool
    and wait on the future. The thread that ran ``fn`` keeps running
    on timeout — Python doesn't expose true thread interruption. The
    cancel token is the cooperative way to stop work; this timeout
    is the "give up waiting" guard for callers.
    """
    if timeout_s is None or timeout_s <= 0:
        return fn()
    fut = _TIMEOUT_POOL.submit(fn)
    try:
        return fut.result(timeout=timeout_s)
    except FutureTimeoutError as exc:
        raise TaskTimeoutError(agent_name, timeout_s) from exc


# ---------------------------------------------------------------------------
# Combined: retry + timeout (the full execute_task wrapper)
# ---------------------------------------------------------------------------

def run_with_resilience(
    fn: Callable[[], Any],
    *,
    retry_policy: RetryPolicy | None = None,
    timeout_s: float | None = None,
    cancel_token: CancelToken | None = None,
    agent_name: str = "<unknown>",
) -> Any:
    """
    Run ``fn`` with optional timeout + retry + cancel.

    Order: cancel-check → timeout-wrap → run → on retryable
    exception, sleep with backoff (cancel-aware), retry. Returns the
    result of ``fn`` or raises the last exception when retries are
    exhausted.
    """
    if cancel_token and cancel_token.is_set():
        raise InterruptedError(f"Task for {agent_name} cancelled before start")

    policy = retry_policy or RetryPolicy()
    last_exc: BaseException | None = None
    attempts = policy.max_retries + 1

    for attempt in range(attempts):
        if cancel_token and cancel_token.is_set():
            raise InterruptedError(
                f"Task for {agent_name} cancelled mid-retry-loop"
            )
        try:
            return run_with_timeout(fn, timeout_s, agent_name=agent_name)
        except policy.retry_on as exc:
            last_exc = exc
            if attempt >= policy.max_retries:
                break
            sleep = policy.sleep_seconds(attempt)
            logger.warning(
                "Agent %s attempt %d/%d failed (%s) — retrying in %.2fs",
                agent_name, attempt + 1, attempts,
                type(exc).__name__, sleep,
            )
            # Cancel-aware sleep: wait on the token, not time.sleep
            if cancel_token:
                if cancel_token.wait(sleep):
                    raise InterruptedError(
                        f"Task for {agent_name} cancelled during backoff"
                    )
            else:
                time.sleep(sleep)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(
        f"run_with_resilience exited without result or exception for {agent_name}"
    )
