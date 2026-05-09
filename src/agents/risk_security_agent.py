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


# ---------------------------------------------------------------------------
# Bittensor-specific detectors (added per online research, May 2026)
# ---------------------------------------------------------------------------

# Known-malicious bittensor-related PyPI packages from real incidents:
#   - May 2024: ``bittensor==6.12.2`` was a poisoned upstream release
#     that drained ~$8M / 32k TAO via patched stake_extrinsic.
#   - August 2025: GitLab found a typosquat campaign shipping
#     ``bitensor 9.9.4/9.9.5``, ``bittenso-cli 9.9.4``, and
#     ``qbittensor 9.9.4`` — same pattern, redirected funds.
# Format: (canonical_name, [malicious_versions]) where the empty
# version list means "any version of this name is malicious".
_BITTENSOR_PACKAGE_DENYLIST: dict[str, frozenset[str]] = {
    # Real poisoned release of the legitimate package
    "bittensor": frozenset({"6.12.2"}),
    # Pure typosquats — every version is malicious
    "bitensor": frozenset(),
    "bittenso": frozenset(),
    "bittenso-cli": frozenset(),
    "qbittensor": frozenset(),
    # Variants seen in the same Aug 2025 campaign
    "bittensor_cli": frozenset(),     # underscore typosquat of bittensor-cli
    "bittensoor": frozenset(),
    "bittensr": frozenset(),
}

# Coldkey-swap social-engineering markers. The 5-day arbitrated
# coldkey swap is irreversible and is being weaponised by attackers
# who pose as "support" telling the user "your key is compromised,
# schedule a swap to this safe address". Any text containing these
# tokens combined with a destination SS58 should escalate to DANGER.
_COLDKEY_SWAP_MARKERS: list[str] = [
    "schedule_coldkey_swap",
    "schedulecoldkeyswap",          # camelCase extrinsic name
    "btcli wallet schedule_coldkey_swap",
    "btcli w schedule_coldkey_swap",
    "swap-hotkey",
    "swap_hotkey",
]

# Urgency phrasing that pairs with coldkey-swap social-engineering.
# Real OTF / Latent communications never use this register.
_COLDKEY_SWAP_URGENCY: list[str] = [
    "execute within",
    "arbitration block",
    "your key is compromised",
    "your wallet is compromised",
    "act before",
    "must initiate immediately",
]

# SS58 (substrate) address heuristic: starts with '5', 47 chars after.
# Bittensor uses prefix 42 → addresses always start with '5'.
_SS58_PATTERN = re.compile(r"\b5[A-HJ-NP-Za-km-z1-9]{47}\b")

# Validators with hotkey age below this many blocks have no slashing
# track record. 4-month subnet immunity ≈ 4*30*24*1200 = 3,456,000
# blocks at 12s/block. Use a conservative cutoff for delegation risk.
_FRESH_HOTKEY_BLOCKS = 200_000  # ~28 days

