"""
Swarm Orchestrator for TAO/Bittensor Multi-Agent System.

The orchestrator is the central coordination hub. It manages agent
registration, task execution with approval gating, conflict detection,
and report generation across all 15 specialized agents.
"""

import logging
import sys
import time
from typing import Any

from src.orchestrator.approval_gate import ApprovalGate
from src.orchestrator.task_router import TaskRouter

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
        self._safety_override: bool = config.get("safety_override", False)
        self._start_time: float = time.time()

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

            # Run the agent
            logger.info(
                "Executing task via %s (classification=%s)",
                agent_name, classification.value,
            )
            output = agent.run(task)

            # Lift the agent's internal per-call ``status`` field (e.g.
            # "complete", "snapshot", "plan_created", "INSUFFICIENT_DATA",
            # "error") into a top-level ``agent_result_status`` so callers
            # don't have to dig into ``output`` and don't have to handle
            # the case where some agents include it and some don't.
            agent_result_status = (
                output.get("status") if isinstance(output, dict) else None
            )

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

    def execute_run(self, run_plan: dict) -> dict:
        """
        Execute a multi-task run plan.

        Each task in the plan is validated and executed sequentially.
        DANGER tasks are blocked and returned as plans.

        Args:
            run_plan: Dictionary with 'tasks' list, each with 'type' and 'params'

        Returns:
            Run result with 'results' list, 'summary', and 'next_actions'
        """
        tasks = run_plan.get("tasks", [])
        if not tasks:
            return {
                "status": "error",
                "error": "Run plan contains no tasks",
                "results": [],
            }

        run_id = run_plan.get("run_id", f"run_{int(time.time())}")
        logger.info(
            "=" * 60
        )
        logger.info(
            "Starting run: %s with %d tasks", run_id, len(tasks)
        )

        self._log_event(
            event_type="run_start",
            run_id=run_id,
            task_count=len(tasks),
        )

        results: list[dict] = []
        success_count = 0
        blocked_count = 0
        error_count = 0

        # Validate the entire plan through the approval gate
        plan_validation = self.approval_gate.validate_plan({
            "actions": [{"type": t.get("type", "unknown"), "params": t.get("params", {})} for t in tasks]
        })

        logger.info(
            "Run plan validation: classification=%s, valid=%s",
            plan_validation["classification"],
            plan_validation["valid"],
        )

        for idx, task in enumerate(tasks):
            logger.info(
                "Executing task %d/%d: %s", idx + 1, len(tasks), task.get("type", "?")
            )

            result = self.execute_task(task)
            results.append(result)

            if result["status"] == "success":
                success_count += 1
            elif result["status"] == "blocked":
                blocked_count += 1
            else:
                error_count += 1

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

        # Safety status
        danger_events = [
            e for e in self.run_log
            if e.get("event_type") == "task_blocked"
        ]

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

        Args:
            **kwargs: Event fields to record
        """
        event = {
            "timestamp": time.time(),
            **kwargs,
        }
        self.run_log.append(event)

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
