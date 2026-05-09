"""
Task Router Module for TAO/Bittensor Multi-Agent System.

Routes incoming tasks to the appropriate agent based on task_type.
Maintains a registry of all available agents and provides task-type
mappings for the 15 specialized agents in the swarm.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default task-type to agent-name mappings for the TAO/Bittensor swarm
_DEFAULT_TASK_MAP: dict[str, str] = {
    # System & Environment
    "system_check": "system_check_agent",
    # Research & Discovery
    "protocol_research": "protocol_research_agent",
    "subnet_discovery": "subnet_discovery_agent",
    "subnet_scoring": "subnet_scoring_agent",
    # Wallet & Finance
    "wallet_watch": "wallet_watch_agent",
    "market_analysis": "market_trade_agent",
    "risk_review": "risk_security_agent",
    # Engineering
    "miner_setup": "miner_engineering_agent",
    "validator_setup": "validator_engineering_agent",
    "training": "training_experiment_agent",
    "infrastructure": "infra_devops_agent",
    # Design & Development
    "dashboard": "dashboard_design_agent",
    "development": "fullstack_dev_agent",
    "quality_assurance": "qa_test_agent",
    "documentation": "documentation_agent",
}


class TaskRouter:
    """
    Routes tasks to the appropriate agent in the TAO/Bittensor swarm.

    Maintains a registry of agent instances and maps task types to
    agent names. Supports dynamic agent registration and fallback
    routing for unknown task types.
    """

    def __init__(self) -> None:
        """Initialize the TaskRouter with empty agent registry."""
        self._agents: dict[str, Any] = {}
        self._task_map: dict[str, str] = dict(_DEFAULT_TASK_MAP)
        logger.info(
            "TaskRouter initialized with %d default task mappings",
            len(self._task_map),
        )

    def register_agent(self, agent_name: str, agent_instance: Any) -> None:
        """
        Register an agent instance with the router.

        Auto-discovers ``AGENT_CAPABILITIES`` (if declared) and adds
        each declared ``task_type`` to the routing table. Existing
        ``_DEFAULT_TASK_MAP`` entries win on conflict so capabilities
        can supplement but not override the curated defaults.

        Args:
            agent_name: Unique name for the agent (e.g. "system_check_agent")
            agent_instance: The agent class instance
        """
        self._agents[agent_name] = agent_instance

        # Pick up agent-declared capabilities so plug-ins (and any
        # built-in that adopts the new convention) auto-route without
        # editing _DEFAULT_TASK_MAP.
        from src.orchestrator.capabilities import discover_capabilities

        capabilities = discover_capabilities(agent_instance)
        added: list[str] = []
        for cap in capabilities:
            if cap.task_type in self._task_map:
                continue  # default map wins on conflict
            self._task_map[cap.task_type] = agent_name
            added.append(cap.task_type)

        logger.info(
            "Agent registered: %s (class=%s, capabilities=%d, +%d task_types)",
            agent_name,
            type(agent_instance).__name__,
            len(capabilities),
            len(added),
        )

    def list_capabilities(self) -> list[dict]:
        """
        Return a flat list of capability dicts across all registered
        agents — what the dashboard / CLI renders as "what can the
        swarm do?". Each entry carries the owning agent_name so the
        dashboard can group by agent.
        """
        from src.orchestrator.capabilities import discover_capabilities

        out: list[dict] = []
        for agent_name, instance in self._agents.items():
            for cap in discover_capabilities(instance):
                row = cap.to_dict()
                row["agent"] = agent_name
                out.append(row)
        return out

    def route_task(self, task: dict) -> str:
        """
        Route a task dictionary to the appropriate agent.

        Args:
            task: Dictionary with at least a 'type' key

        Returns:
            Name of the agent responsible for this task

        Raises:
            ValueError: If no matching agent can be found
        """
        task_type = task.get("type", "")
        if not task_type:
            raise ValueError("Task missing 'type' field")

        agent_name = self._task_map.get(task_type, "")
        if not agent_name:
            # Try fuzzy matching: check if task_type contains a known keyword
            for mapped_type, mapped_agent in self._task_map.items():
                if mapped_type in task_type or task_type in mapped_type:
                    logger.info(
                        "Fuzzy match: task_type='%s' -> agent='%s'",
                        task_type, mapped_agent,
                    )
                    return mapped_agent

            # Check task metadata for agent hint
            agent_hint = task.get("agent", "")
            if agent_hint and agent_hint in self._agents:
                logger.info(
                    "Routing via agent hint: '%s'", agent_hint
                )
                return agent_hint

            available = list(self._task_map.keys())
            raise ValueError(
                f"No agent mapped for task_type='{task_type}'. "
                f"Available types: {available}"
            )

        if agent_name not in self._agents:
            logger.warning(
                "Agent '%s' mapped but not registered in router", agent_name
            )

        logger.debug(
            "Task routed: type='%s' -> agent='%s'", task_type, agent_name
        )
        return agent_name

    def get_agent_for_task(self, task_type: str) -> str:
        """
        Get the agent name mapped to a task type (without routing).

        Args:
            task_type: The task type to look up

        Returns:
            Agent name mapped to this task type

        Raises:
            KeyError: If no mapping exists for the task type
        """
        if task_type not in self._task_map:
            raise KeyError(
                f"No agent mapped for task_type='{task_type}'"
            )
        return self._task_map[task_type]

    def list_agents(self) -> list[str]:
        """
        List all registered agent names.

        Returns:
            List of registered agent name strings
        """
        return sorted(self._agents.keys())

    def list_task_types(self) -> list[str]:
        """
        List all known task types.

        Returns:
            List of task type strings
        """
        return sorted(self._task_map.keys())

    def get_agent_instance(self, agent_name: str) -> Any:
        """
        Get a registered agent instance by name.

        Args:
            agent_name: Name of the registered agent

        Returns:
            The agent instance

        Raises:
            KeyError: If agent is not registered
        """
        if agent_name not in self._agents:
            raise KeyError(
                f"Agent '{agent_name}' not registered. "
                f"Registered: {self.list_agents()}"
            )
        return self._agents[agent_name]

    def has_agent(self, agent_name: str) -> bool:
        """
        Check if an agent is registered.

        Args:
            agent_name: Name of the agent to check

        Returns:
            True if the agent is registered
        """
        return agent_name in self._agents

    def add_task_mapping(self, task_type: str, agent_name: str) -> None:
        """
        Add a custom task-type to agent mapping.

        Args:
            task_type: The task type string
            agent_name: The target agent name
        """
        self._task_map[task_type] = agent_name
        logger.info(
            "Task mapping added: '%s' -> '%s'", task_type, agent_name
        )

    def remove_task_mapping(self, task_type: str) -> None:
        """
        Remove a task-type mapping.

        Args:
            task_type: The task type to remove
        """
        if task_type in self._task_map:
            del self._task_map[task_type]
            logger.info("Task mapping removed: '%s'", task_type)

    def get_all_mappings(self) -> dict[str, str]:
        """
        Return a copy of all task-type to agent mappings.

        Returns:
            Dictionary of task_type -> agent_name
        """
        return dict(self._task_map)
