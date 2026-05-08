"""
Subnet Scoring Algorithm

Scores Bittensor subnets across 10 weighted criteria:
- technical_fit (15%), hardware_fit (15%), setup_complexity (10%),
  doc_quality (10%), competition (15%), reward_realism (10%),
  maintenance (10%), security_risk (5%), learning_value (5%), long_term (5%)

Returns a 0-100 score with actionable recommendations.
"""

import json
import logging
import os
import sqlite3
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Criterion weights (must sum to 1.0)
CRITERIA_WEIGHTS = {
    "technical_fit": 0.15,
    "hardware_fit": 0.15,
    "setup_complexity": 0.10,
    "doc_quality": 0.10,
    "competition": 0.15,
    "reward_realism": 0.10,
    "maintenance": 0.10,
    "security_risk": 0.05,
    "learning_value": 0.05,
    "long_term": 0.05,
}

# Recommendation thresholds and labels
RECOMMENDATION_LABELS = [
    (0, 20, "Ignorieren", "Subnet ist nicht empfohlen. Zu hohe Risiken oder zu geringe Chancen."),
    (20, 40, "Beobachten", "Subnet hat Potential, aber wichtige Bedenken. Nur beobachten, nicht aktiv werden."),
    (40, 60, "Lernen", "Gutes Lernpotential. Code und Dokumentation studieren, aber noch nicht deployen."),
    (60, 75, "Testen", "Subnet ist testenswert. Paper-Trading oder Testnet-Deployment empfohlen."),
    (75, 88, "Miner-Kandidat", "Gutes Verhältnis aus Aufwand und Belohnung. Miner-Setup sinnvoll."),
    (88, 100, "Validator-Kandidat", "Hervorragendes Subnet. Validator-Setup mit Stake empfohlen."),
]


