"""
Validator Engineering Agent (Agent 9).

Analyzes validator feasibility for subnets, reviews evaluation logic,
checks stake requirements, and performs code review of validator
implementations.

Provides validator feasibility reports.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "validator_engineering_agent"
AGENT_VERSION: str = "1.0.0"


class ValidatorEngineeringAgent:
    """
    Agent for validator feasibility analysis and engineering.

    Analyzes whether a subnet is suitable for validation, reviews
evaluation logic, checks stake requirements, and performs code
    review of validator implementations.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the ValidatorEngineeringAgent.

        Args:
            config: Configuration with optional:
                - available_stake: TAO available for staking
                - hardware_profile: Available hardware description
                - target_subnets: List of subnets to evaluate
        """
        self.config: dict = config
        self._status: str = "idle"
        self._available_stake: float = config.get("available_stake", 0.0)
        self._hardware_profile: dict = config.get("hardware_profile", {})
        self._target_subnets: list = config.get("target_subnets", [])
        self._analysis_log: list[dict] = []

        logger.info(
            "ValidatorEngineeringAgent initialized (stake=%.2f TAO)",
            self._available_stake,
        )

    def run(self, task: dict) -> dict:
        """
        Run validator feasibility analysis.

        Args:
            task: Dictionary with 'params' containing:
                - action: "feasibility", "stake_check", "code_review"
                - subnet: Target subnet dict or netuid
                - code_content: Code to review

        Returns:
            Validator feasibility report
        """
        self._status = "running"
        params = task.get("params", {})
        action = params.get("action", "feasibility")

        logger.info("ValidatorEngineeringAgent: action=%s", action)

        try:
            if action == "feasibility":
                result = self._analyze_feasibility(params)
            elif action == "stake_check":
                result = self._check_stake_requirements(params)
            elif action == "code_review":
                result = self._review_validator_code(params)
            else:
                result = {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                }

            self._analysis_log.append({
                "timestamp": time.time(),
                "action": action,
            })
            self._status = "complete"
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("ValidatorEngineeringAgent: failed: %s", e)
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
            "analyses": len(self._analysis_log),
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
        action = params.get("action", "feasibility")
        valid_actions = ["feasibility", "stake_check", "code_review"]
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"
        return True, ""

    def _analyze_feasibility(self, params: dict) -> dict:
        """
        Analyze validator feasibility for a subnet.

        Args:
            params: Parameters with 'subnet'

        Returns:
            Feasibility report
        """
        subnet = params.get("subnet", {})
        netuid = subnet.get("netuid", params.get("netuid", 0))
        name = subnet.get("name", f"Subnet-{netuid}")
        category = subnet.get("category", "unknown")

        # Check hardware readiness
        hw_ready = self._check_validator_hardware()

        # Check stake sufficiency
        stake_check = self._check_stake_sufficiency(netuid)

        # Check uptime capability
        uptime_ready = self._check_uptime_capability()

        # Evaluate complexity
        complexity = self._evaluate_complexity(category)

        # Calculate overall feasibility score
        score = 0
        factors: list[dict] = []

        if hw_ready["ready"]:
            score += 30
            factors.append({"factor": "hardware", "score": 30, "status": "pass"})
        else:
            factors.append({"factor": "hardware", "score": 0, "status": "fail", "issues": hw_ready["issues"]})

        if stake_check["sufficient"]:
            score += 35
            factors.append({"factor": "stake", "score": 35, "status": "pass"})
        else:
            factors.append({
                "factor": "stake", "score": stake_check.get("partial_score", 0),
                "status": "insufficient",
                "required": stake_check.get("required", 0),
                "available": self._available_stake,
            })

        if uptime_ready:
            score += 20
            factors.append({"factor": "uptime", "score": 20, "status": "pass"})
        else:
            factors.append({"factor": "uptime", "score": 5, "status": "warning"})

        if complexity != "high":
            score += 15
            factors.append({"factor": "complexity", "score": 15, "status": "pass"})
        else:
            factors.append({"factor": "complexity", "score": 5, "status": "warning"})

        # Verdict
        if score >= 80:
            verdict = "RECOMMENDED"
        elif score >= 50:
            verdict = "POSSIBLE"
        elif score >= 30:
            verdict = "CHALLENGING"
        else:
            verdict = "NOT_FEASIBLE"

        return {
            "status": "analyzed",
            "subnet": {"netuid": netuid, "name": name, "category": category},
            "feasibility_score": score,
            "verdict": verdict,
            "factors": factors,
            "hardware_check": hw_ready,
            "stake_check": stake_check,
            "uptime_check": uptime_ready,
            "complexity": complexity,
            "recommendations": self._get_validator_recommendations(
                verdict, hw_ready, stake_check, category
            ),
            "timestamp": time.time(),
        }

    def _check_stake_requirements(self, params: dict) -> dict:
        """
        Check stake requirements for a subnet.

        Args:
            params: Parameters with 'netuid'

        Returns:
            Stake requirement report
        """
        netuid = params.get("netuid", 0)
        subnet = params.get("subnet", {})
        category = subnet.get("category", "") if isinstance(subnet, dict) else ""

        # Estimated stake requirements by subnet type
        # Root subnet requires massive stake
        if netuid == 0:
            required = 10000.0
        elif category in ["inference", "nlp", "vision"]:
            required = 1000.0
        elif category in ["audio", "multimodal", "data"]:
            required = 500.0
        else:
            required = 100.0

        sufficient = self._available_stake >= required
        ratio = self._available_stake / required if required > 0 else 0

        return {
            "netuid": netuid,
            "required_tao": required,
            "available_tao": self._available_stake,
            "sufficient": sufficient,
            "ratio": round(ratio, 2),
            "partial_score": round(min(ratio * 35, 35), 1),
            "to_next_validator_set": max(0, required - self._available_stake),
        }

    def _review_validator_code(self, params: dict) -> dict:
        """
        Review validator code for issues.

        Args:
            params: Parameters with 'code_content'

        Returns:
            Code review report
        """
        code_content = params.get("code_content", "")
        issues: list[dict] = []

        # Check for common issues
        if "sleep(" in code_content and "timeout" not in code_content.lower():
            issues.append({
                "severity": "LOW",
                "line": "unknown",
                "issue": "Sleep without timeout may cause blocking",
                "recommendation": "Add timeout parameters to all blocking calls",
            })

        if "try:" in code_content and "except:" in code_content:
            # Check for bare except
            lines = code_content.split("\n")
            for i, line in enumerate(lines):
                if line.strip() == "except:":
                    issues.append({
                        "severity": "MEDIUM",
                        "line": i + 1,
                        "issue": "Bare 'except:' clause catches all exceptions",
                        "recommendation": "Use 'except Exception as e:' and log the error",
                    })

        if "print(" in code_content and "logging" not in code_content:
            issues.append({
                "severity": "LOW",
                "line": "unknown",
                "issue": "Using print() instead of logging",
                "recommendation": "Replace print() with logging for production code",
            })

        # Check for weight setting logic
        if "set_weights" in code_content:
            issues.append({
                "severity": "INFO",
                "line": "unknown",
                "issue": "Weight-setting logic detected",
                "recommendation": "Ensure weights are normalized and validated before setting",
            })

        # Check for API keys in code
        import re
        if re.search(r'[a-zA-Z0-9]{32,}', code_content):
            api_lines = []
            lines = code_content.split("\n")
            for i, line in enumerate(lines):
                if re.search(r'[a-zA-Z0-9]{32,}', line) and (
                    "api" in line.lower() or "key" in line.lower() or "token" in line.lower()
                ):
                    api_lines.append(i + 1)

            if api_lines:
                issues.append({
                    "severity": "HIGH",
                    "line": api_lines[0],
                    "issue": "Potential API key/token in source code",
                    "recommendation": "Move API keys to environment variables",
                })

        # Rate the code
        severity_scores = {"INFO": 0, "LOW": 1, "MEDIUM": 3, "HIGH": 5}
        total_score = sum(severity_scores.get(i["severity"], 0) for i in issues)

        if total_score == 0:
            rating = "EXCELLENT"
        elif total_score <= 2:
            rating = "GOOD"
        elif total_score <= 5:
            rating = "FAIR"
        else:
            rating = "NEEDS_WORK"

        return {
            "status": "reviewed",
            "issues_found": len(issues),
            "issues": issues,
            "code_rating": rating,
            "score": total_score,
            "timestamp": time.time(),
        }

    def _check_validator_hardware(self) -> dict:
        """Check if hardware is suitable for validation."""
        if not self._hardware_profile:
            return {"ready": False, "issues": ["No hardware profile available"]}

        issues: list[str] = []
        ram = self._hardware_profile.get("ram_gb", 0)
        has_gpu = self._hardware_profile.get("has_gpu", False)
        vram = self._hardware_profile.get("vram_gb", 0)
        cores = self._hardware_profile.get("cpu_cores", 0)

        if ram < 32:
            issues.append(f"RAM insufficient: {ram}GB < 32GB recommended for validation")
        if not has_gpu:
            issues.append("GPU required for most validation tasks")
        elif vram < 16:
            issues.append(f"VRAM may be insufficient: {vram}GB < 16GB recommended")
        if cores < 8:
            issues.append(f"CPU cores: {cores} < 8 recommended")

        return {
            "ready": len(issues) == 0,
            "issues": issues,
            "specs": {
                "ram_gb": ram,
                "has_gpu": has_gpu,
                "vram_gb": vram,
                "cpu_cores": cores,
            },
        }

    def _check_stake_sufficiency(self, netuid: int) -> dict:
        """Check if available stake is sufficient."""
        return self._check_stake_requirements({"netuid": netuid})

    def _check_uptime_capability(self) -> bool:
        """Check if 24/7 uptime is possible."""
        # Check if running in a persistent environment
        # This is a heuristic - user must confirm
        return True  # Assume yes, flag in recommendations

    def _evaluate_complexity(self, category: str) -> str:
        """Evaluate validation complexity for a category."""
        high = ["multimodal", "inference", "reasoning"]
        medium = ["nlp", "vision", "audio", "data", "compute"]

        if category in high:
            return "high"
        elif category in medium:
            return "medium"
        return "low"

    def _get_validator_recommendations(
        self, verdict: str, hw: dict, stake: dict, category: str
    ) -> list[str]:
        """Get recommendations based on feasibility."""
        recs: list[str] = []

        if verdict == "RECOMMENDED":
            recs.append("Your setup is well-suited for validation on this subnet")
        elif verdict == "POSSIBLE":
            recs.append("Validation is possible but may have challenges")
        elif verdict == "CHALLENGING":
            recs.append("Validation will be challenging - consider upgrading first")
        else:
            recs.append("Validation not currently feasible - address issues first")

        if not hw.get("ready", False):
            for issue in hw.get("issues", []):
                recs.append(f"HARDWARE: {issue}")

        if not stake.get("sufficient", False):
            req = stake.get("required_tao", 0)
            avail = stake.get("available_tao", 0)
            recs.append(f"STAKE: Need {req:.0f} TAO, have {avail:.0f} TAO")
            recs.append("STAKE: Consider delegation from others")

        recs.append("UPTIME: Ensure 24/7 server availability")
        recs.append("NETWORK: Use reliable internet with low latency")
        recs.append("MONITORING: Set up alerts for validator health")
        recs.append("BACKUP: Have a backup server ready")

        return recs
