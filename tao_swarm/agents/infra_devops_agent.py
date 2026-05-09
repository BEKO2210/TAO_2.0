"""
Infrastructure & DevOps Agent (Agent 11).

Handles project structure, Dockerfiles, docker-compose, Makefiles,
and cron/scheduler configurations for monitoring.

Provides infrastructure setup notes.
"""

import logging
import time

logger = logging.getLogger(__name__)

AGENT_NAME: str = "infra_devops_agent"
AGENT_VERSION: str = "1.0.0"


class InfraDevopsAgent:
    """
    Agent for infrastructure and DevOps setup.

    Generates project structure, Dockerfiles, docker-compose files,
    Makefiles, and cron/scheduler configurations for the TAO/Bittensor
    monitoring and operation system.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the InfraDevopsAgent.

        Args:
            config: Configuration with optional:
                - project_name: Project name
                - output_dir: Output directory
                - services: List of services to configure
        """
        self.config: dict = config
        self._status: str = "idle"
        self._project_name: str = config.get("project_name", "tao-swarm")
        self._output_dir: str = config.get("output_dir", ".")
        self._services: list[str] = config.get("services", ["dashboard", "api", "monitor"])
        self._setup_log: list[dict] = []

        logger.info(
            "InfraDevopsAgent initialized (project=%s, services=%d)",
            self._project_name, len(self._services),
        )

    def run(self, task: dict) -> dict:
        """
        Run infrastructure setup.

        Args:
            task: Dictionary with 'params' containing:
                - action: "structure", "dockerfile", "compose", "makefile", "cron"
                - service_name: Target service name

        Returns:
            Infrastructure setup notes
        """
        self._status = "running"
        params = task.get("params", {})
        action = params.get("action", "structure")

        logger.info("InfraDevopsAgent: action=%s", action)

        try:
            if action == "structure":
                result = self._generate_structure(params)
            elif action == "dockerfile":
                result = self._generate_dockerfile(params)
            elif action == "compose":
                result = self._generate_compose(params)
            elif action == "makefile":
                result = self._generate_makefile(params)
            elif action == "cron":
                result = self._generate_cron(params)
            else:
                result = {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                }

            self._setup_log.append({
                "timestamp": time.time(),
                "action": action,
            })
            self._status = "complete"
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("InfraDevopsAgent: failed: %s", e)
            return {
                "status": "error",
                "reason": str(e),
                "agent_name": AGENT_NAME,
                "task_type": task.get("type"),
            }

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
            "setups_generated": len(self._setup_log),
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
        if "type" not in task:
            return False, "task.type is required"
        params = task.get("params", {})
        action = params.get("action", "structure")
        valid_actions = ["structure", "dockerfile", "compose", "makefile", "cron"]
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"
        return True, ""

    def _generate_structure(self, params: dict) -> dict:
        """
        Generate recommended project structure.

        Args:
            params: Structure parameters

        Returns:
            Project structure
        """
        structure = {
            "project_name": self._project_name,
            "directories": [
                {
                    "path": "src/agents",
                    "description": "Agent implementations",
                    "files": ["__init__.py", "*.py"],
                },
                {
                    "path": "src/orchestrator",
                    "description": "Orchestrator and routing",
                    "files": ["__init__.py", "orchestrator.py", "task_router.py", "approval_gate.py"],
                },
                {
                    "path": "src/collectors",
                    "description": "Data collectors",
                    "files": ["__init__.py", "*.py"],
                },
                {
                    "path": "src/scoring",
                    "description": "Scoring modules",
                    "files": ["__init__.py", "*.py"],
                },
                {
                    "path": "src/dashboard",
                    "description": "Dashboard application",
                    "files": ["__init__.py", "app.py"],
                },
                {
                    "path": "src/cli",
                    "description": "CLI tools",
                    "files": ["__init__.py", "*.py"],
                },
                {
                    "path": "tests",
                    "description": "Test suite",
                    "files": ["__init__.py", "test_*.py"],
                },
                {
                    "path": "docs",
                    "description": "Documentation",
                    "files": ["*.md"],
                },
                {
                    "path": "experiments",
                    "description": "Experiment logs",
                    "files": ["*.json", "*.log"],
                },
                {
                    "path": "docker",
                    "description": "Docker configuration",
                    "files": ["Dockerfile", "docker-compose.yml"],
                },
                {
                    "path": "config",
                    "description": "Configuration files",
                    "files": ["*.yaml", "*.json", ".env.example"],
                },
                {
                    "path": "scripts",
                    "description": "Utility scripts",
                    "files": ["*.sh", "*.py"],
                },
            ],
            "root_files": [
                {"file": "README.md", "description": "Project documentation"},
                {"file": "Makefile", "description": "Build automation"},
                {"file": "requirements.txt", "description": "Python dependencies"},
                {"file": ".env.example", "description": "Environment template"},
                {"file": ".gitignore", "description": "Git ignore rules"},
                {"file": "docker-compose.yml", "description": "Docker compose config"},
            ],
        }

        return {
            "status": "structure_generated",
            "structure": structure,
            "note": "This is the recommended structure. Adapt as needed.",
            "timestamp": time.time(),
        }

    def _generate_dockerfile(self, params: dict) -> dict:
        """
        Generate a Dockerfile for the project.

        Args:
            params: Dockerfile parameters

        Returns:
            Dockerfile content
        """
        service = params.get("service_name", "main")

        dockerfile = f"""# {self._project_name} - {service} service
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    git \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY config/ ./config/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port (if needed)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
    CMD python -c "print('healthy')" || exit 1

# Default command
CMD ["python", "-m", "tao_swarm.orchestrator.orchestrator"]
"""

        return {
            "status": "dockerfile_generated",
            "service": service,
            "dockerfile": dockerfile,
            "filename": f"docker/Dockerfile.{service}",
            "timestamp": time.time(),
        }

    def _generate_compose(self, params: dict) -> dict:
        """
        Generate docker-compose.yml.

        Args:
            params: Compose parameters

        Returns:
            docker-compose content
        """
        compose = """version: "3.8"

services:
  dashboard:
    build:
      context: .
      dockerfile: docker/Dockerfile.main
    ports:
      - "8000:8000"
    environment:
      - PYTHONPATH=/app
      - LOG_LEVEL=INFO
    volumes:
      - ./experiments:/app/experiments
      - ./config:/app/config:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "print('healthy')"]
      interval: 30s
      timeout: 10s
      retries: 3

  monitor:
    build:
      context: .
      dockerfile: docker/Dockerfile.main
    command: python -m src.cli.tao_swarm monitor
    environment:
      - PYTHONPATH=/app
      - LOG_LEVEL=INFO
    volumes:
      - ./experiments:/app/experiments
    restart: unless-stopped
    depends_on:
      - dashboard

  # Optional: Redis for caching
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped
    volumes:
      - redis_data:/data

volumes:
  redis_data:
"""

        return {
            "status": "compose_generated",
            "compose": compose,
            "filename": "docker-compose.yml",
            "services": ["dashboard", "monitor", "redis"],
            "timestamp": time.time(),
        }

    def _generate_makefile(self, params: dict) -> dict:
        """
        Generate a Makefile.

        Args:
            params: Makefile parameters

        Returns:
            Makefile content
        """
        makefile = """# TAO Swarm Makefile
.PHONY: help install test lint docker-up docker-down clean setup

help: ## Show this help
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\\n", $$1, $$2}'

setup: ## Initial project setup
	python -m venv venv
	. venv/bin/activate && pip install --upgrade pip
	. venv/bin/activate && pip install -r requirements.txt
	cp .env.example .env
	@echo "Setup complete. Edit .env with your settings."

install: ## Install dependencies
	pip install -r requirements.txt

test: ## Run tests
	python -m pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage
	python -m pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

lint: ## Run linting
	python -m flake8 src/ --max-line-length=100
	python -m mypy src/ --ignore-missing-imports

fmt: ## Format code
	python -m black src/ tests/ --line-length=100

docker-build: ## Build Docker images
	docker-compose build

docker-up: ## Start Docker containers
	docker-compose up -d

docker-down: ## Stop Docker containers
	docker-compose down

docker-logs: ## View Docker logs
	docker-compose logs -f

clean: ## Clean generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

run: ## Run the orchestrator
	python -m src.cli.tao_swarm

monitor: ## Run monitoring
	python -m src.cli.tao_swarm monitor

safety-check: ## Run safety checks
	python -m pytest tests/test_approval_gate.py tests/test_wallet_safety.py -v
"""

        return {
            "status": "makefile_generated",
            "makefile": makefile,
            "filename": "Makefile",
            "commands": [
                "make setup", "make install", "make test",
                "make lint", "make docker-up", "make clean",
            ],
            "timestamp": time.time(),
        }

    def _generate_cron(self, params: dict) -> dict:
        """
        Generate cron/scheduler configuration.

        Args:
            params: Cron parameters

        Returns:
            Cron configuration
        """
        jobs: list[dict] = [
            {
                "name": "system_check",
                "schedule": "0 */6 * * *",  # Every 6 hours
                "command": "python -m src.cli.tao_swarm system-check >> logs/system.log 2>&1",
                "description": "Run system health check every 6 hours",
            },
            {
                "name": "wallet_snapshot",
                "schedule": "0 * * * *",  # Every hour
                "command": "python -m src.cli.tao_swarm wallet-snapshot >> logs/wallet.log 2>&1",
                "description": "Take hourly wallet snapshot",
            },
            {
                "name": "market_update",
                "schedule": "*/15 * * * *",  # Every 15 minutes
                "command": "python -m src.cli.tao_swarm market-update >> logs/market.log 2>&1",
                "description": "Update market data every 15 minutes",
            },
            {
                "name": "subnet_scan",
                "schedule": "0 0 * * *",  # Daily at midnight
                "command": "python -m src.cli.tao_swarm subnet-scan >> logs/subnets.log 2>&1",
                "description": "Daily subnet discovery scan",
            },
            {
                "name": "risk_review",
                "schedule": "0 2 * * *",  # Daily at 2 AM
                "command": "python -m src.cli.tao_swarm risk-review >> logs/risk.log 2>&1",
                "description": "Daily risk and security review",
            },
            {
                "name": "log_rotation",
                "schedule": "0 3 * * 0",  # Weekly on Sunday at 3 AM
                "command": "find logs/ -name '*.log' -mtime +7 -delete",
                "description": "Weekly log rotation - delete logs older than 7 days",
            },
        ]

        # Generate crontab entry
        crontab_lines: list[str] = [
            "# TAO Swarm Monitoring Cron Jobs",
            f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "SHELL=/bin/bash",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH=/app",
            "",
        ]

        for job in jobs:
            crontab_lines.append(f"# {job['description']}")
            crontab_lines.append(f"{job['schedule']} {job['command']}")
            crontab_lines.append("")

        crontab = "\n".join(crontab_lines)

        return {
            "status": "cron_generated",
            "jobs": jobs,
            "crontab": crontab,
            "filename": "scripts/crontab.txt",
            "installation": "Run: crontab scripts/crontab.txt",
            "timestamp": time.time(),
        }
