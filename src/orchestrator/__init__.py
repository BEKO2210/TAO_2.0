"""
Orchestrator module for TAO/Bittensor Multi-Agent System.

Exports the core orchestration components:
- ApprovalGate: Safety classification gate
- TaskRouter: Task-to-agent routing
- SwarmOrchestrator: Central coordination hub
"""

from src.orchestrator.approval_gate import ApprovalGate, Classification
from src.orchestrator.task_router import TaskRouter
from src.orchestrator.orchestrator import SwarmOrchestrator

__all__ = [
    "ApprovalGate",
    "Classification",
    "TaskRouter",
    "SwarmOrchestrator",
]
