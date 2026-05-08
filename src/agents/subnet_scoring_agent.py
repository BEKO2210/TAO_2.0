"""
Subnet Scoring Agent (Agent 4).

Evaluates subnets using 10 weighted criteria (0-100 each):
Technical Fit, Hardware Fit, Setup Complexity, Documentation Quality,
Competition, Reward Realism, Maintenance, Security, Learning Value,
and Long-Term Potential.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "subnet_scoring_agent"
AGENT_VERSION: str = "1.0.0"

# Default weights for scoring criteria
_DEFAULT_CRITERIA_WEIGHTS: dict[str, float] = {
    "technical_fit": 1.0,
    "hardware_fit": 1.0,
    "setup_complexity": 0.8,
    "documentation_quality": 1.0,
    "competition": 0.8,
    "reward_realism": 1.0,
    "maintenance": 0.7,
    "security": 1.0,
    "learning_value": 0.6,
    "long_term_potential": 0.7,
}


class SubnetScoringAgent:
    """
    Agent for scoring Bittensor subnets against 10 criteria.

    Each criterion is scored 0-100. The final score is weighted and
    normalized. Criteria cover technical alignment, hardware requirements,
    documentation, competition, rewards, maintenance, security,
    learning value, and long-term viability.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the SubnetScoringAgent.

        Args:
            config: Configuration with optional:
                - criteria_weights: Custom weights dict
                - min_score_threshold: Minimum score to recommend
                - user_skills: List of user skills for technical fit
                - available_hardware: Hardware description dict
        """
        self.config: dict = config
        self._status: str = "idle"
        self._scores: list[dict] = []
        self._weights: dict[str, float] = config.get(
            "criteria_weights", dict(_DEFAULT_CRITERIA_WEIGHTS)
        )
        self._min_threshold: int = config.get("min_score_threshold", 50)
        self._user_skills: list[str] = config.get("user_skills", [])
        self._available_hardware: dict = config.get("available_hardware", {})
        logger.info(
            "SubnetScoringAgent initialized (weights=%d, threshold=%d)",
            len(self._weights), self._min_threshold,
        )

    def run(self, task: dict) -> dict:
        """
        Run subnet scoring.

        Args:
            task: Dictionary with 'params' containing:
                - subnets: List of subnet dictionaries to score
                - netuid: Specific NetUID to score
                - custom_weights: Override default weights

        Returns:
            Scoring results with per-subnet scores and justifications
        """
        self._status = "running"
        params = task.get("params", {})
        subnets = params.get("subnets", [])
        custom_weights = params.get("custom_weights", {})

        if custom_weights:
            self._weights.update(custom_weights)

        logger.info(
            "SubnetScoringAgent: scoring %d subnets", len(subnets)
        )

        try:
            scored_subnets: list[dict] = []
            for subnet in subnets:
                score = self._score_subnet(subnet)
                scored_subnets.append(score)

            # Sort by final score descending
            scored_subnets.sort(key=lambda s: s["final_score"], reverse=True)

            result = {
                "scored_subnets": scored_subnets,
                "recommendations": self._generate_recommendations(scored_subnets),
                "weights_used": self._weights,
                "total_scored": len(scored_subnets),
            }

            self._scores.extend(scored_subnets)
            self._status = "complete"
            logger.info("SubnetScoringAgent: scoring complete")
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("SubnetScoringAgent: scoring failed: %s", e)
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
            "subnets_scored": len(self._scores),
            "criteria_weights": self._weights,
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
        subnets = params.get("subnets", [])
        if not isinstance(subnets, list):
            return False, "subnets must be a list"
        return True, ""

    def _score_subnet(self, subnet: dict) -> dict:
        """
        Score a single subnet across all 10 criteria.

        Args:
            subnet: Subnet dictionary with metadata

        Returns:
            Scored subnet with per-criterion scores and final score
        """
        scores: dict[str, dict] = {}

        # 1. Technical Fit (0-100)
        scores["technical_fit"] = self._score_technical_fit(subnet)

        # 2. Hardware Fit (0-100)
        scores["hardware_fit"] = self._score_hardware_fit(subnet)

        # 3. Setup Complexity (0-100, higher = easier)
        scores["setup_complexity"] = self._score_setup_complexity(subnet)

        # 4. Documentation Quality (0-100)
        scores["documentation_quality"] = self._score_documentation(subnet)

        # 5. Competition (0-100, higher = less competition = better)
        scores["competition"] = self._score_competition(subnet)

        # 6. Reward Realism (0-100)
        scores["reward_realism"] = self._score_reward_realism(subnet)

        # 7. Maintenance Burden (0-100, higher = lower burden = better)
        scores["maintenance"] = self._score_maintenance(subnet)

        # 8. Security (0-100)
        scores["security"] = self._score_security(subnet)

        # 9. Learning Value (0-100)
        scores["learning_value"] = self._score_learning_value(subnet)

        # 10. Long-Term Potential (0-100)
        scores["long_term_potential"] = self._score_long_term_potential(subnet)

        # Calculate weighted final score
        total_weight = sum(self._weights.values())
        weighted_sum = sum(
            scores[c]["score"] * self._weights.get(c, 1.0)
            for c in scores
        )
        final_score = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0

        # Determine recommendation
        if final_score >= 70:
            recommendation = "RECOMMENDED"
        elif final_score >= self._min_threshold:
            recommendation = "CONDITIONAL"
        else:
            recommendation = "NOT RECOMMENDED"

        return {
            "netuid": subnet.get("netuid", -1),
            "name": subnet.get("name", "Unknown"),
            "category": subnet.get("category", "unknown"),
            "final_score": final_score,
            "recommendation": recommendation,
            "criteria_scores": scores,
            "scored_at": time.time(),
        }

    def _score_technical_fit(self, subnet: dict) -> dict:
        """Score technical fit based on user skills vs subnet requirements."""
        category = subnet.get("category", "unknown")
        skill_map: dict[str, list[str]] = {
            "nlp": ["python", "ml", "transformers", "pytorch"],
            "vision": ["python", "ml", "computer_vision", "pytorch"],
            "audio": ["python", "ml", "audio", "pytorch"],
            "multimodal": ["python", "ml", "multimodal", "pytorch"],
            "inference": ["python", "api", "deployment", "gpu"],
            "data": ["python", "scraping", "etl", "data_engineering"],
            "compute": ["python", "distributed", "systems"],
            "governance": ["python", "blockchain"],
            "infrastructure": ["python", "devops", "storage"],
            "search": ["python", "search", "algorithms"],
            "reasoning": ["python", "ml", "reasoning", "nlp"],
        }

        if not self._user_skills:
            return {"score": 50, "reason": "No user skills configured - neutral score"}

        relevant_skills = skill_map.get(category, [])
        if not relevant_skills:
            return {"score": 40, "reason": f"Unknown category '{category}' - low score"}

        user_lower = [s.lower() for s in self._user_skills]
        matches = sum(1 for s in relevant_skills if s.lower() in user_lower)
        ratio = matches / len(relevant_skills) if relevant_skills else 0
        score = round(ratio * 100)

        return {
            "score": score,
            "reason": (
                f"Matched {matches}/{len(relevant_skills)} relevant skills "
                f"for {category}: {relevant_skills}"
            ),
        }

    def _score_hardware_fit(self, subnet: dict) -> dict:
        """Score hardware fit based on available vs required hardware."""
        hw_min = subnet.get("hardware_min", {})

        if not self._available_hardware:
            return {
                "score": 50,
                "reason": "No hardware info available - neutral score",
            }

        checks: list[str] = []
        pass_count = 0
        total_checks = 0

        # Check RAM
        if "ram_gb" in hw_min:
            total_checks += 1
            avail_ram = self._available_hardware.get("ram_gb", 0)
            req_ram = hw_min["ram_gb"]
            if avail_ram >= req_ram:
                pass_count += 1
                checks.append(f"RAM OK: {avail_ram}GB >= {req_ram}GB")
            else:
                checks.append(f"RAM insufficient: {avail_ram}GB < {req_ram}GB")

        # Check GPU
        if hw_min.get("gpu") == "required":
            total_checks += 1
            if self._available_hardware.get("has_gpu", False):
                pass_count += 1
                checks.append("GPU available")
            else:
                checks.append("GPU required but not available")

            # Check VRAM
            if "vram_gb" in hw_min:
                total_checks += 1
                avail_vram = self._available_hardware.get("vram_gb", 0)
                req_vram = hw_min["vram_gb"]
                if avail_vram >= req_vram:
                    pass_count += 1
                    checks.append(f"VRAM OK: {avail_vram}GB >= {req_vram}GB")
                else:
                    checks.append(f"VRAM insufficient: {avail_vram}GB < {req_vram}GB")
        elif hw_min.get("gpu") == "optional":
            total_checks += 1
            if self._available_hardware.get("has_gpu", False):
                pass_count += 1
                checks.append("GPU available (optional)")
            else:
                pass_count += 1
                checks.append("GPU optional - not required")
        else:
            total_checks += 1
            pass_count += 1
            checks.append("No GPU required")

        # Check CPU cores
        if "cpu_cores" in hw_min:
            total_checks += 1
            avail_cores = self._available_hardware.get("cpu_cores", 0)
            req_cores = hw_min["cpu_cores"]
            if avail_cores >= req_cores:
                pass_count += 1
                checks.append(f"CPU OK: {avail_cores} cores >= {req_cores}")
            else:
                checks.append(f"CPU insufficient: {avail_cores} cores < {req_cores}")

        score = round((pass_count / total_checks) * 100) if total_checks > 0 else 50
        return {
            "score": score,
            "reason": f"Hardware check: {pass_count}/{total_checks} passed. " + "; ".join(checks),
        }

    def _score_setup_complexity(self, subnet: dict) -> dict:
        """Score setup complexity (higher = easier setup)."""
        hw = subnet.get("hardware_min", {})
        has_repo = bool(subnet.get("repo_url"))
        has_docs = bool(subnet.get("docs_url"))

        score = 50  # Base

        if has_repo:
            score += 15
        if has_docs:
            score += 15
        if hw.get("gpu") == "not_needed":
            score += 10
        elif hw.get("gpu") == "optional":
            score += 5

        # Penalty for high hardware requirements
        if hw.get("vram_gb", 0) > 24:
            score -= 15
        elif hw.get("vram_gb", 0) > 16:
            score -= 5

        if hw.get("ram_gb", 16) > 64:
            score -= 10
        elif hw.get("ram_gb", 16) > 32:
            score -= 5

        score = max(0, min(100, score))

        return {
            "score": score,
            "reason": (
                f"Setup complexity: repo={'yes' if has_repo else 'no'}, "
                f"docs={'yes' if has_docs else 'no'}, gpu={hw.get('gpu', 'unknown')}"
            ),
        }

    def _score_documentation(self, subnet: dict) -> dict:
        """Score documentation quality."""
        has_repo = bool(subnet.get("repo_url"))
        has_docs = bool(subnet.get("docs_url"))
        name = subnet.get("name", "")

        # Well-known subnets get bonus for assumed docs
        well_known = ["Root", "Text Prompting", "Cortex.t"]
        is_well_known = any(wk in name for wk in well_known)

        score = 20  # Base for any subnet

        if has_repo:
            score += 30
        if has_docs:
            score += 30
        if is_well_known:
            score += 20

        score = min(100, score)

        return {
            "score": score,
            "reason": (
                f"Documentation: repo={'yes' if has_repo else 'no'}, "
                f"docs={'yes' if has_docs else 'no'}, "
                f"well_known={'yes' if is_well_known else 'no'}"
            ),
        }

    def _score_competition(self, subnet: dict) -> dict:
        """Score competition level (higher = less competition = better)."""
        netuid = subnet.get("netuid", 0)

        # Root subnet has highest competition
        if netuid == 0:
            return {"score": 10, "reason": "Root subnet - highest competition (validators only)"}

        # Popular subnets have more competition
        high_competition = [1, 4, 5, 18, 19]
        medium_competition = [7, 8, 9, 11, 12]

        if netuid in high_competition:
            return {"score": 30, "reason": f"Subnet {netuid} - high competition"}
        elif netuid in medium_competition:
            return {"score": 60, "reason": f"Subnet {netuid} - medium competition"}
        else:
            return {"score": 80, "reason": f"Subnet {netuid} - lower competition (opportunity)"}

    def _score_reward_realism(self, subnet: dict) -> dict:
        """Score reward realism based on category and demand."""
        category = subnet.get("category", "")
        netuid = subnet.get("netuid", 0)

        # Root has no miner rewards
        if netuid == 0:
            return {"score": 20, "reason": "Root subnet - no miner rewards (validator only)"}

        # Categories with proven demand
        high_demand = ["inference", "nlp", "vision", "audio"]
        medium_demand = ["data", "compute", "multimodal"]

        if category in high_demand:
            return {"score": 70, "reason": f"{category} has high demand - realistic rewards"}
        elif category in medium_demand:
            return {"score": 55, "reason": f"{category} has medium demand"}
        else:
            return {"score": 40, "reason": f"{category} demand uncertain - speculative"}

    def _score_maintenance(self, subnet: dict) -> dict:
        """Score maintenance burden (higher = lower burden = better)."""
        category = subnet.get("category", "")

        # Some categories require more maintenance
        high_maintenance = ["data", "infrastructure", "compute"]
        low_maintenance = ["governance"]

        if category in low_maintenance:
            return {"score": 85, "reason": f"{category} - low maintenance overhead"}
        elif category in high_maintenance:
            return {"score": 40, "reason": f"{category} - high maintenance overhead"}
        else:
            return {"score": 65, "reason": f"{category} - moderate maintenance"}

    def _score_security(self, subnet: dict) -> dict:
        """Score security posture."""
        has_repo = bool(subnet.get("repo_url"))
        is_active = subnet.get("active", True)
        netuid = subnet.get("netuid", 0)

        score = 50

        if has_repo:
            score += 20  # Open source = auditable
        if is_active:
            score += 20
        if netuid <= 12:
            score += 10  # Older subnets have more track record

        score = min(100, score)

        return {
            "score": score,
            "reason": (
                f"Security: active={'yes' if is_active else 'no'}, "
                f"open_source={'yes' if has_repo else 'no'}, "
                f"established={'yes' if netuid <= 12 else 'no'}"
            ),
        }

    def _score_learning_value(self, subnet: dict) -> dict:
        """Score learning/educational value."""
        category = subnet.get("category", "")

        high_learning = ["nlp", "vision", "multimodal", "reasoning", "inference"]
        medium_learning = ["audio", "data", "compute", "search"]

        if category in high_learning:
            return {"score": 80, "reason": f"{category} - excellent learning value"}
        elif category in medium_learning:
            return {"score": 65, "reason": f"{category} - good learning value"}
        else:
            return {"score": 50, "reason": f"{category} - moderate learning value"}

    def _score_long_term_potential(self, subnet: dict) -> dict:
        """Score long-term potential."""
        category = subnet.get("category", "")
        netuid = subnet.get("netuid", 0)

        high_potential = ["inference", "multimodal", "reasoning", "compute"]
        medium_potential = ["nlp", "vision", "audio", "data"]

        score = 50

        if category in high_potential:
            score += 30
        elif category in medium_potential:
            score += 15

        # Older subnets have proven staying power
        if netuid <= 12 and netuid > 0:
            score += 10

        score = min(100, score)

        return {
            "score": score,
            "reason": (
                f"Long-term: category={category}, "
                f"established={'yes' if netuid <= 12 else 'new'}"
            ),
        }

    def _generate_recommendations(self, scored_subnets: list[dict]) -> list[dict]:
        """
        Generate recommendations from scored subnets.

        Args:
            scored_subnets: List of scored subnet dictionaries

        Returns:
            List of recommendation dictionaries
        """
        recommendations: list[dict] = []

        top_subnet = scored_subnets[0] if scored_subnets else None
        if top_subnet and top_subnet["final_score"] >= 70:
            recommendations.append({
                "type": "top_recommendation",
                "subnet": top_subnet["name"],
                "netuid": top_subnet["netuid"],
                "score": top_subnet["final_score"],
                "message": (
                    f"Best match: {top_subnet['name']} (NetUID {top_subnet['netuid']}) "
                    f"with score {top_subnet['final_score']}"
                ),
            })

        recommended = [s for s in scored_subnets if s["recommendation"] == "RECOMMENDED"]
        if len(recommended) >= 2:
            recommendations.append({
                "type": "portfolio_suggestion",
                "count": len(recommended),
                "message": (
                    f"{len(recommended)} subnets score above 70 - consider "
                    f"a multi-subnet strategy"
                ),
                "subnets": [
                    {"name": s["name"], "netuid": s["netuid"], "score": s["final_score"]}
                    for s in recommended[:5]
                ],
            })

        if not recommended:
            conditional = [s for s in scored_subnets if s["recommendation"] == "CONDITIONAL"]
            if conditional:
                recommendations.append({
                    "type": "no_strong_match",
                    "message": (
                        "No subnets scored above 70. Consider conditional options "
                        "or upgrading hardware."
                    ),
                    "best_conditional": {
                        "name": conditional[0]["name"],
                        "netuid": conditional[0]["netuid"],
                        "score": conditional[0]["final_score"],
                    },
                })

        return recommendations
