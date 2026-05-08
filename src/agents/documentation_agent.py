"""
Documentation Agent (Agent 15).

Maintains README, KIMI.md, and run logs. Keeps documentation
current with system state and activity.

Provides documentation status reports.
"""

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "documentation_agent"
AGENT_VERSION: str = "1.0.0"


class DocumentationAgent:
    """
    Agent for maintaining project documentation.

    Keeps README.md, KIMI.md, and run logs up to date with the
current system state. Generates documentation status reports
    and identifies outdated documentation.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the DocumentationAgent.

        Args:
            config: Configuration with optional:
                - project_root: Project root directory
                - docs_dir: Documentation directory
                - auto_update: Enable auto-update (default False)
        """
        self.config: dict = config
        self._status: str = "idle"
        self._project_root: str = config.get("project_root", ".")
        self._docs_dir: str = config.get("docs_dir", "./docs")
        self._auto_update: bool = config.get("auto_update", False)
        self._doc_log: list[dict] = []

        logger.info(
            "DocumentationAgent initialized (root=%s, auto_update=%s)",
            self._project_root, self._auto_update,
        )

    def run(self, task: dict) -> dict:
        """
        Run documentation maintenance.

        Args:
            task: Dictionary with 'params' containing:
                - action: "status", "update_readme", "update_kimi", "update_logs"
                - content: New content to document
                - run_data: Run data to log

        Returns:
            Documentation status report
        """
        self._status = "running"
        params = task.get("params", {})
        action = params.get("action", "status")

        logger.info("DocumentationAgent: action=%s", action)

        try:
            if action == "status":
                result = self._get_doc_status(params)
            elif action == "update_readme":
                result = self._update_readme(params)
            elif action == "update_kimi":
                result = self._update_kimi(params)
            elif action == "update_logs":
                result = self._update_run_logs(params)
            else:
                result = {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                }

            self._doc_log.append({
                "timestamp": time.time(),
                "action": action,
            })
            self._status = "complete"
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("DocumentationAgent: failed: %s", e)
            raise

    def get_status(self) -> dict:
        """
        Get current agent status.

        Returns:
            Status dictionary
        """
        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "status": self._status,
            "docs_updated": len(self._doc_log),
        }

    def validate_input(self, task: dict) -> tuple[bool, str]:
        """
        Validate task input.

        Args:
            task: Task dictionary to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(task, dict):
            return False, "Task must be a dictionary"
        params = task.get("params", {})
        action = params.get("action", "status")
        valid_actions = ["status", "update_readme", "update_kimi", "update_logs"]
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"
        return True, ""

    def _get_doc_status(self, params: dict) -> dict:
        """
        Get documentation status.

        Args:
            params: Status parameters

        Returns:
            Documentation status report
        """
        docs: dict[str, dict] = {}
        outdated: list[str] = []

        # Check README.md
        readme_path = os.path.join(self._project_root, "README.md")
        readme_status = self._check_file_status(readme_path)
        docs["README.md"] = readme_status
        if readme_status.get("is_outdated", False):
            outdated.append("README.md")

        # Check KIMI.md
        kimi_path = os.path.join(self._project_root, "KIMI.md")
        kimi_status = self._check_file_status(kimi_path)
        docs["KIMI.md"] = kimi_status
        if kimi_status.get("is_outdated", False):
            outdated.append("KIMI.md")

        # Check docs/ directory
        docs_dir_status = self._check_docs_dir()

        # Overall status
        total_docs = len(docs)
        outdated_count = len(outdated)
        overall = "UP_TO_DATE" if outdated_count == 0 else "NEEDS_UPDATE"

        return {
            "status": "checked",
            "overall_status": overall,
            "documentation": docs,
            "docs_directory": docs_dir_status,
            "outdated_files": outdated,
            "stats": {
                "total_tracked": total_docs,
                "outdated": outdated_count,
                "up_to_date": total_docs - outdated_count,
            },
            "recommendations": [
                f"Update {f}" for f in outdated
            ] if outdated else ["All documentation is up to date"],
            "timestamp": time.time(),
        }

    def _update_readme(self, params: dict) -> dict:
        """
        Generate README.md content.

        Args:
            params: Update parameters

        Returns:
            README update result
        """
        content = params.get("content", {})

        readme_sections: list[dict] = [
            {
                "heading": "# TAO / Bittensor Multi-Agent System",
                "content": "A multi-agent swarm for Bittensor/TAO exploration and operations.",
                "required": True,
            },
            {
                "heading": "## Architecture",
                "content": (
                    "The system consists of 15 specialized agents coordinated by "
                    "a central orchestrator with an ApprovalGate for safety."
                ),
                "required": True,
            },
            {
                "heading": "## Agents",
                "content": self._list_agents(),
                "required": True,
            },
            {
                "heading": "## Quick Start",
                "content": (
                    "```bash\n"
                    "pip install -r requirements.txt\n"
                    "python -m src.cli.tao_swarm\n"
                    "```"
                ),
                "required": True,
            },
            {
                "heading": "## Safety",
                "content": (
                    "- Wallet mode: NO_WALLET by default\n"
                    "- DANGER actions are reported as plans only\n"
                    "- No seeds or private keys are ever requested\n"
                    "- ApprovalGate classifies all actions\n"
                ),
                "required": True,
            },
            {
                "heading": "## Project Structure",
                "content": self._get_project_structure(),
                "required": True,
            },
        ]

        # Generate full README content
        readme_content = "\n\n".join(
            f"{s['heading']}\n\n{s['content']}" for s in readme_sections
        )

        return {
            "status": "readme_generated",
            "sections": len(readme_sections),
            "content_preview": readme_content[:500] + "..." if len(readme_content) > 500 else readme_content,
            "full_content_length": len(readme_content),
            "filename": "README.md",
            "timestamp": time.time(),
        }

    def _update_kimi(self, params: dict) -> dict:
        """
        Generate KIMI.md content.

        Args:
            params: Update parameters

        Returns:
            KIMI update result
        """
        kimi_content = self._generate_kimi_content()

        return {
            "status": "kimi_generated",
            "content_preview": kimi_content[:500] + "..." if len(kimi_content) > 500 else kimi_content,
            "full_content_length": len(kimi_content),
            "filename": "KIMI.md",
            "timestamp": time.time(),
        }

    def _update_run_logs(self, params: dict) -> dict:
        """
        Update run logs.

        Args:
            params: Update parameters with 'run_data'

        Returns:
            Log update result
        """
        run_data = params.get("run_data", {})

        if not run_data:
            return {
                "status": "no_data",
                "message": "No run data provided",
            }

        log_entry = {
            "timestamp": time.time(),
            "run_id": run_data.get("run_id", f"run_{int(time.time())}"),
            "status": run_data.get("status", "unknown"),
            "tasks_completed": run_data.get("tasks_completed", 0),
            "agents_used": run_data.get("agents_used", []),
        }

        return {
            "status": "logged",
            "log_entry": log_entry,
            "total_entries": len(self._doc_log),
            "timestamp": time.time(),
        }

    def _check_file_status(self, file_path: str) -> dict:
        """Check the status of a documentation file."""
        exists = os.path.exists(file_path)

        if not exists:
            return {
                "exists": False,
                "size": 0,
                "last_modified": None,
                "is_outdated": True,
                "reason": "File does not exist",
            }

        stat = os.stat(file_path)
        age_days = (time.time() - stat.st_mtime) / 86400

        return {
            "exists": True,
            "size": stat.st_size,
            "last_modified": stat.st_mtime,
            "age_days": round(age_days, 1),
            "is_outdated": age_days > 7,  # Consider > 7 days as potentially outdated
            "reason": f"Last modified {round(age_days, 1)} days ago" if age_days > 7 else "Up to date",
        }

    def _check_docs_dir(self) -> dict:
        """Check the docs/ directory status."""
        if not os.path.isdir(self._docs_dir):
            return {
                "exists": False,
                "files": [],
                "recommendation": "Create docs/ directory for extended documentation",
            }

        files = []
        for f in os.listdir(self._docs_dir):
            fpath = os.path.join(self._docs_dir, f)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({
                    "name": f,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })

        return {
            "exists": True,
            "files": files,
            "file_count": len(files),
        }

    def _list_agents(self) -> str:
        """Generate a list of all agents."""
        agents: list[tuple[str, str]] = [
            ("system_check_agent", "System environment check"),
            ("protocol_research_agent", "Bittensor protocol research"),
            ("subnet_discovery_agent", "Subnet discovery and cataloging"),
            ("subnet_scoring_agent", "Subnet scoring with 10 criteria"),
            ("wallet_watch_agent", "Read-only wallet monitoring"),
            ("market_trade_agent", "TAO market analysis (paper trading)"),
            ("risk_security_agent", "Risk review with VETO power"),
            ("miner_engineering_agent", "Miner setup analysis"),
            ("validator_engineering_agent", "Validator feasibility analysis"),
            ("training_experiment_agent", "Training run planning"),
            ("infra_devops_agent", "Infrastructure setup"),
            ("dashboard_design_agent", "Dashboard design"),
            ("fullstack_dev_agent", "Full-stack development planning"),
            ("qa_test_agent", "QA testing and compliance"),
            ("documentation_agent", "Documentation maintenance"),
        ]

        lines: list[str] = []
        for name, desc in agents:
            lines.append(f"- **{name}**: {desc}")
        return "\n".join(lines)

    def _get_project_structure(self) -> str:
        """Generate project structure description."""
        return (
            "```\n"
            "src/\n"
            "  orchestrator/\n"
            "    __init__.py\n"
            "    approval_gate.py      - Safety classification\n"
            "    task_router.py        - Task routing\n"
            "    orchestrator.py       - Central coordination\n"
            "  agents/\n"
            "    __init__.py\n"
            "    system_check_agent.py\n"
            "    protocol_research_agent.py\n"
            "    subnet_discovery_agent.py\n"
            "    subnet_scoring_agent.py\n"
            "    wallet_watch_agent.py\n"
            "    market_trade_agent.py\n"
            "    risk_security_agent.py\n"
            "    miner_engineering_agent.py\n"
            "    validator_engineering_agent.py\n"
            "    training_experiment_agent.py\n"
            "    infra_devops_agent.py\n"
            "    dashboard_design_agent.py\n"
            "    fullstack_dev_agent.py\n"
            "    qa_test_agent.py\n"
            "    documentation_agent.py\n"
            "  collectors/\n"
            "  scoring/\n"
            "  dashboard/\n"
            "  cli/\n"
            "tests/\n"
            "docs/\n"
            "```"
        )

    def _generate_kimi_content(self) -> str:
        """Generate KIMI.md content."""
        sections = [
            ("# TAO Swarm - System Context", self._get_kimi_overview()),
            ("## Architecture", self._get_kimi_architecture()),
            ("## Agent Responsibilities", self._get_kimi_agents()),
            ("## Safety Rules", self._get_kimi_safety()),
            ("## Common Patterns", self._get_kimi_patterns()),
            ("## Development Notes", self._get_kimi_dev_notes()),
        ]

        return "\n\n".join(f"{heading}\n\n{content}" for heading, content in sections)

    def _get_kimi_overview(self) -> str:
        return (
            "A multi-agent system for Bittensor/TAO exploration.\n\n"
            "- 15 specialized agents\n"
            "- Central orchestrator with ApprovalGate\n"
            "- Task routing system\n"
            "- Dark-themed monitoring dashboard\n"
            "- All wallet operations are read-only by default\n"
            "- DANGER actions require explicit manual approval"
        )

    def _get_kimi_architecture(self) -> str:
        return (
            "```\n"
            "SwarmOrchestrator\n"
            "  |- ApprovalGate (SAFE/CAUTION/DANGER)\n"
            "  |- TaskRouter (15 task type mappings)\n"
            "  |- 15 Agents\n"
            "```\n\n"
            "All tasks go through ApprovalGate before execution.\n"
            "DANGER tasks are blocked and returned as plans."
        )

    def _get_kimi_agents(self) -> str:
        lines: list[str] = []
        for name, desc in [
            ("system_check_agent", "Hardware/Software check"),
            ("protocol_research_agent", "Protocol knowledge"),
            ("subnet_discovery_agent", "Subnet catalog"),
            ("subnet_scoring_agent", "10-criteria scoring"),
            ("wallet_watch_agent", "Watch-only monitoring"),
            ("market_trade_agent", "Paper trading analysis"),
            ("risk_security_agent", "STOP/REJECT/PAUSE/PROCEED"),
            ("miner_engineering_agent", "Setup analysis"),
            ("validator_engineering_agent", "Feasibility check"),
            ("training_experiment_agent", "Training plans"),
            ("infra_devops_agent", "Docker/Make/cron"),
            ("dashboard_design_agent", "UI spec"),
            ("fullstack_dev_agent", "Dev planning"),
            ("qa_test_agent", "Secret/compliance checks"),
            ("documentation_agent", "README/KIMI/logs"),
        ]:
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def _get_kimi_safety(self) -> str:
        return (
            "- Wallet mode: NO_WALLET by default\n"
            "- No agent requests seeds or keys\n"
            "- DANGER = plan only, never execute\n"
            "- Risk agent has VETO power (STOP)\n"
            "- QA agent checks compliance on every run"
        )

    def _get_kimi_patterns(self) -> str:
        return (
            "- All agents: config -> run(task) -> status -> validate_input(task)\n"
            "- Tasks: {type, params} dict\n"
            "- Results: {status, output} dict\n"
            "- Classify action before execute\n"
            "- Log every event"
        )

    def _get_kimi_dev_notes(self) -> str:
        return (
            "- Python 3.10+\n"
            "- Type hints everywhere\n"
            "- Docstrings for all classes/methods\n"
            "- Logging (import logging)\n"
            "- Never use print() in production\n"
            "- Security: no secrets in code"
        )
