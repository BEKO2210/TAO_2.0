"""
Risk & Security Agent (Agent 7).

Comprehensive risk and security review agent. Checks for scam indicators,
dangerous repositories, wallet/key risks, and phishing threats.

Has VETO power: STOP verdict stops the entire system.
Returns: proceed / pause / reject / STOP
"""

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "risk_security_agent"
AGENT_VERSION: str = "1.0.0"

# Known scam indicators
_SCAM_INDICATORS: list[str] = [
    "guaranteed returns",
    "risk free",
    "no risk",
    "100% profit",
    "double your tao",
    "send tao to receive",
    "private key needed",
    "seed phrase required",
    "connect wallet to verify",
    "urgent action required",
    "limited time",
    "exclusive opportunity",
    "act now",
    "guaranteed stake rewards",
]

# Known suspicious patterns in repos
_SUSPICIOUS_PATTERNS: list[str] = [
    "hardcoded private key",
    "send_funds",
    "withdraw_all",
    "steal_",
    "keylogger",
    "exfiltrate",
    "backdoor",
    "reverse_shell",
    "eval(input",
    "exec(input",
    "__import__('os').system",
    "subprocess.call",
]

# Trusted domains
_TRUSTED_DOMAINS: set[str] = {
    "github.com", "docs.bittensor.com", "bittensor.com",
    "opentensor.ai", "huggingface.co", "pypi.org",
}

# Known phishing domains (example patterns)
_KNOWN_PHISHING_PATTERNS: list[str] = [
    "bittensor-wallet",
    "tao-rewards",
    "bittensor-airdrop",
    "claim-tao",
]


