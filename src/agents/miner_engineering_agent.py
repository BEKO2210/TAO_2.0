"""
Miner Engineering Agent (Agent 8).

Analyzes miner setup requirements per subnet, checks repositories,
local test environments, Docker setup, and benchmark scripts.

Provides miner setup notes and test plans.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "miner_engineering_agent"
AGENT_VERSION: str = "1.0.0"


class MinerEngineeringAgent:
    """
    Agent for miner setup analysis and engineering.

    Analyzes miner requirements for specific subnets, validates
    repository setup, plans local test environments, Docker
    configurations, and benchmark scripts.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the MinerEngineeringAgent.

        Args:
            config: Configuration with optional:
                - subnets: List of target subnets
                - use_docker: Prefer Docker setup (default True)
                - local_test: Enable local testing (default True)
                - hardware_profile: Available hardware description
        """
        self.config: dict = config
        self._status: str = "idle"
        self._use_docker: bool = config.get("use_docker", True)
        self._local_test: bool = config.get("local_test", True)
        self._hardware_profile: dict = config.get("hardware_profile", {})
        self._setup_log: list[dict] = []

        logger.info(
            "MinerEngineeringAgent initialized (docker=%s, local_test=%s)",
            self._use_docker, self._local_test,
        )

    def run(self, task: dict) -> dict:
        """
        Run miner engineering analysis.

        Args:
            task: Dictionary with 'params' containing:
                - action: "analyze", "setup_plan", "test_plan", "benchmark"
                - subnet: Target subnet dict or netuid
                - repo_url: Repository URL to analyze

        Returns:
            Miner setup notes and test plan
        """
        self._status = "running"
        params = task.get("params", {})
        action = params.get("action", "analyze")

        logger.info("MinerEngineeringAgent: action=%s", action)

        try:
            if action == "analyze":
                result = self._analyze_subnet(params)
            elif action == "setup_plan":
                result = self._create_setup_plan(params)
            elif action == "test_plan":
                result = self._create_test_plan(params)
            elif action == "benchmark":
                result = self._create_benchmark_plan(params)
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
            logger.exception("MinerEngineeringAgent: failed: %s", e)
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
            "setups_analyzed": len(self._setup_log),
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
        action = params.get("action", "analyze")
        valid_actions = ["analyze", "setup_plan", "test_plan", "benchmark"]
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"
        return True, ""

    def _analyze_subnet(self, params: dict) -> dict:
        """
        Analyze miner setup requirements for a subnet.

        Args:
            params: Parameters with 'subnet' dict or 'netuid'

        Returns:
            Analysis result
        """
        subnet = params.get("subnet", {})
        netuid = subnet.get("netuid", params.get("netuid", 0))
        name = subnet.get("name", f"Subnet-{netuid}")
        category = subnet.get("category", "unknown")
        hw_min = subnet.get("hardware_min", {})

        # Determine framework needs
        framework = self._detect_framework(category)

        # Check hardware compatibility
        hw_check = self._check_hardware_compatibility(hw_min)

        # Estimate setup complexity
        complexity = self._estimate_complexity(subnet, framework)

        return {
            "status": "analyzed",
            "subnet": {
                "netuid": netuid,
                "name": name,
                "category": category,
            },
            "framework": framework,
            "hardware_compatibility": hw_check,
            "setup_complexity": complexity,
            "recommendations": self._get_recommendations(subnet, framework, hw_check),
            "timestamp": time.time(),
        }

    def _create_setup_plan(self, params: dict) -> dict:
        """
        Create a detailed miner setup plan.

        Args:
            params: Setup parameters

        Returns:
            Setup plan dictionary
        """
        subnet = params.get("subnet", {})
        netuid = subnet.get("netuid", params.get("netuid", 0))
        name = subnet.get("name", f"Subnet-{netuid}")
        repo_url = subnet.get("repo_url", params.get("repo_url", ""))
        category = subnet.get("category", "unknown")

        steps: list[dict] = []

        # Step 1: Prerequisites
        steps.append({
            "step": 1,
            "title": "Install Prerequisites",
            "description": "Install Python 3.10+, pip, git, and required system packages",
            "commands": [
                "sudo apt update && sudo apt install -y python3 python3-pip git",
                "pip install --upgrade pip",
            ],
            "classification": "CAUTION",
        })

        # Step 2: Clone Repository
        if repo_url:
            steps.append({
                "step": 2,
                "title": "Clone Miner Repository",
                "description": f"Clone the subnet miner repository from {repo_url}",
                "commands": [
                    f"git clone {repo_url} miner-subnet-{netuid}",
                    f"cd miner-subnet-{netuid}",
                ],
                "classification": "SAFE",
            })
        else:
            steps.append({
                "step": 2,
                "title": "Find Repository",
                "description": f"Search for subnet {netuid} miner repository",
                "commands": [
                    f"# Search GitHub for subnet-{netuid} or '{name}' miner",
                    "# Check bittensor.com documentation for links",
                ],
                "classification": "SAFE",
            })

        # Step 3: Install Dependencies
        steps.append({
            "step": 3,
            "title": "Install Python Dependencies",
            "description": "Install required packages from requirements.txt or setup.py",
            "commands": [
                "pip install -r requirements.txt",
                "# Or: pip install -e .",
            ],
            "classification": "CAUTION",
        })

        # Step 4: Install Bittensor
        steps.append({
            "step": 4,
            "title": "Install Bittensor",
            "description": "Install the bittensor SDK",
            "commands": [
                "pip install bittensor",
                "# Verify: python -c 'import bittensor; print(bittensor.__version__)'",
            ],
            "classification": "CAUTION",
        })

        # Step 5: Docker Setup (optional)
        if self._use_docker:
            steps.append({
                "step": 5,
                "title": "Docker Setup (Optional)",
                "description": "Build and run miner in Docker container",
                "commands": [
                    "docker build -t miner-subnet-{netuid} .",
                    "# Run: docker run -d --gpus all miner-subnet-{netuid}",
                ],
                "classification": "CAUTION",
            })

        # Step 6: Configuration
        steps.append({
            "step": 6,
            "title": "Configure Miner",
            "description": "Set up miner configuration (wallet, network, subnet)",
            "commands": [
                "# Copy example config",
                "cp .env.example .env",
                "# Edit .env with your settings",
                "# Set WALLET_NAME, HOTKEY, NETWORK, NETUID",
            ],
            "classification": "SAFE",
        })

        # Step 7: Registration warning
        steps.append({
            "step": 7,
            "title": "Register on Subnet (DANGER - Manual Only)",
            "description": (
                "Registration requires burning TAO. This is a DANGER action "
                "that must be done manually."
            ),
            "commands": [
                "# DANGER: Only run after full review",
                f"# btcli subnet register --netuid {netuid} --wallet.name YOUR_WALLET",
                "# Review cost and confirm manually",
            ],
            "classification": "DANGER",
        })

        return {
            "status": "plan_created",
            "subnet": {"netuid": netuid, "name": name},
            "setup_steps": steps,
            "total_steps": len(steps),
            "estimated_time_hours": self._estimate_setup_time(subnet),
            "timestamp": time.time(),
        }

    def _create_test_plan(self, params: dict) -> dict:
        """
        Create a local test plan for a miner.

        Args:
            params: Test parameters

        Returns:
            Test plan dictionary
        """
        subnet = params.get("subnet", {})
        netuid = subnet.get("netuid", params.get("netuid", 0))

        tests: list[dict] = [
            {
                "id": "TEST-001",
                "name": "Environment Setup Test",
                "description": "Verify Python, dependencies, and GPU availability",
                "commands": [
                    "python --version",
                    "python -c 'import bittensor; print(bittensor.__version__)'",
                    "python -c 'import torch; print(torch.cuda.is_available())'",
                ],
                "expected": "All imports succeed, GPU detected",
                "classification": "SAFE",
            },
            {
                "id": "TEST-002",
                "name": "Configuration Test",
                "description": "Verify config files and environment variables",
                "commands": [
                    "python -c 'from miner.config import load_config; load_config()'",
                ],
                "expected": "Configuration loads without errors",
                "classification": "SAFE",
            },
            {
                "id": "TEST-003",
                "name": "Model Loading Test",
                "description": "Verify AI model loads correctly",
                "commands": [
                    "python -c 'from miner.model import load_model; load_model()'",
                ],
                "expected": "Model loads into GPU/CPU memory",
                "classification": "SAFE",
            },
            {
                "id": "TEST-004",
                "name": "Inference Test",
                "description": "Run inference with sample inputs",
                "commands": [
                    "python miner/test_inference.py --samples 10",
                ],
                "expected": "All sample inferences complete successfully",
                "classification": "SAFE",
            },
            {
                "id": "TEST-005",
                "name": "Axon Communication Test",
                "description": "Test local axon server (without network)",
                "commands": [
                    "python miner/test_axon.py --local-only",
                ],
                "expected": "Axon starts and responds to local requests",
                "classification": "SAFE",
            },
            {
                "id": "TEST-006",
                "name": "Integration Test",
                "description": "End-to-end test with mock validator",
                "commands": [
                    "python miner/test_integration.py --mock-validator",
                ],
                "expected": "Full pipeline executes without errors",
                "classification": "SAFE",
            },
        ]

        return {
            "status": "test_plan_created",
            "subnet_netuid": netuid,
            "tests": tests,
            "test_count": len(tests),
            "estimated_duration_minutes": len(tests * 5),
            "timestamp": time.time(),
        }

    def _create_benchmark_plan(self, params: dict) -> dict:
        """
        Create a benchmark plan for miner performance.

        Args:
            params: Benchmark parameters

        Returns:
            Benchmark plan dictionary
        """
        subnet = params.get("subnet", {})
        netuid = subnet.get("netuid", params.get("netuid", 0))

        benchmarks: list[dict] = [
            {
                "id": "BENCH-001",
                "name": "Inference Latency",
                "description": "Measure response time for single requests",
                "metric": "latency_ms",
                "target": "< 500ms",
                "classification": "SAFE",
            },
            {
                "id": "BENCH-002",
                "name": "Throughput",
                "description": "Requests per second under load",
                "metric": "requests_per_second",
                "target": "> 10 req/s",
                "classification": "SAFE",
            },
            {
                "id": "BENCH-003",
                "name": "Memory Usage",
                "description": "GPU and RAM usage during operation",
                "metric": "peak_vram_gb",
                "target": "< available VRAM",
                "classification": "SAFE",
            },
            {
                "id": "BENCH-004",
                "name": "Model Quality",
                "description": "Output quality score from evaluation",
                "metric": "quality_score",
                "target": "> 0.7",
                "classification": "SAFE",
            },
        ]

        return {
            "status": "benchmark_plan_created",
            "subnet_netuid": netuid,
            "benchmarks": benchmarks,
            "benchmark_count": len(benchmarks),
            "scripts": [
                "# Run all benchmarks",
                "python benchmark/run_all.py",
                "# Run single benchmark",
                "python benchmark/latency.py",
            ],
            "timestamp": time.time(),
        }

    def _detect_framework(self, category: str) -> dict:
        """Detect the ML framework needed for a category."""
        framework_map: dict[str, dict] = {
            "nlp": {"primary": "PyTorch", "secondary": "Transformers", "libs": ["torch", "transformers"]},
            "vision": {"primary": "PyTorch", "secondary": "Diffusers/TorchVision", "libs": ["torch", "torchvision", "diffusers"]},
            "audio": {"primary": "PyTorch", "secondary": "Tortoise/TTS", "libs": ["torch", "TTS"]},
            "multimodal": {"primary": "PyTorch", "secondary": "CLIP/BLIP", "libs": ["torch", "transformers"]},
            "inference": {"primary": "PyTorch", "secondary": "vLLM/TGI", "libs": ["torch", "vllm"]},
            "data": {"primary": "Python", "secondary": "Scrapy/Requests", "libs": ["requests", "scrapy"]},
            "compute": {"primary": "Python", "secondary": "Ray/Dask", "libs": ["ray"]},
            "infrastructure": {"primary": "Python", "secondary": "IPFS", "libs": ["ipfshttpclient"]},
            "governance": {"primary": "Python", "secondary": "Bittensor", "libs": ["bittensor"]},
            "search": {"primary": "Python", "secondary": "Elasticsearch", "libs": ["elasticsearch"]},
            "reasoning": {"primary": "PyTorch", "secondary": "Transformers", "libs": ["torch", "transformers"]},
        }
        return framework_map.get(category, {"primary": "Unknown", "secondary": "Bittensor", "libs": ["bittensor"]})

    def _hardware_profile_from_context(self) -> dict:
        """
        Pull a hardware profile from the shared agent context.

        Looks up the most recent ``system_check_agent.hardware_report`` and
        adapts it to the field names this agent expects (``ram_gb``,
        ``has_gpu``, ``vram_gb``, ``cpu_cores``). Returns ``{}`` when
        context isn't available or no report has been published — the
        caller falls back to its existing ``status="unknown"`` path.
        """
        ctx = getattr(self, "context", None)
        if ctx is None or not hasattr(ctx, "get"):
            return {}
        report = ctx.get("system_check_agent.hardware_report")
        if not isinstance(report, dict):
            return {}

        ram = report.get("ram") or {}
        gpu = report.get("gpu") or {}
        cpu = report.get("cpu") or {}
        return {
            "ram_gb": ram.get("total_gb", 0),
            "has_gpu": bool(gpu.get("available", False)),
            "vram_gb": gpu.get("vram_gb", 0),
            "cpu_cores": cpu.get("cores", 0),
            "_source": "system_check_agent.hardware_report",
        }

    def _check_hardware_compatibility(self, hw_min: dict) -> dict:
        """Check if available hardware meets minimum requirements."""
        if not self._hardware_profile:
            self._hardware_profile = self._hardware_profile_from_context()
        if not self._hardware_profile:
            return {
                "status": "unknown",
                "checks": [],
                "ready": False,
                "reason": (
                    "No hardware profile configured and no system_check_agent "
                    "report in context. Run system_check first or pass "
                    "hardware_profile in config."
                ),
            }

        checks: list[dict] = []
        ready = True

        # Check RAM
        if "ram_gb" in hw_min:
            avail_ram = self._hardware_profile.get("ram_gb", 0)
            req_ram = hw_min["ram_gb"]
            ram_ok = avail_ram >= req_ram
            checks.append({
                "component": "RAM",
                "available": f"{avail_ram}GB",
                "required": f"{req_ram}GB",
                "status": "PASS" if ram_ok else "FAIL",
            })
            if not ram_ok:
                ready = False

        # Check GPU
        if hw_min.get("gpu") == "required":
            has_gpu = self._hardware_profile.get("has_gpu", False)
            checks.append({
                "component": "GPU",
                "available": "Yes" if has_gpu else "No",
                "required": "Yes",
                "status": "PASS" if has_gpu else "FAIL",
            })
            if not has_gpu:
                ready = False

            # VRAM
            if "vram_gb" in hw_min:
                avail_vram = self._hardware_profile.get("vram_gb", 0)
                req_vram = hw_min["vram_gb"]
                vram_ok = avail_vram >= req_vram
                checks.append({
                    "component": "VRAM",
                    "available": f"{avail_vram}GB",
                    "required": f"{req_vram}GB",
                    "status": "PASS" if vram_ok else "FAIL",
                })
                if not vram_ok:
                    ready = False

        # CPU cores
        if "cpu_cores" in hw_min:
            avail_cores = self._hardware_profile.get("cpu_cores", 0)
            req_cores = hw_min["cpu_cores"]
            cpu_ok = avail_cores >= req_cores
            checks.append({
                "component": "CPU",
                "available": f"{avail_cores} cores",
                "required": f"{req_cores} cores",
                "status": "PASS" if cpu_ok else "FAIL",
            })
            if not cpu_ok:
                ready = False

        return {"status": "ready" if ready else "insufficient", "checks": checks, "ready": ready}

    def _estimate_complexity(self, subnet: dict, framework: dict) -> dict:
        """Estimate setup complexity."""
        score = 50  # Base
        reasons: list[str] = []

        if subnet.get("repo_url"):
            score -= 10
            reasons.append("Has repository")
        else:
            score += 10
            reasons.append("No repository - must find code")

        if subnet.get("docs_url"):
            score -= 10
            reasons.append("Has documentation")
        else:
            score += 10
            reasons.append("No documentation")

        hw = subnet.get("hardware_min", {})
        if hw.get("gpu") == "required" and hw.get("vram_gb", 0) > 16:
            score += 15
            reasons.append(f"High VRAM requirement ({hw['vram_gb']}GB)")

        if framework["primary"] == "PyTorch":
            score -= 5
            reasons.append("PyTorch framework (well-supported)")

        score = max(0, min(100, score))

        if score < 30:
            level = "easy"
        elif score < 60:
            level = "moderate"
        else:
            level = "complex"

        return {"score": score, "level": level, "reasons": reasons}

    def _get_recommendations(self, subnet: dict, framework: dict, hw_check: dict) -> list[str]:
        """Get setup recommendations."""
        recs: list[str] = []

        if not hw_check.get("ready", False):
            recs.append("UPGRADE HARDWARE: Current setup does not meet minimum requirements")

        if not subnet.get("repo_url"):
            recs.append("FIND REPO: Search GitHub for official miner implementation")

        if self._use_docker:
            recs.append("USE DOCKER: Containerized setup recommended for reproducibility")

        if framework["primary"] == "PyTorch":
            recs.append("INSTALL CUDA: Ensure CUDA toolkit matches PyTorch version")

        recs.append("START LOCAL: Test miner locally before mainnet registration")
        recs.append("READ DOCS: Review subnet-specific documentation thoroughly")

        return recs

    def _estimate_setup_time(self, subnet: dict) -> float:
        """Estimate setup time in hours."""
        base = 2

        if not subnet.get("repo_url"):
            base += 2
        if not subnet.get("docs_url"):
            base += 1

        hw = subnet.get("hardware_min", {})
        if hw.get("gpu") == "required":
            base += 1
        if hw.get("ram_gb", 16) > 32:
            base += 0.5

        return round(base, 1)
