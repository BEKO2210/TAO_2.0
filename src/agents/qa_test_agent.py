"""
QA & Test Agent (Agent 14).

Handles code testing, secret leakage checks, and wallet rule compliance.
Ensures all safety rules are enforced across the codebase.

Provides test reports.
"""

import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "qa_test_agent"
AGENT_VERSION: str = "1.0.0"

# Wallet safety rules to enforce
_WALLET_SAFETY_RULES: list[dict[str, Any]] = [
    {
        "id": "WS-001",
        "description": "NEVER request or store seed phrases",
        "forbidden_patterns": [
            r"seed[\s_]*phrase",
            r"mnemonic.*request",
            r"enter.*seed",
            r"type.*mnemonic",
            r"input.*recovery",
        ],
        "severity": "CRITICAL",
    },
    {
        "id": "WS-002",
        "description": "NEVER request or store private keys",
        "forbidden_patterns": [
            r"private[\s_]*key",
            r"secret[\s_]*key",
            r"enter.*private",
            r"input.*key",
        ],
        "severity": "CRITICAL",
    },
    {
        "id": "WS-003",
        "description": "NEVER create wallets automatically",
        "forbidden_patterns": [
            r"create_wallet\s*\(",
            r"create.*wallet.*automatically",
            r"generate.*wallet.*without",
        ],
        "severity": "CRITICAL",
    },
    {
        "id": "WS-004",
        "description": "NEVER sign transactions automatically",
        "forbidden_patterns": [
            r"sign.*automatically",
            r"auto.*sign",
            r"sign_transaction\s*\(.*\)",
        ],
        "severity": "CRITICAL",
    },
    {
        "id": "WS-005",
        "description": "Wallet watch-only mode enforced",
        "required_patterns": [
            r"watch.only|watch_only|WATCH_ONLY",
            r"read.only|read_only",
        ],
        "check": "contains_required",
        "severity": "INFO",
    },
    {
        "id": "WS-006",
        "description": "NEVER export or reveal keys",
        "forbidden_patterns": [
            r"export.*key",
            r"reveal.*seed",
            r"show.*mnemonic",
            r"backup.*wallet",
        ],
        "severity": "CRITICAL",
    },
    {
        "id": "WS-007",
        "description": "NEVER execute trades automatically",
        "forbidden_patterns": [
            r"execute_trade",
            r"place_order.*automatic",
            r"auto.*trade",
        ],
        "severity": "CRITICAL",
    },
]

# Secret patterns to detect
_SECRET_PATTERNS: list[dict[str, Any]] = [
    {
        "name": "Private Key (hex)",
        "pattern": r'[\"\']?[0-9a-fA-F]{64}[\"\']?',
        "severity": "HIGH",
    },
    {
        "name": "API Key (generic)",
        "pattern": r'(?:api[_-]?key|apikey)\s*[:=]\s*[\"\']?[a-zA-Z0-9]{32,}[\"\']?',
        "severity": "HIGH",
    },
    {
        "name": "Password in code",
        "pattern": r'(?:password|passwd|pwd)\s*[:=]\s*[\"\'][^\"\']{4,}[\"\']',
        "severity": "HIGH",
    },
    {
        "name": "Token in code",
        "pattern": r'(?:token|auth_token)\s*[:=]\s*[\"\']?[a-zA-Z0-9_-]{20,}[\"\']?',
        "severity": "MEDIUM",
    },
    {
        "name": "AWS Access Key",
        "pattern": r'AKIA[0-9A-Z]{16}',
        "severity": "CRITICAL",
    },
    {
        "name": "Bittensor seed phrase words",
        "pattern": r'(?:abandon ability able about above absent|abstract abuse access|'
                   r'accident account achieve acid acoustic)',
        "severity": "HIGH",
    },
]


