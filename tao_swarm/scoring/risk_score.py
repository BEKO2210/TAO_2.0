"""
Risk Scoring Algorithm

Calculates risk scores across four categories:
- technical: Code quality, test coverage, documentation
- financial: Market volatility, liquidity, tokenomics
- wallet: Address security, transaction patterns
- reputation: Community trust, developer activity

CRITICAL risk triggers automatic veto.
"""

import logging

logger = logging.getLogger(__name__)

# Risk category weights
RISK_CATEGORY_WEIGHTS = {
    "technical": 0.25,
    "financial": 0.30,
    "wallet": 0.20,
    "reputation": 0.25,
}

# Risk thresholds
RISK_LEVELS = [
    (0, 20, "LOW"),
    (20, 45, "MEDIUM"),
    (45, 70, "HIGH"),
    (70, 101, "CRITICAL"),
]

# CRITICAL patterns that trigger veto
CRITICAL_PATTERNS = [
    "critical_vulnerability",
    "hardcoded_private_key",
    "exposed_seed_phrase",
    "confirmed_scam",
    "malicious_contract",
    "rug_pull_detected",
    "hacker_address",
]


class RiskScorer:
    """
    Calculates comprehensive risk scores for Bittensor operations.

    Covers technical, financial, wallet, and reputation risks.
    CRITICAL-level risks trigger automatic veto.
    """

    def __init__(self, config: dict = None) -> None:
        """
        Initialize the risk scorer.

        Args:
            config: Optional configuration dictionary.
        """
        self.config = config or {}

    # ── Risk level helpers ────────────────────────────────────────────────

    @staticmethod
    def get_risk_level(score: float) -> str:
        """
        Convert numeric risk score to risk level string.

        Args:
            score: Risk score 0-100.

        Returns:
            'LOW', 'MEDIUM', 'HIGH', or 'CRITICAL'.
        """
        for lo, hi, level in RISK_LEVELS:
            if lo <= score < hi:
                return level
        return "CRITICAL"

    def should_veto(self, risk_data: dict) -> bool:
        """
        Determine if a risk should be vetoed.

        Args:
            risk_data: Dictionary with risk findings.

        Returns:
            True if the action should be vetoed (CRITICAL level or critical patterns).
        """
        # Check overall score
        total = risk_data.get("total_risk", 0)
        if self.get_risk_level(total) == "CRITICAL":
            logger.warning("CRITICAL risk detected (score=%.1f) - veto triggered", total)
            return True

        # Check for critical patterns in findings
        findings = risk_data.get("findings", [])
        for finding in findings:
            pattern = finding.get("pattern", "")
            if pattern in CRITICAL_PATTERNS:
                logger.warning("Critical pattern found: %s - veto triggered", pattern)
                return True
            if finding.get("severity") == "CRITICAL":
                logger.warning("CRITICAL severity finding - veto triggered")
                return True

        return False

    # ── Technical risk ────────────────────────────────────────────────────

    def _assess_technical_risk(self, context: dict) -> dict:
        """Assess technical/code-related risks."""
        score = 20.0  # Base risk
        findings = []

        repo_data = context.get("repo", {})
        if not repo_data:
            return {"score": 50.0, "findings": [{"pattern": "no_repo_data", "severity": "MEDIUM", "risk": 20}]}

        # No license
        if repo_data.get("license", "none") == "none":
            score += 10
            findings.append({"pattern": "no_license", "severity": "MEDIUM", "risk": 10})

        # Archived
        if repo_data.get("archived", False):
            score += 20
            findings.append({"pattern": "archived_repo", "severity": "HIGH", "risk": 20})

        # Very old / no updates
        updated = repo_data.get("updated_at", "")
        if updated:
            try:
                from datetime import datetime, timezone
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                days = (datetime.now(timezone.utc) - updated_dt).days
                if days > 180:
                    score += 15
                    findings.append({"pattern": "stale_repo", "severity": "HIGH", "risk": 15, "detail": f"{days} days since update"})
                elif days > 90:
                    score += 8
                    findings.append({"pattern": "aging_repo", "severity": "MEDIUM", "risk": 8, "detail": f"{days} days since update"})
            except Exception:
                pass

        # Fork (might not be maintained)
        if repo_data.get("is_fork", False):
            score += 5
            findings.append({"pattern": "is_fork", "severity": "LOW", "risk": 5})

        # No tests / low activity
        if repo_data.get("stars", 0) < 3:
            score += 10
            findings.append({"pattern": "very_low_stars", "severity": "MEDIUM", "risk": 10})

        return {"score": min(100, score), "findings": findings}

    # ── Financial risk ────────────────────────────────────────────────────

    def _assess_financial_risk(self, context: dict) -> dict:
        """Assess financial/market risks."""
        score = 20.0
        findings = []

        market = context.get("market", {})
        if not market:
            return {"score": 40.0, "findings": [{"pattern": "no_market_data", "severity": "MEDIUM", "risk": 20}]}

        # High volatility
        change_24h = abs(market.get("change_24h_pct", 0))
        if change_24h > 20:
            score += 20
            findings.append({"pattern": "extreme_volatility", "severity": "HIGH", "risk": 20, "detail": f"{change_24h:.1f}% 24h change"})
        elif change_24h > 10:
            score += 10
            findings.append({"pattern": "high_volatility", "severity": "MEDIUM", "risk": 10, "detail": f"{change_24h:.1f}% 24h change"})
        elif change_24h < 3:
            score -= 5

        # Low market cap
        mcap = market.get("market_cap_usd", 0)
        if mcap < 100_000_000:
            score += 10
            findings.append({"pattern": "low_market_cap", "severity": "MEDIUM", "risk": 10, "detail": f"${mcap:,.0f}"})

        # Low volume
        vol = market.get("volume_24h_usd", 0)
        if vol < 1_000_000:
            score += 15
            findings.append({"pattern": "low_liquidity", "severity": "HIGH", "risk": 15, "detail": f"${vol:,.0f} 24h vol"})
        elif vol < 10_000_000:
            score += 5
            findings.append({"pattern": "moderate_liquidity", "severity": "LOW", "risk": 5})

        return {"score": min(100, score), "findings": findings}

    # ── Wallet risk ───────────────────────────────────────────────────────

    def _assess_wallet_risk(self, context: dict) -> dict:
        """Assess wallet-related risks."""
        score = 10.0
        findings = []

        wallet = context.get("wallet", {})
        if not wallet:
            return {"score": 10.0, "findings": []}

        # Unknown address format
        address = wallet.get("address", "")
        if address and not address.startswith("5"):
            score += 25
            findings.append({"pattern": "unusual_address_format", "severity": "HIGH", "risk": 25})

        # High balance (more at risk)
        balance = wallet.get("balance", 0)
        if balance > 1000:
            score += 10
            findings.append({"pattern": "high_balance", "severity": "MEDIUM", "risk": 10, "detail": f"{balance:.2f} TAO"})

        # Many recent transactions (potential compromise)
        tx_count = wallet.get("recent_tx_count", 0)
        if tx_count > 50:
            score += 15
            findings.append({"pattern": "high_tx_frequency", "severity": "HIGH", "risk": 15})

        return {"score": min(100, score), "findings": findings}

    # ── Reputation risk ───────────────────────────────────────────────────

    def _assess_reputation_risk(self, context: dict) -> dict:
        """Assess reputation/community risks."""
        score = 15.0
        findings = []

        reputation = context.get("reputation", {})
        if not reputation:
            return {"score": 30.0, "findings": [{"pattern": "no_reputation_data", "severity": "MEDIUM", "risk": 15}]}

        # Low community activity
        followers = reputation.get("twitter_followers", 0)
        if followers < 100:
            score += 10
            findings.append({"pattern": "low_social_presence", "severity": "LOW", "risk": 10})

        # Negative sentiment
        sentiment = reputation.get("sentiment", "neutral")
        if sentiment == "negative":
            score += 25
            findings.append({"pattern": "negative_sentiment", "severity": "HIGH", "risk": 25})
        elif sentiment == "mixed":
            score += 10
            findings.append({"pattern": "mixed_sentiment", "severity": "MEDIUM", "risk": 10})

        # Reported issues
        reports = reputation.get("reports", 0)
        if reports > 10:
            score += 30
            findings.append({"pattern": "many_reports", "severity": "CRITICAL", "risk": 30})
        elif reports > 0:
            score += 15
            findings.append({"pattern": "some_reports", "severity": "HIGH", "risk": 15})

        return {"score": min(100, score), "findings": findings}

    # ── Composite risk ────────────────────────────────────────────────────

    def calculate_risk(self, context: dict) -> dict:
        """
        Calculate comprehensive risk score across all categories.

        Args:
            context: Dictionary with keys: 'repo', 'market', 'wallet', 'reputation'.

        Returns:
            Full risk assessment with category scores, total, level, and veto decision.
        """
        technical = self._assess_technical_risk(context)
        financial = self._assess_financial_risk(context)
        wallet = self._assess_wallet_risk(context)
        reputation = self._assess_reputation_risk(context)

        categories = {
            "technical": technical,
            "financial": financial,
            "wallet": wallet,
            "reputation": reputation,
        }

        # Weighted total
        total = sum(
            categories[cat]["score"] * RISK_CATEGORY_WEIGHTS[cat]
            for cat in categories
        )
        total = round(total, 2)

        # Combine all findings
        all_findings = []
        for cat, data in categories.items():
            for finding in data.get("findings", []):
                finding["category"] = cat
                all_findings.append(finding)

        risk_data = {
            "total_risk": total,
            "risk_level": self.get_risk_level(total),
            "categories": categories,
            "findings": all_findings,
            "num_findings": len(all_findings),
            "veto": False,
            "veto_reason": None,
        }

        # Check veto
        if self.should_veto(risk_data):
            risk_data["veto"] = True
            risk_data["veto_reason"] = "CRITICAL risk level or pattern detected"

        logger.info("Risk assessment: total=%.1f (%s) veto=%s", total, risk_data["risk_level"], risk_data["veto"])
        return risk_data

    # ── Convenience methods ───────────────────────────────────────────────

    def assess_subnet_risk(self, subnet_data: dict) -> dict:
        """
        Assess risk for a specific subnet.

        Args:
            subnet_data: Subnet profile dictionary.

        Returns:
            Risk assessment dictionary.
        """
        context = {
            "repo": subnet_data.get("github", {}),
            "market": {},
            "wallet": {},
            "reputation": {
                "twitter_followers": subnet_data.get("scores", {}).get("activity_score", 0),
            },
        }
        return self.calculate_risk(context)

    def assess_repo_risk(self, repo_data: dict) -> dict:
        """
        Assess risk for a GitHub repository.

        Args:
            repo_data: Repository info dictionary.

        Returns:
            Risk assessment dictionary.
        """
        context = {
            "repo": repo_data,
            "market": {},
            "wallet": {},
            "reputation": {},
        }
        return self.calculate_risk(context)

    def assess_trade_risk(self, trade_data: dict) -> dict:
        """
        Assess risk for a potential trade.

        Args:
            trade_data: Trade parameters dictionary.

        Returns:
            Risk assessment dictionary.
        """
        context = {
            "repo": {},
            "market": trade_data.get("market", {}),
            "wallet": trade_data.get("wallet", {}),
            "reputation": {},
        }
        return self.calculate_risk(context)
