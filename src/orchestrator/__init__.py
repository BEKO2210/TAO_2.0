"""
Orchestrator module for TAO/Bittensor Multi-Agent System.

Exports the core orchestration components:
- ApprovalGate: Safety classification gate
- TaskRouter: Task-to-agent routing
- SwarmOrchestrator: Central coordination hub
- AgentContext: Pull-based shared context bus across agents
- load_plugins: User-defined external agents (path or entry-point based)
"""

from src.orchestrator.approval_gate import ApprovalGate, Classification
from src.orchestrator.context import AgentContext
from src.orchestrator.orchestrator import SwarmOrchestrator
from src.orchestrator.plugin_loader import (
    ON_CONFLICT_ERROR,
    ON_CONFLICT_REPLACE,
    ON_CONFLICT_SKIP,
    PluginLoadSummary,
    load_plugins,
)
from src.orchestrator.resilience import (
    CancelToken,
    RetryPolicy,
    TaskTimeoutError,
)
from src.orchestrator.task_router import TaskRouter

__all__ = [
    "ON_CONFLICT_ERROR",
    "ON_CONFLICT_REPLACE",
    "ON_CONFLICT_SKIP",
    "AgentContext",
    "ApprovalGate",
    "CancelToken",
    "Classification",
    "PluginLoadSummary",
    "RetryPolicy",
    "SwarmOrchestrator",
    "TaskRouter",
    "TaskTimeoutError",
    "load_plugins",
]