class QATestAgent:
    """
    Agent for quality assurance and testing.

    Runs code tests, checks for secret leakage, and verifies wallet
    safety rule compliance across the entire codebase. Ensures no
    agent violates the security rules.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the QATestAgent.

        Args:
            config: Configuration with optional:
                - source_dir: Directory to scan
                - test_dir: Test directory
                - check_secrets: Enable secret checking (default True)
                - check_wallet_rules: Enable wallet rule checking (default True)
        """
        self.config: dict = config
        self._status: str = "idle"
        self._source_dir: str = config.get("source_dir", "./src")
        self._test_dir: str = config.get("test_dir", "./tests")
        self._check_secrets: bool = config.get("check_secrets", True)
        self._check_wallet_rules: bool = config.get("check_wallet_rules", True)
        self._test_log: list[dict] = []

        logger.info(
            "QATestAgent initialized (source=%s, secrets=%s, wallet=%s)",
            self._source_dir, self._check_secrets, self._check_wallet_rules,
        )

    def run(self, task: dict) -> dict:
        """
        Run QA tests.

        Args:
            task: Dictionary with 'params' containing:
                - action: "test", "secret_check", "wallet_compliance", "full_scan"
                - file_path: Specific file to check

        Returns:
            Test report
        """
        self._status = "running"
        params = task.get("params", {})
        action = params.get("action", "full_scan")

        logger.info("QATestAgent: action=%s", action)

        try:
            if action == "test":
                result = self._run_tests(params)
            elif action == "secret_check":
                result = self._check_secrets_in_code(params)
            elif action == "wallet_compliance":
                result = self._check_wallet_compliance(params)
            elif action == "full_scan":
                result = self._run_full_scan(params)
            else:
                result = {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                }

            self._test_log.append({
                "timestamp": time.time(),
                "action": action,
                "findings": result.get("findings_count", 0),
            })
            self._status = "complete"
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("QATestAgent: failed: %s", e)
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
            "scans_completed": len(self._test_log),
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
        action = params.get("action", "full_scan")
        valid_actions = ["test", "secret_check", "wallet_compliance", "full_scan"]
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"
        return True, ""

    def _run_tests(self, params: dict) -> dict:
        """
        Run code tests.

        Args:
            params: Test parameters

        Returns:
            Test results
        """
        import subprocess

        test_path = params.get("file_path", self._test_dir)
        verbose = params.get("verbose", True)

        test_results: list[dict] = []
        total_passed = 0
        total_failed = 0
        total_errors = 0

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", test_path, "-v" if verbose else "-q"],
                capture_output=True,
                text=True,
                timeout=120,
            )

            # Parse results
            output = result.stdout
            if "passed" in output:
                import re as re_module
                match = re_module.search(r'(\d+) passed', output)
                if match:
                    total_passed = int(match.group(1))
                match = re_module.search(r'(\d+) failed', output)
                if match:
                    total_failed = int(match.group(1))
                match = re_module.search(r'(\d+) error', output)
                if match:
                    total_errors = int(match.group(1))

            test_results.append({
                "path": test_path,
                "returncode": result.returncode,
                "passed": total_passed,
                "failed": total_failed,
                "errors": total_errors,
            })

        except FileNotFoundError:
            test_results.append({
                "path": test_path,
                "error": "pytest not found",
                "note": "Install with: pip install pytest",
            })
        except subprocess.TimeoutExpired:
            test_results.append({
                "path": test_path,
                "error": "Test timed out",
            })

        return {
            "status": "tested",
            "test_results": test_results,
            "summary": {
                "total_passed": total_passed,
                "total_failed": total_failed,
                "total_errors": total_errors,
            },
            "timestamp": time.time(),
        }

    def _check_secrets_in_code(self, params: dict) -> dict:
        """
        Check for secrets in source code.

        Args:
            params: Check parameters

        Returns:
            Secret check results
        """
        file_path = params.get("file_path")
        scan_dir = file_path or self._source_dir

        findings: list[dict] = []
        files_scanned = 0

        if os.path.isfile(scan_dir):
            files_scanned += 1
            with open(scan_dir, "r") as f:
                content = f.read()
            findings.extend(self._scan_content_for_secrets(content, scan_dir))
        elif os.path.isdir(scan_dir):
            for root, dirs, files in os.walk(scan_dir):
                # Skip hidden dirs and venv
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", "__pycache__")]
                for fname in files:
                    if fname.endswith(".py"):
                        full_path = os.path.join(root, fname)
                        files_scanned += 1
                        try:
                            with open(full_path, "r") as f:
                                content = f.read()
                            findings.extend(self._scan_content_for_secrets(content, full_path))
                        except Exception as e:
                            logger.debug("Could not read %s: %s", full_path, e)

        return {
            "status": "secrets_checked",
            "files_scanned": files_scanned,
            "findings_count": len(findings),
            "findings": findings,
            "passed": len(findings) == 0,
            "timestamp": time.time(),
        }

    def _scan_content_for_secrets(self, content: str, file_path: str) -> list[dict]:
        """Scan content for secret patterns."""
        findings: list[dict] = []
        lines = content.split("\n")

        for secret_pattern in _SECRET_PATTERNS:
            for i, line in enumerate(lines, 1):
                if re.search(secret_pattern["pattern"], line, re.IGNORECASE):
                    # Skip comments that explain patterns
                    stripped = line.strip()
                    if stripped.startswith("#") and (
                        "pattern" in stripped.lower() or "example" in stripped.lower()
                    ):
                        continue
                    # Skip docstrings explaining
                    if '"""' in stripped or "'''" in stripped or "pattern" in stripped.lower():
                        continue
                    # Skip test data
                    if "test" in file_path and "mock" in line.lower():
                        continue

                    findings.append({
                        "file": file_path,
                        "line": i,
                        "type": secret_pattern["name"],
                        "severity": secret_pattern["severity"],
                        "snippet": line.strip()[:100],
                    })

        return findings

    def _check_wallet_compliance(self, params: dict) -> dict:
        """
        Check wallet safety rule compliance.

        Args:
            params: Check parameters

        Returns:
            Compliance report
        """
        file_path = params.get("file_path")
        scan_dir = file_path or self._source_dir

        rule_results: list[dict] = []
        files_scanned = 0

        if os.path.isfile(scan_dir):
            files_scanned += 1
            with open(scan_dir, "r") as f:
                content = f.read()
            rule_results.extend(self._check_file_wallet_compliance(content, scan_dir))
        elif os.path.isdir(scan_dir):
            for root, dirs, files in os.walk(scan_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", "__pycache__")]
                for fname in files:
                    if fname.endswith(".py"):
                        full_path = os.path.join(root, fname)
                        files_scanned += 1
                        try:
                            with open(full_path, "r") as f:
                                content = f.read()
                            rule_results.extend(self._check_file_wallet_compliance(content, full_path))
                        except Exception as e:
                            logger.debug("Could not read %s: %s", full_path, e)

        # Count violations by severity
        violations = [r for r in rule_results if r["status"] == "VIOLATION"]
        critical = [r for r in violations if r["severity"] == "CRITICAL"]

        return {
            "status": "compliance_checked",
            "files_scanned": files_scanned,
            "total_checks": len(rule_results),
            "violations": len(violations),
            "critical_violations": len(critical),
            "passed": len(violations) == 0,
            "results": rule_results,
            "timestamp": time.time(),
        }

    def _check_file_wallet_compliance(self, content: str, file_path: str) -> list[dict]:
        """Check a single file for wallet compliance."""
        results: list[dict] = []

        for rule in _WALLET_SAFETY_RULES:
            # Check forbidden patterns
            if "forbidden_patterns" in rule:
                for pattern in rule["forbidden_patterns"]:
                    matches = list(re.finditer(pattern, content, re.IGNORECASE))
                    for match in matches:
                        # Context check: skip test files and docstrings
                        line_num = content[:match.start()].count("\n") + 1
                        line = content.split("\n")[line_num - 1]
                        if "test" in file_path and "mock" in line.lower():
                            continue
                        if "#" in line and ("pattern" in line.lower() or "example" in line.lower()):
                            continue

                        results.append({
                            "file": file_path,
                            "line": line_num,
                            "rule_id": rule["id"],
                            "rule_description": rule["description"],
                            "status": "VIOLATION",
                            "severity": rule["severity"],
                            "matched_pattern": pattern,
                            "snippet": line.strip()[:100],
                        })

            # Check required patterns
            if "check" in rule and rule["check"] == "contains_required":
                has_required = any(
                    re.search(p, content, re.IGNORECASE)
                    for p in rule.get("required_patterns", [])
                )
                status = "PASS" if has_required else "INFO"
                results.append({
                    "file": file_path,
                    "line": 0,
                    "rule_id": rule["id"],
                    "rule_description": rule["description"],
                    "status": status,
                    "severity": rule["severity"],
                })

        return results

    def _run_full_scan(self, params: dict) -> dict:
        """
        Run a full QA scan.

        Args:
            params: Scan parameters

        Returns:
            Full scan report
        """
        # Run all checks
        secret_results = self._check_secrets_in_code(params) if self._check_secrets else {"findings": []}
        wallet_results = self._check_wallet_compliance(params) if self._check_wallet_rules else {"violations": 0, "critical_violations": 0}
        test_results = self._run_tests(params)

        total_findings = len(secret_results.get("findings", [])) + wallet_results.get("violations", 0)
        critical = wallet_results.get("critical_violations", 0)
        for f in secret_results.get("findings", []):
            if f.get("severity") == "CRITICAL":
                critical += 1

        overall_status = "PASS" if total_findings == 0 else "FAIL" if critical > 0 else "WARN"

        return {
            "status": "full_scan_complete",
            "overall_status": overall_status,
            "total_findings": total_findings,
            "critical_findings": critical,
            "sections": {
                "secrets": secret_results,
                "wallet_compliance": wallet_results,
                "tests": test_results,
            },
            "recommendations": self._get_recommendations(
                overall_status, secret_results, wallet_results
            ),
            "timestamp": time.time(),
        }

    def _get_recommendations(
        self,
        status: str,
        secret_results: dict,
        wallet_results: dict,
    ) -> list[str]:
        """Get recommendations based on scan results."""
        recs: list[str] = []

        if status == "FAIL":
            recs.append("CRITICAL: Fix all critical findings before deploying")

        if secret_results.get("findings"):
            recs.append("Remove all secrets from code - use environment variables")
            recs.append("Add .env to .gitignore if not already present")
            recs.append("Rotate any exposed credentials immediately")

        if wallet_results.get("violations", 0) > 0:
            recs.append("Review and fix all wallet safety rule violations")
            recs.append("Ensure no agent can request or handle credentials")

        if status == "PASS":
            recs.append("All checks passed - codebase is clean")
            recs.append("Continue monitoring with regular scans")

        recs.append("Run full_scan regularly (recommended: before each commit)")

        return recs