# Take rate (validator commission) above this is a delegator trap —
# bait with low take, then raise. Bittensor caps take at 18% by
# default but subnet owners can take more.
_HIGH_TAKE_PCT = 18.0


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
            elif target == "validator":
                # Bittensor-specific delegation safety review.
                # Expected params: {"validator": {...}, "current_block": int}
                v = params.get("validator") or {}
                cb = int(params.get("current_block", 0))
                result = self.score_validator_risk(v, current_block=cb)
                # Wrap in the standard verdict shape used by other paths
                result.setdefault("findings_count", len(result.get("findings", [])))
                result.setdefault("target", "validator")
                result.setdefault("reviewed_at", time.time())
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
            result.setdefault("status", "complete")
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("RiskSecurityAgent: review failed: %s", e)
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
        if "type" not in task:
            return False, "task.type is required"
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

        # Bittensor-specific: PyPI typosquats in any embedded
        # ``pip install`` / requirements line in the content.
        pypi_findings, pypi_score = self.scan_bittensor_dependency(content)
        findings.extend(pypi_findings)
        risk_score += pypi_score

        # Bittensor-specific: coldkey-swap social engineering.
        watchlist = set(params.get("watchlist_addresses") or [])
        swap_findings, swap_score = self.scan_coldkey_swap_pattern(
            content, watchlist_addresses=watchlist,
        )
        findings.extend(swap_findings)
        risk_score += swap_score

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

    # ── Bittensor-specific detectors (added per online research) ──────────

    def scan_bittensor_dependency(self, dep_string: str) -> tuple[list[dict], int]:
        """
        Scan a single dependency string (line of requirements.txt,
        ``pip install ...`` command, or import statement) for the
        known-malicious bittensor packages from the May 2024 and
        August 2025 supply-chain incidents.

        Detects:

        - Exact poisoned versions on the legitimate ``bittensor``
          package (e.g. ``bittensor==6.12.2``).
        - Any version of the known typosquats (``bitensor``,
          ``bittenso``, ``bittenso-cli``, ``qbittensor``,
          ``bittensor_cli`` with underscore, …).
        - Installs from non-PyPI indexes via ``--index-url`` or
          ``--extra-index-url`` pointing anywhere except pypi.org —
          a common vector for sideloaded malicious wheels.

        Returns ``(findings, risk_score)`` so callers can fold this
        into ``_compile_verdict``. CRITICAL findings score 50 each.
        """
        findings: list[dict] = []
        score = 0
        text = (dep_string or "").lower().strip()
        if not text:
            return findings, 0

        # Off-PyPI index → CRITICAL on its own (sideload vector)
        for marker in ("--index-url", "--extra-index-url"):
            idx = text.find(marker)
            if idx == -1:
                continue
            after = text[idx + len(marker):].strip(" =").split()[0:1]
            url = after[0] if after else ""
            if url and "pypi.org" not in url and "files.pythonhosted.org" not in url:
                findings.append({
                    "severity": "CRITICAL",
                    "category": "supply_chain_off_pypi_index",
                    "finding": f"pip install via non-PyPI index: {url}",
                    "recommendation": (
                        "STOP — only install bittensor from pypi.org. "
                        "Custom indexes are the vector used by the Aug "
                        "2025 typosquat campaign."
                    ),
                })
                score += 50

        # Parse out package name + optional version pin. Cover the
        # common shapes:  bittensor==6.12.2  bittensor>=8  bittensor
        for match in re.finditer(
            r"\b([a-zA-Z][a-zA-Z0-9_-]*)\s*(?:==|>=|<=|~=|!=|>|<)?\s*([\d.]*)",
            text,
        ):
            name_raw = match.group(1)
            version = match.group(2)
            name = name_raw.lower()
            if name not in _BITTENSOR_PACKAGE_DENYLIST:
                continue
            bad_versions = _BITTENSOR_PACKAGE_DENYLIST[name]
            # Empty bad_versions = the whole package is a known typosquat
            if not bad_versions or version in bad_versions:
                hint = (
                    f"version {version} on the legitimate name"
                    if name == "bittensor" and version
                    else f"typosquat of bittensor / bittensor-cli"
                )
                findings.append({
                    "severity": "CRITICAL",
                    "category": "supply_chain_malicious_package",
                    "finding": f"Known-malicious bittensor package: {name_raw}{('==' + version) if version else ''} — {hint}",
                    "recommendation": (
                        "STOP — this package version was used in a real "
                        "Bittensor wallet-draining campaign. Uninstall "
                        "immediately: `pip uninstall " + name_raw + "`."
                    ),
                    "package": name,
                    "version": version,
                })
                score += 50

        return findings, score

    def scan_coldkey_swap_pattern(
        self,
        content: str,
        watchlist_addresses: set[str] | None = None,
    ) -> tuple[list[dict], int]:
        """
        Detect the coldkey-swap social-engineering pattern.

        Real OTF / Latent communications never instruct users to
        schedule a ``schedule_coldkey_swap`` to a third-party address.
        Any text containing the swap markers + an SS58 destination
        that isn't already in the user's watchlist + urgency phrasing
        scores CRITICAL. The 5-day arbitrated swap is irreversible
        once executed.

        Args:
            content: Free-form text to scan (chat message, doc, etc.)
            watchlist_addresses: Optional set of SS58 addresses the
                user already trusts. Destinations that match these
                downgrade the finding from CRITICAL to HIGH.

        Returns ``(findings, risk_score)``.
        """
        findings: list[dict] = []
        score = 0
        text = (content or "").lower()
        if not text:
            return findings, 0

        # Marker present?
        marker_hit = next(
            (m for m in _COLDKEY_SWAP_MARKERS if m in text),
            None,
        )
        if not marker_hit:
            return findings, 0

        # Destination SS58 in the text?
        # (Operate on the original case-preserving content for SS58 match.)
        ss58_matches = _SS58_PATTERN.findall(content or "")
        urgency_hit = any(u in text for u in _COLDKEY_SWAP_URGENCY)
        watchlist = watchlist_addresses or set()

        # Worst case: marker + new (non-watchlist) destination + urgency.
        for ss58 in ss58_matches:
            in_watchlist = ss58 in watchlist
            severity = "HIGH" if in_watchlist else "CRITICAL"
            findings.append({
                "severity": severity,
                "category": "coldkey_swap_social_engineering",
                "finding": (
                    f"Coldkey swap instruction detected ('{marker_hit}') "
                    f"with destination {ss58[:10]}..."
                    + (" (in watchlist)" if in_watchlist else " (NOT in watchlist)")
                    + (" + urgency phrasing" if urgency_hit else "")
                ),
                "recommendation": (
                    "STOP — verify out-of-band before executing any "
                    "schedule_coldkey_swap. The 5-day arbitrated swap is "
                    "irreversible and OTF/Latent CANNOT intervene. Real "
                    "support never asks you to swap your coldkey."
                ),
                "destination_ss58": ss58,
                "in_watchlist": in_watchlist,
                "urgency_detected": urgency_hit,
            })
            score += 50 if severity == "CRITICAL" else 30

        # Marker without any SS58 in the text — still suspicious as
        # a precursor to a follow-up message with the address.
        if not ss58_matches:
            findings.append({
                "severity": "HIGH" if urgency_hit else "MEDIUM",
                "category": "coldkey_swap_marker_only",
                "finding": (
                    f"Coldkey-swap command reference '{marker_hit}' detected "
                    "without a destination address — likely precursor to a "
                    "social-engineering follow-up."
                ),
                "recommendation": (
                    "Treat any subsequent message asking to swap your "
                    "coldkey as suspicious. Verify the destination "
                    "address out-of-band."
                ),
            })
            score += 30 if urgency_hit else 15

        return findings, score

    def score_validator_risk(self, validator: dict, current_block: int = 0) -> dict:
        """
        Risk-score a validator hotkey for delegation safety.

        Computes a 0..100 risk score and a list of red-flag findings
        from the validator's on-chain shape. Higher score = more risk.
        Built around the patterns the online research surfaced:

        - Hotkey age below ``_FRESH_HOTKEY_BLOCKS`` (~28 days) — no
          slashing track record, can be a fresh impersonator.
        - No axon endpoint serving — validator publishes nothing.
        - ``vtrust == 0`` on subnets where the validator holds a
          permit — they have a permit but aren't trusted.
        - Recent take rate spike — bait-then-raise delegator trap.
        - Take rate already above ``_HIGH_TAKE_PCT``.
        - Coldkey has scheduled a swap — about to rotate out.

        Args:
            validator: Dict with optional keys: ``hotkey``, ``coldkey``,
                ``registered_block``, ``take_pct``, ``take_history``
                (list of ``[block, pct]`` tuples), ``vtrust_per_subnet``
                (dict of netuid→vtrust), ``axon_serving`` (bool),
                ``scheduled_coldkey_swap_block`` (int|None),
                ``identity_name`` (str).
            current_block: Reference block for age comparisons.

        Returns:
            ``{"score": int, "findings": list[dict], "verdict": str}``
        """
        findings: list[dict] = []
        score = 0

        # 1. Fresh hotkey — no slashing history
        registered = validator.get("registered_block", 0)
        if current_block and registered:
            age_blocks = current_block - registered
            if age_blocks < _FRESH_HOTKEY_BLOCKS:
                findings.append({
                    "severity": "HIGH",
                    "category": "fresh_validator_hotkey",
                    "finding": (
                        f"Hotkey age {age_blocks} blocks "
                        f"(< {_FRESH_HOTKEY_BLOCKS} threshold)"
                    ),
                    "recommendation": (
                        "Wait at least one full immunity period before "
                        "delegating. Fresh hotkeys can be impersonators."
                    ),
                })
                score += 30

        # 2. No axon serving
        if validator.get("axon_serving") is False:
            findings.append({
                "severity": "MEDIUM",
                "category": "no_axon_serving",
                "finding": "Validator publishes no axon endpoint",
                "recommendation": (
                    "Real validators serve axons. Absent axon = absent "
                    "real work."
                ),
            })
            score += 15

        # 3. vtrust=0 on permitted subnets
        vtrust = validator.get("vtrust_per_subnet") or {}
        zero_vtrust = [n for n, t in vtrust.items() if t == 0]
        if zero_vtrust:
            findings.append({
                "severity": "MEDIUM",
                "category": "zero_vtrust_with_permit",
                "finding": (
                    f"Validator holds permit but vtrust=0 on "
                    f"subnet(s) {zero_vtrust}"
                ),
                "recommendation": (
                    "Validator is registered but not trusted by other "
                    "validators on these subnets — likely weight-copying "
                    "or otherwise misbehaving."
                ),
            })
            score += 20

        # 4. Recent take spike
        take_history = validator.get("take_history") or []
        if len(take_history) >= 2:
            recent_take = take_history[-1][1]
            prev_take = take_history[-2][1]
            if recent_take > prev_take + 5.0:
                findings.append({
                    "severity": "HIGH",
                    "category": "validator_take_spike",
                    "finding": (
                        f"Take raised from {prev_take:.1f}% to "
                        f"{recent_take:.1f}% — bait-then-raise pattern"
                    ),
                    "recommendation": (
                        "Validator increased commission sharply — typical "
                        "delegator trap. Consider undelegating."
                    ),
                })
                score += 30

        # 5. High take rate
        take_pct = validator.get("take_pct", 0.0)
        if take_pct > _HIGH_TAKE_PCT:
            findings.append({
                "severity": "MEDIUM",
                "category": "high_take_rate",
                "finding": f"Take rate {take_pct:.1f}% > {_HIGH_TAKE_PCT}% threshold",
                "recommendation": "Compare against subnet median take.",
            })
            score += 15

        # 6. Scheduled coldkey swap (about to rotate out)
        if validator.get("scheduled_coldkey_swap_block"):
            findings.append({
                "severity": "CRITICAL",
                "category": "scheduled_coldkey_swap",
                "finding": (
                    "Validator coldkey has a scheduled swap pending — "
                    "delegations may be lost or redirected when it executes"
                ),
                "recommendation": (
                    "Do not delegate to a validator with a pending "
                    "coldkey swap. Wait for the swap to execute or be "
                    "cancelled."
                ),
            })
            score += 50

        # Verdict mapping (independent of _compile_verdict because the
        # caller may want to embed this into a per-validator report
        # rather than a global review).
        if score >= 50:
            verdict = "STOP"
        elif score >= 30:
            verdict = "REJECT"
        elif score >= 15:
            verdict = "PAUSE"
        else:
            verdict = "PROCEED"

        return {
            "score": score,
            "verdict": verdict,
            "findings": findings,
            "validator_hotkey": validator.get("hotkey"),
        }

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