class SubnetScorer:
    """
    Scores Bittensor subnets across multiple weighted criteria.

    Produces a 0-100 score with detailed breakdowns and recommendations.
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Initialize the subnet scorer.

        Args:
            config: Optional configuration dict with:
                - 'db_path': SQLite path for score history
        """
        self.config = config or {}
        self.db_path = self.config.get("db_path", "data/scores.db")
        self._init_db()

    def _init_db(self) -> None:
        """Create score history table."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subnet_scores (
                    netuid INTEGER NOT NULL,
                    score REAL NOT NULL,
                    breakdown TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    scored_at REAL NOT NULL
                )
            """)
            conn.commit()

    # ── Individual scoring functions ────────────────────────────────────────

    def score_technical_fit(self, data: dict) -> float:
        """
        Score technical fit (0-100).

        Evaluates whether the subnet's technical requirements match
        the available skills and stack.
        """
        score = 50.0  # Base
        profile = data.get("profile", {})
        hardware = profile.get("hardware_requirements", {})
        github = profile.get("github", {})

        # Language match bonus
        lang = github.get("language", "").lower()
        if lang in ("python", "rust"):
            score += 20
        elif lang in ("typescript", "javascript", "go"):
            score += 10

        # GPU requirement check
        gpu = hardware.get("gpu", "none")
        if "a100" in gpu.lower() or "h100" in gpu.lower():
            score -= 10  # High-end GPU needed
        elif "none" in gpu.lower():
            score += 10  # No GPU needed

        # Code complexity from repo size
        size = github.get("size_kb", 0)
        if size < 100:
            score += 5  # Small, manageable
        elif size > 10000:
            score -= 5  # Very large codebase

        return max(0.0, min(100.0, score))

    def score_hardware_fit(self, data: dict) -> float:
        """
        Score hardware compatibility (0-100).

        Evaluates whether the required hardware is accessible and affordable.
        """
        score = 50.0
        profile = data.get("profile", {})
        hardware = profile.get("hardware_requirements", {})

        vram = hardware.get("vram_gb", 0)
        ram = hardware.get("ram_gb", 0)
        disk = hardware.get("disk_gb", 0)
        cost = hardware.get("estimated_cost_monthly_usd", 0)

        # VRAM scoring
        if vram == 0:
            score += 25  # No GPU needed = very accessible
        elif vram <= 16:
            score += 15
        elif vram <= 40:
            score += 0
        elif vram <= 80:
            score -= 15
        else:
            score -= 25

        # RAM scoring
        if ram <= 16:
            score += 10
        elif ram <= 32:
            score += 5
        elif ram <= 64:
            score += 0
        else:
            score -= 10

        # Cost scoring
        if cost <= 50:
            score += 15
        elif cost <= 200:
            score += 5
        elif cost <= 500:
            score -= 5
        elif cost <= 1000:
            score -= 15
        else:
            score -= 25

        return max(0.0, min(100.0, score))

    def score_setup_complexity(self, data: dict) -> float:
        """
        Score setup complexity (0-100).

        Lower complexity = higher score (inverted).
        """
        score = 70.0
        profile = data.get("profile", {})
        docs = profile.get("documentation", {})
        github = profile.get("github", {})

        # Documentation quality helps setup
        if docs.get("has_installation"):
            score += 10
        if docs.get("has_examples"):
            score += 5
        if docs.get("code_blocks", 0) > 5:
            score += 5

        # README presence
        readme = github.get("description", "")
        if readme and len(readme) > 50:
            score += 5

        # Repo size as proxy for complexity
        size = github.get("size_kb", 0)
        if size < 500:
            score += 5
        elif size > 50000:
            score -= 10

        return max(0.0, min(100.0, score))

    def score_doc_quality(self, data: dict) -> float:
        """
        Score documentation quality (0-100).
        """
        score = 30.0
        profile = data.get("profile", {})
        docs = profile.get("documentation", {})

        if not docs or "error" in docs:
            return score

        if docs.get("has_installation"):
            score += 20
        if docs.get("has_api_docs"):
            score += 15
        if docs.get("has_examples"):
            score += 15

        h2_count = docs.get("headings_h2", 0)
        if h2_count > 5:
            score += 10
        elif h2_count > 2:
            score += 5

        if docs.get("content_length", 0) > 5000:
            score += 10

        return min(100.0, score)

    def score_competition(self, data: dict) -> float:
        """
        Score competitive landscape (0-100).

        Higher score = less competition = better opportunity.
        """
        score = 50.0
        profile = data.get("profile", {})
        chain = profile.get("chain_info", {})

        neurons = chain.get("num_neurons", 0)
        max_neurons = chain.get("max_neurons", 1)

        if max_neurons > 0:
            fill_ratio = neurons / max_neurons
            if fill_ratio < 0.3:
                score += 30  # Lots of room
            elif fill_ratio < 0.6:
                score += 15
            elif fill_ratio < 0.8:
                score += 0
            else:
                score -= 20  # Almost full

        # GitHub stars as proxy for developer interest
        github = profile.get("github", {})
        stars = github.get("stars", 0)
        if stars < 10:
            score += 10  # Low attention = opportunity
        elif stars > 500:
            score -= 10  # High attention = more competition

        return max(0.0, min(100.0, score))

    def score_reward_realism(self, data: dict) -> float:
        """
        Score reward realism (0-100).

        Evaluates whether advertised rewards are realistic.
        """
        score = 50.0
        profile = data.get("profile", {})
        history = profile.get("reward_history", [])

        if len(history) >= 7:
            # Calculate reward stability
            rewards = [h["reward"] for h in history]
            avg_reward = sum(rewards) / len(rewards)
            if avg_reward > 0:
                variance = sum((r - avg_reward) ** 2 for r in rewards) / len(rewards)
                std_dev = variance ** 0.5
                cv = std_dev / avg_reward  # Coefficient of variation

                if cv < 0.1:
                    score += 20  # Very stable
                elif cv < 0.3:
                    score += 10
                elif cv < 0.5:
                    score += 0
                else:
                    score -= 15  # Very volatile

            # Trend check
            if len(history) >= 14:
                first_half = sum(rewards[:len(rewards)//2]) / max(len(rewards)//2, 1)
                second_half = sum(rewards[len(rewards)//2:]) / max(len(rewards) - len(rewards)//2, 1)
                if second_half > first_half * 1.1:
                    score += 10  # Growing rewards
                elif second_half < first_half * 0.7:
                    score -= 15  # Declining rewards

        return max(0.0, min(100.0, score))

    def score_maintenance(self, data: dict) -> float:
        """
        Score maintenance level (0-100).

        Evaluates ongoing maintenance and support quality.
        """
        score = 40.0
        profile = data.get("profile", {})
        github = profile.get("github", {})

        # Recent activity
        updated = github.get("updated_at", "")
        if updated:
            try:
                from datetime import datetime, timezone
                updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                days_since = (datetime.now(timezone.utc) - updated_dt).days
                if days_since < 7:
                    score += 20
                elif days_since < 30:
                    score += 10
                elif days_since < 90:
                    score += 0
                else:
                    score -= 20
            except Exception:
                pass

        # Open issues ratio
        open_issues = github.get("open_issues", 0)
        # Lower is better (reasonable maintenance)
        if open_issues < 5:
            score += 10
        elif open_issues > 50:
            score -= 10

        # Has wiki / discussions
        if github.get("has_wiki"):
            score += 5
        if github.get("has_discussions"):
            score += 5

        return max(0.0, min(100.0, score))

    def score_security_risk(self, data: dict) -> float:
        """
        Score security risk (0-100).

        Higher = lower risk = better. Inverted risk score.
        """
        score = 60.0
        profile = data.get("profile", {})
        github = profile.get("github", {})

        # License presence
        if github.get("license", "none") != "none":
            score += 10

        # Not a fork
        if not github.get("is_fork", False):
            score += 5

        # Not archived
        if not github.get("archived", False):
            score += 10
        else:
            score -= 30

        # Multiple contributors = more eyes
        # (This would need contributor data)

        return min(100.0, score)

    def score_learning_value(self, data: dict) -> float:
        """
        Score learning value (0-100).

        Evaluates educational value of studying this subnet.
        """
        score = 50.0
        profile = data.get("profile", {})
        github = profile.get("github", {})
        docs = profile.get("documentation", {})

        # Good documentation = better learning
        if docs.get("has_examples"):
            score += 15
        if docs.get("has_api_docs"):
            score += 10
        if docs.get("code_blocks", 0) > 10:
            score += 10

        # Well-known language
        lang = github.get("language", "").lower()
        if lang == "python":
            score += 10  # Most accessible

        # Reasonable size for learning
        size = github.get("size_kb", 0)
        if 100 < size < 5000:
            score += 5

        return min(100.0, score)

    def score_long_term(self, data: dict) -> float:
        """
        Score long-term viability (0-100).
        """
        score = 50.0
        profile = data.get("profile", {})
        github = profile.get("github", {})
        chain = profile.get("chain_info", {})

        # Community size proxy
        stars = github.get("stars", 0)
        forks = github.get("forks", 0)
        if stars > 100:
            score += 15
        elif stars > 20:
            score += 10

        if forks > 20:
            score += 10
        elif forks > 5:
            score += 5

        # Subnet maturity
        created = chain.get("created_at_block", 0)
        if created > 0:
            # Older subnets that are still active = more stable
            pass

        # Maintenance quality
        updated = github.get("updated_at", "")
        if updated:
            score += 10

        return min(100.0, score)

    # ── Composite scoring ───────────────────────────────────────────────────

    def score_subnet(self, subnet_data: dict) -> dict:
        """
        Calculate composite score for a subnet.

        Args:
            subnet_data: Dictionary with subnet profile data.
                Expected structure: {"netuid": int, "profile": dict}

        Returns:
            Dictionary with total score (0-100), breakdown, and recommendation.
        """
        netuid = subnet_data.get("netuid", 0)

        # Score all criteria
        scores = {
            "technical_fit": self.score_technical_fit(subnet_data),
            "hardware_fit": self.score_hardware_fit(subnet_data),
            "setup_complexity": self.score_setup_complexity(subnet_data),
            "doc_quality": self.score_doc_quality(subnet_data),
            "competition": self.score_competition(subnet_data),
            "reward_realism": self.score_reward_realism(subnet_data),
            "maintenance": self.score_maintenance(subnet_data),
            "security_risk": self.score_security_risk(subnet_data),
            "learning_value": self.score_learning_value(subnet_data),
            "long_term": self.score_long_term(subnet_data),
        }

        # Weighted total
        total = sum(scores[c] * CRITERIA_WEIGHTS[c] for c in scores)
        total = max(0.0, min(100.0, round(total, 2)))

        # Recommendation
        recommendation = self.get_recommendation(total)

        result = {
            "netuid": netuid,
            "total_score": total,
            "breakdown": scores,
            "weights": CRITERIA_WEIGHTS,
            "recommendation": recommendation,
            "scored_at": int(time.time()),
        }

        # Persist
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO subnet_scores (netuid, score, breakdown, recommendation, scored_at) VALUES (?, ?, ?, ?, ?)",
                (netuid, total, json.dumps(scores), recommendation["label"], time.time()),
            )
            conn.commit()

        logger.info("Subnet netuid=%d scored: %.1f - %s", netuid, total, recommendation["label"])
        return result

    def get_recommendation(self, score: float) -> dict:
        """
        Get recommendation based on total score.

        Args:
            score: Total score (0-100).

        Returns:
            Dictionary with label, description, and action suggestion.
        """
        for lo, hi, label, desc in RECOMMENDATION_LABELS:
            if lo <= score < hi:
                return {"label": label, "description": desc, "min_score": lo, "max_score": hi}
        # Fallback for score == 100
        return {"label": "Validator-Kandidat", "description": RECOMMENDATION_LABELS[-1][3], "min_score": 88, "max_score": 100}

    def generate_score_report(self, netuid: int) -> dict:
        """
        Generate a comprehensive score report for a subnet.

        Args:
            netuid: Subnet identifier.

        Returns:
            Full report dictionary with score history and analysis.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT score, breakdown, recommendation, scored_at FROM subnet_scores WHERE netuid = ? ORDER BY scored_at DESC LIMIT 10",
                (netuid,),
            ).fetchall()

        history = []
        for r in rows:
            history.append({
                "score": r[0],
                "breakdown": json.loads(r[1]),
                "recommendation": r[2],
                "scored_at": r[3],
            })

        return {
            "netuid": netuid,
            "score_count": len(history),
            "latest_score": history[0] if history else None,
            "score_history": history,
            "trend": "stable" if len(history) < 2 else (
                "improving" if history[0]["score"] > history[-1]["score"] else
                "declining" if history[0]["score"] < history[-1]["score"] else "stable"
            ),
            "generated_at": int(time.time()),
        }
