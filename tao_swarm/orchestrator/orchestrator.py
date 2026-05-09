"""
Swarm Orchestrator for TAO/Bittensor Multi-Agent System.

The orchestrator is the central coordination hub. It manages agent
registration, task execution with approval gating, conflict detection,
and report generation across all 15 specialized agents.
"""

import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from tao_swarm.orchestrator.approval_gate import ApprovalGate
from tao_swarm.orchestrator.context import AgentContext
from tao_swarm.orchestrator.progress import _OrchestratorProgressChannel
from tao_swarm.orchestrator.resilience import (
    CancelToken,
    run_with_resilience,
)
from tao_swarm.orchestrator.resilience import (
    from_task_field as _resolve_retry_policy,
)
from tao_swarm.orchestrator.task_router import TaskRouter

logger = logging.getLogger(__name__)


class SwarmOrchestrator:
    """
    Central orchestrator for the TAO/Bittensor multi-agent swarm.

    Coordinates all 15 specialized agents, enforces safety through the
    ApprovalGate, routes tasks via the TaskRouter, and maintains a full
    execution history. DANGER actions are never executed automatically -
    they are reported as plans for human review.

    Attributes:
        config: Global configuration dictionary
        approval_gate: Safety gate for action classification
        task_router: Task-to-agent router
        agents: Dictionary of registered agent instances
        run_log: Chronological list of all execution events
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the SwarmOrchestrator.

        Args:
            config: Global configuration dictionary containing:
                - wallet_mode: "NO_WALLET" | "WATCH_ONLY" | "FULL"
                - log_level: Logging level string
                - safety_override: Whether DANGER override is enabled
        """
        self.config: dict = config
        self.approval_gate: ApprovalGate = ApprovalGate(
            wallet_mode=config.get("wallet_mode", "NO_WALLET")
        )
        self.task_router: TaskRouter = TaskRouter()
        self.agents: dict[str, Any] = {}
        self.run_log: list[dict] = []
        self.context: AgentContext = AgentContext()
        self._safety_override: bool = config.get("safety_override", False)
        self._start_time: float = time.time()
        # Thread-safety primitives. _log_lock guards run_log mutations
        # (multiple workers can append events concurrently). _agent_locks
        # serialise calls into the same agent instance — different agents
        # can still run in parallel — because most agents keep mutable
        # ``self._status`` / counters that aren't safe to race on.
        self._log_lock: threading.Lock = threading.Lock()
        self._agent_locks: dict[str, threading.Lock] = {}
        self._agent_locks_lock: threading.Lock = threading.Lock()
        # Run-wide cooperative cancel token. Default ``None`` keeps the
        # existing behaviour. Callers can ``orch.cancel_run()`` to stop
        # an in-flight ``execute_run`` (or any execute_task that polls).
        self._run_cancel_token: CancelToken | None = None
        # Heartbeat / progress sink. Agents that opt in can call
        # ``self.report_progress(percent, message)`` during long
        # operations; the orchestrator records the events and tracks
        # last-heartbeat timestamps for stale-task detection.
        self.progress: _OrchestratorProgressChannel = _OrchestratorProgressChannel(
            log_event=self._log_event,
        )

        logger.info(
            "SwarmOrchestrator initialized (wallet_mode=%s, safety_override=%s)",
            self.approval_gate.wallet_mode,
            self._safety_override,
        )

    def register_agent(self, agent_instance: Any) -> None:
        """
        Register an agent instance with the orchestrator.

        Resolves ``AGENT_NAME`` / ``AGENT_VERSION`` from the instance, the
        class, or — per SPEC.md — the agent's defining module, in that order.

        Args:
            agent_instance: The agent class instance to register
        """
        agent_name, agent_version = self._resolve_agent_identity(agent_instance)

        if not agent_name:
            raise ValueError(
                "Agent instance missing AGENT_NAME (checked instance, class, "
                "and module)"
            )

        self.agents[agent_name] = agent_instance
        self.task_router.register_agent(agent_name, agent_instance)

        # Pull-based context bus: hand the agent a reference to the shared
        # context so it can opt-in by reading from it. Agents that don't
        # use ``self.context`` never have to know it exists. We don't
        # overwrite if the agent (or its config) already set one — even
        # if that pre-set context happens to be empty (so ``is None`` is
        # the right check, not a truthiness check).
        if getattr(agent_instance, "context", None) is None:
            agent_instance.context = self.context

        # Heartbeat / progress reporter. Agents that opt in can call
        # ``self.report_progress(percent, message)`` during long-
        # running work. We bind the reporter to the agent's name so
        # the agent can't accidentally report progress under another
        # agent's identity. Agents that don't call it lose nothing.
        if not callable(getattr(agent_instance, "report_progress", None)):
            agent_instance.report_progress = self.progress.make_reporter_for(
                agent_name,
            )

        logger.info(
            "Agent registered: %s v%s (%s)",
            agent_name, agent_version, type(agent_instance).__name__,
        )

        self._log_event(
            event_type="agent_registered",
            agent_name=agent_name,
            agent_version=agent_version,
        )

    def execute_task(self, task: dict) -> dict:
        """
        Execute a single task with full approval gate checking.

        Steps:
        1. Validate the task input
        2. Classify the task action through the ApprovalGate
        3. If DANGER: return a plan only, do NOT route or execute
        4. Otherwise: route to an agent and execute

        Classification runs **before** routing so that DANGER actions
        (e.g. ``execute_trade``, ``sign_transaction``) are blocked even
        when the TaskRouter has no mapping for them — the safety gate
        is the system of record, not the router table.

        Args:
            task: Dictionary with 'type' and optional 'params' keys

        Returns:
            Execution result dictionary with status, classification,
            output, and metadata
        """
        task_type = task.get("type", "unknown")
        task_params = task.get("params", {})

        logger.info("=" * 60)
        logger.info("Executing task: type=%s", task_type)

        self._log_event(
            event_type="task_start",
            task_type=task_type,
            params=task_params,
        )

        # Step 1: Validate input
        validation = self._validate_task_input(task)
        if not validation["valid"]:
            logger.error("Task validation failed: %s", validation["reason"])
            result = {
                "status": "error",
                "error": f"Validation failed: {validation['reason']}",
                "task_type": task_type,
                "classification": ApprovalGate.SAFE.value,
                "executed": False,
            }
            self._log_event(
                event_type="task_error",
                task_type=task_type,
                error=validation["reason"],
            )
            return result

        # Step 2: Classify BEFORE routing so DANGER actions are blocked
        # even if the router has no mapping for the task type.
        classification = self.approval_gate.classify_action(task_type, task_params)
        can_execute = self.approval_gate.can_execute(
            classification, override=self._safety_override
        )

        if not can_execute:
            logger.warning(
                "Task '%s' classified as %s - returning as plan only",
                task_type, classification.value,
            )
            result = {
                "status": "blocked",
                "task_type": task_type,
                "agent_name": None,
                "classification": classification.value,
                "executed": False,
                "output": {
                    "plan": task,
                    "note": (
                        f"This is a {classification.value} action. It requires "
                        "manual approval. Review the plan carefully before "
                        "executing with safety_override=True."
                    ),
                },
                "timestamp": time.time(),
            }
            self._log_event(
                event_type="task_blocked",
                task_type=task_type,
                classification=classification.value,
            )
            return result

        # Step 3: Route to agent (only for SAFE / CAUTION-with-override)
        try:
            agent_name = self.task_router.route_task(task)
        except ValueError as e:
            logger.error("Task routing failed: %s", e)
            return {
                "status": "error",
                "error": str(e),
                "task_type": task_type,
                "classification": classification.value,
                "executed": False,
            }

        # Step 4: Execute via the agent
        try:
            agent = self.agents.get(agent_name)
            if agent is None:
                raise RuntimeError(
                    f"Agent '{agent_name}' not found in registry"
                )

            # Validate task-specific input
            is_valid, error_msg = agent.validate_input(task)
            if not is_valid:
                return {
                    "status": "error",
                    "error": f"Agent validation: {error_msg}",
                    "task_type": task_type,
                    "agent_name": agent_name,
                    "classification": classification.value,
                    "executed": False,
                }

            # Run the agent. Hold the per-agent lock so two parallel
            # execute_task calls into the *same* agent serialise; tasks
            # against *different* agents still run concurrently.
            #
            # Resilience knobs are opt-in via the task dict:
            #   task['timeout_s']    — single-call wall-clock cap
            #   task['retry_policy'] — RetryPolicy or dict; default = no retry
            #   task['cancel_token'] — CancelToken to bail out cooperatively
            # Tasks without these fields execute exactly as before.
            logger.info(
                "Executing task via %s (classification=%s)",
                agent_name, classification.value,
            )
            timeout_s = task.get("timeout_s")
            retry_policy = _resolve_retry_policy(task.get("retry_policy"))
            cancel_token = task.get("cancel_token") or self._run_cancel_token

            def _do_run():
                with self._agent_lock(agent_name):
                    return agent.run(task)

            if timeout_s or retry_policy or cancel_token:
                output = run_with_resilience(
                    _do_run,
                    retry_policy=retry_policy,
                    timeout_s=timeout_s,
                    cancel_token=cancel_token,
                    agent_name=agent_name,
                )
            else:
                output = _do_run()

            # Lift the agent's internal per-call ``status`` field (e.g.
            # "complete", "snapshot", "plan_created", "INSUFFICIENT_DATA",
            # "error") into a top-level ``agent_result_status`` so callers
            # don't have to dig into ``output`` and don't have to handle
            # the case where some agents include it and some don't.
            agent_result_status = (
                output.get("status") if isinstance(output, dict) else None
            )

            # Pull-based context bus: publish the agent's output under the
            # agent's name so a later agent can read it via
            # ``self.context.get("system_check_agent.hardware_report")``.
            # Failed runs (status == "error") are skipped so consumers
            # don't pick up a stale or partial report.
            if isinstance(output, dict) and agent_result_status != "error":
                self.context.publish(agent_name, output)

            result = {
                "status": "success",
                "task_type": task_type,
                "agent_name": agent_name,
                "classification": classification.value,
                "executed": True,
                "output": output,
                "agent_status": agent.get_status(),
                "agent_result_status": agent_result_status,
                "timestamp": time.time(),
            }

            self._log_event(
                event_type="task_complete",
                task_type=task_type,
                agent_name=agent_name,
                classification=classification.value,
                status="success",
            )

        except Exception as e:
            logger.exception("Task execution failed: %s", e)
            result = {
                "status": "error",
                "error": str(e),
                "task_type": task_type,
                "agent_name": agent_name,
                "classification": classification.value,
                "executed": False,
            }
            self._log_event(
                event_type="task_error",
                task_type=task_type,
                agent_name=agent_name,
                error=str(e),
            )

        return result

    def execute_run(
        self,
        run_plan: dict,
        parallel: bool = False,
        max_workers: int = 4,
    ) -> dict:
        """
        Execute a multi-task run plan.

        DANGER tasks are blocked at the gate (per ``execute_task``)
        regardless of mode — concurrency never weakens the safety
        contract.

        Args:
            run_plan: Dictionary with 'tasks' list, each with 'type'
                and 'params'.
            parallel: When True, dispatch tasks via a thread pool.
                Different agents run concurrently; calls into the same
                agent serialise via per-agent locks. Default False so
                existing callers see no behaviour change.
            max_workers: Thread pool size used when ``parallel`` is True.
                Capped to ``len(tasks)`` so we don't spawn idle workers.

        Returns:
            Run result with 'results' list (in the same order as the
            input tasks), 'summary', and 'next_actions'.
        """
        tasks = run_plan.get("tasks", [])
        if not tasks:
            return {
                "status": "error",
                "error": "Run plan contains no tasks",
                "results": [],
            }

        run_id = run_plan.get("run_id", f"run_{int(time.time())}")
        logger.info("=" * 60)
        logger.info(
            "Starting run: %s with %d tasks (parallel=%s)",
            run_id, len(tasks), parallel,
        )

        self._log_event(
            event_type="run_start",
            run_id=run_id,
            task_count=len(tasks),
            parallel=parallel,
        )

        # Validate the entire plan through the approval gate
        plan_validation = self.approval_gate.validate_plan({
            "actions": [{"type": t.get("type", "unknown"),
                         "params": t.get("params", {})} for t in tasks]
        })

        logger.info(
            "Run plan validation: classification=%s, valid=%s",
            plan_validation["classification"],
            plan_validation["valid"],
        )

        if parallel:
            results = self._execute_tasks_parallel(tasks, max_workers)
        else:
            results = []
            for idx, task in enumerate(tasks):
                logger.info(
                    "Executing task %d/%d: %s",
                    idx + 1, len(tasks), task.get("type", "?"),
                )
                results.append(self.execute_task(task))

        success_count = sum(1 for r in results if r["status"] == "success")
        blocked_count = sum(1 for r in results if r["status"] == "blocked")
        error_count = sum(1 for r in results if r["status"] not in ("success", "blocked"))

        # Detect conflicts across results
        conflicts = self.detect_conflicts(results)

        summary = {
            "run_id": run_id,
            "total_tasks": len(tasks),
            "successful": success_count,
            "blocked": blocked_count,
            "errors": error_count,
            "plan_classification": plan_validation["classification"],
            "conflicts_detected": len(conflicts),
            "conflicts": conflicts,
            "execution_time": time.time() - self._start_time,
        }

        self._log_event(
            event_type="run_complete",
            run_id=run_id,
            summary=summary,
        )

        return {
            "status": "complete",
            "run_id": run_id,
            "results": results,
            "summary": summary,
            "next_actions": self.get_next_actions(results),
        }

    def cancel_run(self) -> CancelToken:
        """
        Cooperatively cancel any in-flight ``execute_run`` /
        ``execute_task`` that observes the run-wide cancel token.

        Idempotent — repeated calls just keep the token set. Returns
        the token so callers can ``token.is_set()`` to confirm. Reset
        via ``arm_cancel_token()`` for the next run.

        Note: cancellation is **cooperative**. The orchestrator stops
        between retries and during backoff sleeps. Agents that loop
        over many items can poll ``task['cancel_token']`` (or the
        run-wide token via ``self.context``) to bail out mid-call.
        Python doesn't expose true thread interruption — a CPU-bound
        agent that ignores the token will run to completion.
        """
        if self._run_cancel_token is None:
            self._run_cancel_token = CancelToken()
        self._run_cancel_token.cancel()
        self._log_event(event_type="run_cancelled")
        return self._run_cancel_token

    def arm_cancel_token(self) -> CancelToken:
        """
        Install a fresh ``CancelToken`` for the run-wide channel.

        Call this before ``execute_run`` if you want to be able to
        ``cancel_run()`` later. The token replaces any previously-
        cancelled one so the next run starts clean.
        """
        self._run_cancel_token = CancelToken()
        return self._run_cancel_token

    def reset_context(self) -> None:
        """
        Wipe the shared agent context bus.

        Use this between independent runs so a later agent doesn't pick
        up a stale report from a previous run. Does not affect the
        ``run_log`` or registered agents.
        """
        self.context.reset()
        self._log_event(event_type="context_reset")

    def get_summary(self) -> dict:
        """
        Get an overall summary of the orchestrator state.

        Returns:
            Dictionary with agent count, execution history,
            wallet mode, and uptime
        """
        uptime = time.time() - self._start_time
        return {
            "agent_count": len(self.agents),
            "registered_agents": sorted(self.agents.keys()),
            "task_types_supported": self.task_router.list_task_types(),
            "wallet_mode": self.approval_gate.wallet_mode,
            "safety_override": self._safety_override,
            "events_logged": len(self.run_log),
            "uptime_seconds": round(uptime, 2),
            "approval_gate_rules": len(self.approval_gate.get_rules()),
        }

    def detect_conflicts(self, results: list[dict]) -> list[dict]:
        """
        Detect contradictory or conflicting results across agents.

        Checks for:
        - Agents reporting contradictory status
        - Risk agents vetoing while others proceed
        - Duplicate recommendations

        Args:
            results: List of task execution results

        Returns:
            List of detected conflict dictionaries
        """
        conflicts: list[dict] = []

        # Check if risk agent issued a veto
        risk_results = [
            r for r in results
            if r.get("agent_name") == "risk_security_agent"
            and r.get("status") == "success"
        ]

        for risk_result in risk_results:
            output = risk_result.get("output", {})
            verdict = output.get("verdict", "")

            if verdict == "STOP":
                # Risk agent vetoed - check if other agents proceeded
                proceeding = [
                    r for r in results
                    if r.get("status") == "success"
                    and r.get("agent_name") != "risk_security_agent"
                ]
                if proceeding:
                    conflicts.append({
                        "type": "risk_veto_conflict",
                        "description": (
                            "Risk agent issued STOP veto but other agents "
                            "proceeded with execution"
                        ),
                        "risk_agent_result": risk_result,
                        "proceeding_agents": [
                            r.get("agent_name", "unknown") for r in proceeding
                        ],
                        "severity": "CRITICAL",
                    })

            if verdict == "REJECT":
                conflicts.append({
                    "type": "risk_rejection",
                    "description": (
                        "Risk agent rejected the operation. "
                        "Review risk report before proceeding."
                    ),
                    "risk_agent_result": risk_result,
                    "severity": "HIGH",
                })

        # Check for duplicate wallet operations
        wallet_tasks = [
            r for r in results
            if "wallet" in r.get("task_type", "").lower()
            or r.get("agent_name") == "wallet_watch_agent"
        ]
        if len(wallet_tasks) > 1:
            conflicts.append({
                "type": "multiple_wallet_operations",
                "description": (
                    f"Multiple wallet-related tasks detected ({len(wallet_tasks)}). "
                    "Verify no credential leakage across agents."
                ),
                "count": len(wallet_tasks),
                "severity": "MEDIUM",
            })

        # Check for market/risk inconsistencies
        market_results = [
            r for r in results
            if r.get("agent_name") == "market_trade_agent"
            and r.get("status") == "success"
        ]
        if market_results and not risk_results:
            conflicts.append({
                "type": "missing_risk_review",
                "description": (
                    "Market analysis executed without risk review. "
                    "Consider running risk_security_agent."
                ),
                "severity": "LOW",
            })

        logger.info(
            "Conflict detection: %d conflicts found", len(conflicts)
        )
        return conflicts

    def generate_report(self) -> dict:
        """
        Generate a master report of all orchestrator activity.

        Returns:
            Master report dictionary with status, summary,
            execution log, safety status, and recommendations
        """
        uptime = time.time() - self._start_time

        # Analyze execution log
        event_types: dict[str, int] = {}
        for event in self.run_log:
            et = event.get("event_type", "unknown")
            event_types[et] = event_types.get(et, 0) + 1

        blocked_tasks = [
            e for e in self.run_log
            if e.get("event_type") == "task_blocked"
        ]

        report = {
            "report_type": "orchestrator_master_report",
            "generated_at": time.time(),
            "orchestrator_status": {
                "state": "active",
                "uptime_seconds": round(uptime, 2),
                "agents_registered": len(self.agents),
                "agent_names": sorted(self.agents.keys()),
            },
            "safety_status": {
                "wallet_mode": self.approval_gate.wallet_mode,
                "safety_override": self._safety_override,
                "danger_actions_blocked": len(blocked_tasks),
                "blocked_events": [
                    {
                        "task_type": e.get("task_type"),
                        "agent_name": e.get("agent_name"),
                        "classification": e.get("classification"),
                    }
                    for e in blocked_tasks
                ],
                "active_rules": len(self.approval_gate.get_rules()),
            },
            "execution_summary": {
                "total_events": len(self.run_log),
                "event_breakdown": event_types,
            },
            "agent_status": {
                name: agent.get_status()
                for name, agent in self.agents.items()
            },
            "recommendations": self._generate_recommendations(),
        }

        logger.info("Master report generated with %d sections", len(report))
        return report

    def get_next_actions(self, results: list[dict] | None = None) -> list[dict]:
        """
        Generate clear next actions based on execution results.

        Args:
            results: Optional list of execution results to analyze

        Returns:
            List of recommended next action dictionaries
        """
        next_actions: list[dict] = []

        # Default onboarding actions
        if len(self.agents) == 0:
            return [{
                "priority": "HIGH",
                "action": "Register agents before executing tasks",
                "details": "Use orchestrator.register_agent() for each agent",
            }]

        # Analyze results if provided
        if results:
            blocked = [r for r in results if r.get("status") == "blocked"]
            errors = [r for r in results if r.get("status") == "error"]

            if blocked:
                next_actions.append({
                    "priority": "HIGH",
                    "action": "Review and approve DANGER actions",
                    "details": (
                        f"{len(blocked)} task(s) blocked. "
                        "Review the plans and set safety_override=True "
                        "if you want to proceed."
                    ),
                    "blocked_tasks": [
                        {
                            "type": r.get("task_type"),
                            "agent": r.get("agent_name"),
                            "classification": r.get("classification"),
                        }
                        for r in blocked
                    ],
                })

            if errors:
                next_actions.append({
                    "priority": "HIGH",
                    "action": "Fix task execution errors",
                    "details": f"{len(errors)} task(s) failed with errors",
                    "errors": [r.get("error", "unknown") for r in errors],
                })

        # Standard next actions based on available agents
        if "system_check_agent" in self.agents:
            next_actions.append({
                "priority": "MEDIUM",
                "action": "Run system check",
                "details": "Execute system_check task to verify environment",
                "task": {"type": "system_check", "params": {}},
            })

        if "protocol_research_agent" in self.agents:
            next_actions.append({
                "priority": "MEDIUM",
                "action": "Research Bittensor protocol",
                "details": "Learn about Bittensor protocol before proceeding",
                "task": {"type": "protocol_research", "params": {}},
            })

        if "risk_security_agent" in self.agents:
            next_actions.append({
                "priority": "MEDIUM",
                "action": "Run risk review",
                "details": "Review all operations for security risks",
                "task": {"type": "risk_review", "params": {}},
            })

        if "subnet_discovery_agent" in self.agents:
            next_actions.append({
                "priority": "LOW",
                "action": "Discover available subnets",
                "details": "Find subnets that match your interests",
                "task": {"type": "subnet_discovery", "params": {}},
            })

        return next_actions

    def _execute_tasks_parallel(
        self,
        tasks: list[dict],
        max_workers: int,
    ) -> list[dict]:
        """
        Run ``tasks`` concurrently via ``ThreadPoolExecutor``.

        Per-task safety lives inside ``execute_task`` itself:

        - The ApprovalGate runs *before* any agent is touched, so DANGER
          tasks are blocked the same way they are in sequential mode.
        - ``_log_event`` writes through ``_log_lock``, so the run_log
          stays well-formed across workers.
        - Per-agent locks (``_agent_lock``) serialise calls into the
          same agent instance — different agents run concurrently;
          the same agent invoked twice is queued.

        Returns results in the same order as ``tasks`` so callers can
        zip(tasks, results) regardless of completion order.
        """
        worker_count = min(max_workers, len(tasks))
        results: list[dict | None] = [None] * len(tasks)
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="tao-task",
        ) as pool:
            future_to_idx = {
                pool.submit(self.execute_task, task): idx
                for idx, task in enumerate(tasks)
            }
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                try:
                    results[idx] = fut.result()
                except Exception as exc:  # pragma: no cover - guard
                    logger.exception("Worker for task %d raised: %s", idx, exc)
                    results[idx] = {
                        "status": "error",
                        "error": f"Worker exception: {exc}",
                        "task_type": tasks[idx].get("type", "unknown"),
                        "executed": False,
                    }
        # Fill any None slots defensively (shouldn't happen, but keeps
        # the return type honest).
        return [r if r is not None else {"status": "error", "executed": False}
                for r in results]

    def _validate_task_input(self, task: dict) -> dict:
        """
        Validate a task dictionary has required fields.

        Args:
            task: The task dictionary to validate

        Returns:
            Validation result with 'valid' (bool) and 'reason' (str)
        """
        if not isinstance(task, dict):
            return {"valid": False, "reason": "Task must be a dictionary"}

        if "type" not in task:
            return {"valid": False, "reason": "Task missing 'type' field"}

        task_type = task.get("type", "")
        if not isinstance(task_type, str):
            return {"valid": False, "reason": "Task 'type' must be a string"}

        if not task_type:
            return {"valid": False, "reason": "Task 'type' cannot be empty"}

        # Security check: task type should not contain dangerous keywords
        dangerous_type_keywords = [
            "sign_", "stake", "unstake", "transfer", "send_tao",
            "create_wallet", "reveal_seed", "export_key", "show_mnemonic",
        ]
        task_lower = task_type.lower()
        for kw in dangerous_type_keywords:
            if kw in task_lower:
                # Not a validation error - will be classified as DANGER
                logger.warning(
                    "Task type '%s' contains potentially dangerous keyword '%s'",
                    task_type, kw,
                )

        return {"valid": True, "reason": ""}

    @staticmethod
    def _resolve_agent_identity(agent_instance: Any) -> tuple[str | None, str]:
        """
        Resolve an agent's ``AGENT_NAME`` and ``AGENT_VERSION``.

        Per SPEC.md, agents declare these as module-level constants. Some
        also expose them on the class. This helper checks the instance,
        the class, and the defining module so any of those styles works.
        """
        sources: list[Any] = [agent_instance, type(agent_instance)]
        module = sys.modules.get(type(agent_instance).__module__)
        if module is not None:
            sources.append(module)

        name: str | None = None
        version: str = "unknown"
        for src in sources:
            if name is None:
                candidate = getattr(src, "AGENT_NAME", None)
                if candidate:
                    name = candidate
            if version == "unknown":
                candidate = getattr(src, "AGENT_VERSION", None)
                if candidate:
                    version = candidate
            if name and version != "unknown":
                break
        return name, version

    def _log_event(self, **kwargs: Any) -> None:
        """
        Log an event to the run log.

        Thread-safe: takes ``_log_lock`` so concurrent ``execute_task``
        workers can't drop or interleave events into ``run_log``.

        Args:
            **kwargs: Event fields to record
        """
        event = {
            "timestamp": time.time(),
            **kwargs,
        }
        with self._log_lock:
            self.run_log.append(event)

    def _agent_lock(self, agent_name: str) -> threading.Lock:
        """
        Return the per-agent serialisation lock, creating it lazily.

        Most agents keep mutable instance state (``self._status``,
        counters, last-seen timestamps, …) that isn't safe to mutate
        from multiple threads at once. The parallel ``execute_run``
        path therefore acquires this lock before calling ``agent.run``,
        so two tasks that route to **different** agents run concurrently
        but two tasks routed to the **same** agent serialise.
        """
        with self._agent_locks_lock:
            lock = self._agent_locks.get(agent_name)
            if lock is None:
                lock = threading.Lock()
                self._agent_locks[agent_name] = lock
            return lock

    def _generate_recommendations(self) -> list[dict]:
        """
        Generate recommendations based on orchestrator state.

        Returns:
            List of recommendation dictionaries
        """
        recommendations: list[dict] = []

        if self.approval_gate.wallet_mode == "NO_WALLET":
            recommendations.append({
                "category": "wallet",
                "priority": "HIGH",
                "message": (
                    "Wallet is in NO_WALLET mode. Set to WATCH_ONLY "
                    "to monitor wallets, or FULL for all operations."
                ),
            })

        if len(self.agents) < 15:
            recommendations.append({
                "category": "agents",
                "priority": "MEDIUM",
                "message": (
                    f"Only {len(self.agents)}/15 agents registered. "
                    "Register all agents for full swarm capability."
                ),
            })

        if not self._safety_override:
            recommendations.append({
                "category": "safety",
                "priority": "INFO",
                "message": (
                    "safety_override is False. DANGER actions will be "
                    "reported as plans only. This is the recommended setting."
                ),
            })

        blocked = [
            e for e in self.run_log
            if e.get("event_type") == "task_blocked"
        ]
        if blocked:
            recommendations.append({
                "category": "safety",
                "priority": "HIGH",
                "message": (
                    f"{len(blocked)} DANGER action(s) were blocked. "
                    "Review these carefully before overriding."
                ),
            })

        return recommendations