class RiskSecurityAgent:
    """
    Risk and security review agent with VETO power.

    Reviews all operations for security risks including scam indicators,
    suspicious code patterns, wallet/key risks, and phishing threats.
    Can issue a STOP verdict that halts the entire system.

    Returns verdicts: PROCEED / PAUSE / REJECT / STOP
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the RiskSecurityAgent.

        Args:
            config: Configuration with optional:
                - strict_mode: Enable strict checking (default True)
                - auto_stop: Auto-stop on critical findings (default False)
                - whitelist: Additional trusted domains
        """
        self.config: dict = config
        self._status: str = "idle"
        self._strict_mode: bool = config.get("strict_mode", True)
        self._auto_stop: bool = config.get("auto_stop", False)
        self._whitelist: set[str] = set(config.get("whitelist", []))
        self._whitelist.update(_TRUSTED_DOMAINS)
        self._review_log: list[dict] = []

        logger.info(
            "RiskSecurityAgent initialized (strict=%s, auto_stop=%s)",
            self._strict_mode, self._auto_stop,
        )

    def run(self, task: dict) -> dict:
        """
        Run risk and security review.

        Args:
            task: Dictionary with 'params' containing:
                - target: What to review ("operation", "repo", "url", "general")
                - content: Content to analyze
                - operation_type: Type of operation being reviewed

        Returns:
            Risk review with verdict and findings
        """
        self._status = "running"
        params = task.get("params", {})
        target = params.get("target", "general")
        content = params.get("content", "")
        operation_type = params.get("operation_type", "")

        logger.info(
            "RiskSecurityAgent: reviewing target=%s, op=%s",
            target, operation_type,
        )

        try:
            if target == "operation":
                result = self._review_operation(params)
            elif target == "repo":
                result = self._review_repository(params)
            elif target == "url":
                result = self._review_url(params)
            elif target == "general":
                result = self._general_review(params)
            else:
                result = self._general_review(params)

            self._review_log.append({
                "timestamp": time.time(),
                "target": target,
                "verdict": result.get("verdict", "UNKNOWN"),
            })
            self._status = "complete"
            logger.info(
                "RiskSecurityAgent: verdict=%s", result.get("verdict")
            )
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("RiskSecurityAgent: review failed: %s", e)
            raise

    def get_status(self) -> dict:
        """
        Get current agent status.

        Returns:
            Status dictionary
        """
        recent_verdicts = [
            r["verdict"] for r in self._review_log[-10:]
        ]
        stop_count = recent_verdicts.count("STOP")

        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "status": self._status,
            "reviews_conducted": len(self._review_log),
            "strict_mode": self._strict_mode,
            "recent_stop_count": stop_count,
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
        return True, ""

    def _review_operation(self, params: dict) -> dict:
        """
        Review a planned operation for risks.

        Args:
            params: Operation parameters

        Returns:
            Risk review result
        """
        operation_type = params.get("operation_type", "")
        content = str(params.get("content", ""))
        data_reviewed = bool(operation_type) or bool(content)

        findings: list[dict] = []
        risk_score = 0

        # Check for scam indicators in operation description
        for indicator in _SCAM_INDICATORS:
            if indicator.lower() in content.lower():
                findings.append({
                    "severity": "CRITICAL",
                    "category": "scam_indicator",
                    "finding": f"Scam indicator detected: '{indicator}'",
                    "recommendation": "STOP - Do not proceed with this operation",
                })
                risk_score += 50

        # Check operation type risks
        high_risk_ops = [
            "wallet_creation", "sign_transaction", "stake",
            "unstake", "transfer", "delegate", "mainnet_register",
        ]
        if operation_type.lower() in high_risk_ops:
            findings.append({
                "severity": "HIGH",
                "category": "operation_type",
                "finding": f"High-risk operation: {operation_type}",
                "recommendation": "Requires explicit manual approval",
            })
            risk_score += 30

        # Check for key/seed exposure
        if self._contains_key_material(content):
            findings.append({
                "severity": "CRITICAL",
                "category": "key_exposure",
                "finding": "Potential key material detected in operation content",
                "recommendation": "STOP - Never include keys in operation parameters",
            })
            risk_score += 50

        # Check for wallet credential requests
        if any(kw in content.lower() for kw in [
            "password", "seed phrase", "mnemonic", "private key",
            "decrypt wallet", "unlock wallet",
        ]):
            findings.append({
                "severity": "CRITICAL",
                "category": "credential_request",
                "finding": "Operation requests wallet credentials",
                "recommendation": "STOP - No agent should request credentials",
            })
            risk_score += 50

        return self._compile_verdict(findings, risk_score, data_reviewed=data_reviewed)

    def _review_repository(self, params: dict) -> dict:
        """
        Review a code repository for security issues.

        Args:
            params: Repository parameters with 'repo_url' or 'code_content'

        Returns:
            Repository security review
        """
        repo_url = params.get("repo_url", "")
        code_content = params.get("code_content", "")
        data_reviewed = bool(repo_url) or bool(code_content)

        findings: list[dict] = []
        risk_score = 0

        # Check repo URL trustworthiness
        if repo_url:
            domain = self._extract_domain(repo_url)
            if domain and domain not in self._whitelist:
                findings.append({
                    "severity": "MEDIUM",
                    "category": "untrusted_source",
                    "finding": f"Repository from untrusted domain: {domain}",
                    "recommendation": "Verify repository authenticity before use",
                })
                risk_score += 15

        # Check code for suspicious patterns
        if code_content:
            for pattern in _SUSPICIOUS_PATTERNS:
                if pattern.lower() in code_content.lower():
                    findings.append({
                        "severity": "HIGH",
                        "category": "suspicious_code",
                        "finding": f"Suspicious pattern detected: '{pattern}'",
                        "recommendation": "Manual code review required",
                    })
                    risk_score += 25

        # Check for hardcoded values
        if code_content and re.search(r'0x[a-fA-F0-9]{64}', code_content):
            findings.append({
                "severity": "MEDIUM",
                "category": "hardcoded_value",
                "finding": "Potential hardcoded private key or hash detected",
                "recommendation": "Verify all hardcoded values are safe",
            })
            risk_score += 15

        # Check for network requests to unknown hosts
        if code_content:
            url_pattern = re.compile(r'https?://([^/\s"\']+)')
            urls = url_pattern.findall(code_content)
            for url in urls:
                if url not in self._whitelist and "localhost" not in url:
                    findings.append({
                        "severity": "LOW",
                        "category": "external_request",
                        "finding": f"External network request to: {url}",
                        "recommendation": "Verify destination is legitimate",
                    })
                    risk_score += 5

        return self._compile_verdict(
            findings, risk_score, repo_url, data_reviewed=data_reviewed,
        )

    def _review_url(self, params: dict) -> dict:
        """
        Review a URL for phishing/malicious indicators.

        Args:
            params: URL parameters with 'url'

        Returns:
            URL security review
        """
        url = params.get("url", "")
        data_reviewed = bool(url)
        findings: list[dict] = []
        risk_score = 0

        # Check for phishing patterns
        url_lower = url.lower()
        for pattern in _KNOWN_PHISHING_PATTERNS:
            if pattern in url_lower:
                findings.append({
                    "severity": "CRITICAL",
                    "category": "phishing",
                    "finding": f"Phishing pattern detected: '{pattern}'",
                    "recommendation": "STOP - Known phishing indicator",
                })
                risk_score += 50

        # Check domain trustworthiness
        domain = self._extract_domain(url)
        if domain:
            if domain in self._whitelist:
                findings.append({
                    "severity": "INFO",
                    "category": "trusted_domain",
                    "finding": f"Trusted domain: {domain}",
                    "recommendation": "No concerns",
                })
            else:
                findings.append({
                    "severity": "MEDIUM",
                    "category": "unverified_domain",
                    "finding": f"Domain not in whitelist: {domain}",
                    "recommendation": "Verify domain authenticity",
                })
                risk_score += 10

        # Check for typosquatting (e.g., bittenson vs bittensor)
        if "bittensor" in url_lower and domain:
            if "github.com" not in domain and "opentensor" not in domain:
                if "bittensor" in domain and domain not in self._whitelist:
                    findings.append({
                        "severity": "HIGH",
                        "category": "typosquatting",
                        "finding": f"Potential typosquatting: {domain}",
                        "recommendation": "Verify this is the official domain",
                    })
                    risk_score += 25

        # Check for HTTP (non-HTTPS)
        if url.startswith("http://") and not url.startswith("http://localhost"):
            findings.append({
                "severity": "MEDIUM",
                "category": "insecure_protocol",
                "finding": "URL uses HTTP (not HTTPS)",
                "recommendation": "Prefer HTTPS connections",
            })
            risk_score += 10

        return self._compile_verdict(
            findings, risk_score, url, data_reviewed=data_reviewed,
        )

    def _general_review(self, params: dict) -> dict:
        """
        Perform a general security review.

        Args:
            params: Review parameters

        Returns:
            General security review result
        """
        content = str(params.get("content", ""))
        operation_type = params.get("operation_type", "general")
        # "general" is the *default* op-type when nothing was specified, so
        # treat it as no signal. Any explicit value (including the special
        # cases below) counts as data.
        data_reviewed = bool(content) or operation_type != "general"

        findings: list[dict] = []
        risk_score = 0

        # Scan for all risk categories
        scam_findings, scam_score = self._scan_scam_indicators(content)
        findings.extend(scam_findings)
        risk_score += scam_score

        key_findings, key_score = self._scan_key_exposure(content)
        findings.extend(key_findings)
        risk_score += key_score

        cred_findings, cred_score = self._scan_credential_requests(content)
        findings.extend(cred_findings)
        risk_score += cred_score

        # Check wallet safety rules
        wallet_findings, wallet_score = self._check_wallet_safety(content)
        findings.extend(wallet_findings)
        risk_score += wallet_score

        # System configuration risks
        if operation_type in ["install_deps", "connect_api"]:
            findings.append({
                "severity": "LOW",
                "category": "caution_operation",
                "finding": f"CAUTION-level operation: {operation_type}",
                "recommendation": "Verify sources and permissions",
            })
            risk_score += 5

        return self._compile_verdict(findings, risk_score, data_reviewed=data_reviewed)

    def _scan_scam_indicators(self, content: str) -> tuple[list[dict], int]:
        """Scan content for scam indicators."""
        findings: list[dict] = []
        score = 0
        content_lower = content.lower()

        for indicator in _SCAM_INDICATORS:
            if indicator in content_lower:
                findings.append({
                    "severity": "CRITICAL",
                    "category": "scam_indicator",
                    "finding": f"Scam language: '{indicator}'",
                    "recommendation": "STOP - Scam indicator detected",
                })
                score += 50

        return findings, score

    def _scan_key_exposure(self, content: str) -> tuple[list[dict], int]:
        """Scan content for exposed key material."""
        findings: list[dict] = []
        score = 0

        # Check for private key patterns (64 hex chars)
        if re.search(r'[0-9a-fA-F]{64}', content):
            findings.append({
                "severity": "CRITICAL",
                "category": "key_exposure",
                "finding": "Potential private key (64 hex characters) detected",
                "recommendation": "STOP - Never expose private keys",
            })
            score += 50

        # Check for seed phrase patterns (12-24 words)
        words = content.split()
        if len(words) >= 12:
            # Check for bip39 word patterns (simplified)
            bip39_words = [
                "abandon", "ability", "able", "about", "above", "absent",
                "abstract", "abuse", "account", "achieve", "acid", "acoustic",
            ]
            found_bip = sum(1 for w in words if w.lower() in bip39_words)
            if found_bip >= 3:
                findings.append({
                    "severity": "CRITICAL",
                    "category": "key_exposure",
                    "finding": f"Potential seed phrase words detected ({found_bip} matches)",
                    "recommendation": "STOP - Never expose seed phrases",
                })
                score += 50

        return findings, score

    def _scan_credential_requests(self, content: str) -> tuple[list[dict], int]:
        """Scan content for credential requests."""
        findings: list[dict] = []
        score = 0
        content_lower = content.lower()

        cred_keywords = [
            "password", "seed phrase", "mnemonic", "private key",
            "decrypt wallet", "unlock wallet", "wallet password",
        ]

        for kw in cred_keywords:
            if kw in content_lower:
                findings.append({
                    "severity": "CRITICAL",
                    "category": "credential_request",
                    "finding": f"Credential request detected: '{kw}'",
                    "recommendation": "STOP - No agent should request credentials",
                })
                score += 50
                break  # One finding is enough for this category

        return findings, score

    def _check_wallet_safety(self, content: str) -> tuple[list[dict], int]:
        """Check for wallet safety rule violations."""
        findings: list[dict] = []
        score = 0
        content_lower = content.lower()

        # Rule: Never request seeds/private keys
        if any(kw in content_lower for kw in [
            "need your seed", "need your private", "send me your",
            "share your key", "provide your mnemonic",
        ]):
            findings.append({
                "severity": "CRITICAL",
                "category": "wallet_safety",
                "finding": "Agent requests sensitive wallet information",
                "recommendation": "STOP - Violates RULE-001: Never request seeds/keys",
            })
            score += 50

        return findings, score

    def _contains_key_material(self, content: str) -> bool:
        """Check if content contains potential key material."""
        return bool(re.search(r'[0-9a-fA-F]{64}', content))

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            # Fallback regex
            match = re.search(r'https?://([^/\s]+)', url)
            return match.group(1).lower() if match else ""

    def _compile_verdict(
        self,
        findings: list[dict],
        risk_score: int,
        target: str = "",
        data_reviewed: bool = True,
    ) -> dict:
        """
        Compile final verdict from findings.

        Verdicts:
        - STOP: Critical findings - halt everything (score >= 50)
        - REJECT: High risk - don't proceed (score 30-49)
        - PAUSE: Medium risk - manual review needed (score 15-29)
        - PROCEED: Low risk - safe to continue (score < 15) **and**
          ``data_reviewed`` is True (i.e. the agent actually inspected
          something).
        - INSUFFICIENT_DATA: Caller did not provide content / target /
          identifying info, so no scans ran. Refusing to issue PROCEED
          on absence of evidence — empty findings means "nothing was
          checked", not "nothing is wrong".

        Args:
            findings: List of finding dictionaries
            risk_score: Composite risk score (0-100+)
            target: Target being reviewed
            data_reviewed: True iff the caller passed enough input for
                at least one scan to make a meaningful pass. When False,
                ``PROCEED`` is suppressed in favour of ``INSUFFICIENT_DATA``.

        Returns:
            Compiled review result
        """
        critical_count = sum(1 for f in findings if f["severity"] == "CRITICAL")
        high_count = sum(1 for f in findings if f["severity"] == "HIGH")

        if critical_count > 0 or risk_score >= 50:
            verdict = "STOP"
        elif high_count > 1 or risk_score >= 30:
            verdict = "REJECT"
        elif risk_score >= 15:
            verdict = "PAUSE"
        elif not data_reviewed:
            verdict = "INSUFFICIENT_DATA"
        else:
            verdict = "PROCEED"

        # Count by severity
        severity_counts: dict[str, int] = {}
        for f in findings:
            sev = f["severity"]
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        result = {
            "verdict": verdict,
            "risk_score": risk_score,
            "target": target,
            "findings_count": len(findings),
            "severity_counts": severity_counts,
            "critical_findings": critical_count,
            "findings": findings,
            "reviewed_at": time.time(),
            "veto_power": True,
            "strict_mode": self._strict_mode,
        }

        if verdict == "STOP":
            result["system_action"] = (
                "CRITICAL: Risk agent issued STOP. All operations must halt. "
                "Review findings immediately before proceeding."
            )
            logger.critical(
                "RISK STOP issued for target=%s: %d critical findings",
                target, critical_count,
            )
        elif verdict == "INSUFFICIENT_DATA":
            result["system_action"] = (
                "Risk review could not run — no content, repo, URL, or "
                "operation parameters were provided. Re-issue the task with "
                "concrete input before treating this as 'safe'."
            )
            logger.warning(
                "RISK INSUFFICIENT_DATA for target=%s: nothing to scan",
                target,
            )

        return result
