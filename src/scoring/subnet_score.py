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
import math
import os
import sqlite3
import time

logger = logging.getLogger(__name__)

# Criterion weights (must sum to 1.0)
CRITERIA_WEIGHTS = {
    # Personal-fit criteria (kept for backward compat — these reflect
    # "is this subnet a good fit for ME?" rather than absolute subnet
    # quality. The online research flagged them as subjective; we
    # reduced their combined weight from 90% → 50% to make room for
    # the chain-derived signals below.)
    "technical_fit": 0.08,
    "hardware_fit": 0.08,
    "setup_complexity": 0.05,
    "doc_quality": 0.06,
    "competition": 0.07,
    "reward_realism": 0.06,
    "maintenance": 0.05,
    "security_risk": 0.03,
    "learning_value": 0.01,
    "long_term": 0.01,
    # Chain-derived quality criteria (added per online research,
    # 2025-2026 Bittensor-specific subnet analytics). These read
    # from the live metagraph + dynamic info + owner activity, so
    # they only fire when the caller provides chain data (graceful
    # 50 default otherwise).
    "taoflow_health": 0.15,             # net stake flow EMA (Taoflow)
    "validator_concentration": 0.10,    # 1 - HHI on validator stake
    "weight_consensus_divergence": 0.10,  # 1 - mean pairwise weight cosine
    "miner_slot_liveness": 0.08,        # active / registered miner ratio
    "owner_liveness": 0.07,             # owner activity decay (commits + hparam)
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

    def __init__(self, config: dict | None = None) -> None:
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

    # ── Chain-derived criteria (per online research) ────────────────────────

    @staticmethod
    def _chain_section(data: dict, key: str) -> dict:
        """Look up a chain-data section under ``data[key]`` or, for
        consistency with the existing personal-fit scorers,
        ``data['profile'][key]``. Returns ``{}`` for either-missing."""
        d = data or {}
        section = d.get(key)
        if not section:
            section = (d.get("profile") or {}).get(key)
        return section or {}

    def score_taoflow_health(self, data: dict) -> float:
        """
        Score the subnet's net TAO staking flow (post-Nov 2025 Taoflow
        emission regime — flow drives emission share).

        Reads from ``data['taoflow']``:
          - ``net_flow_30d``: net stake delta over 30 days, in TAO
          - ``share_of_emission_pct``: 0..100, optional rank signal

        Persistent negative flow = automatic 0. Positive flow scores
        proportionally to the share of emission. Falls back to 50
        ("unknown") when no flow data is provided.
        """
        flow = self._chain_section(data, "taoflow")
        if not flow:
            return 50.0
        net = float(flow.get("net_flow_30d", 0))
        if net < 0:
            return 0.0
        share = float(flow.get("share_of_emission_pct", 0.0))
        # Top decile (>= 1.5% of total emission, rough top-10-of-90+) → 100
        # Below 0.1% → ~30
        if share <= 0:
            return 50.0  # we have flow but no rank yet — neutral
        score = 30.0 + min(70.0, share * 47.0)  # 1.5% share → 100
        return max(0.0, min(100.0, score))

    def score_validator_concentration(self, data: dict) -> float:
        """
        Score validator-stake concentration on the subnet.

        Reads from ``data['metagraph']['neurons']`` — picks neurons
        with ``validator_permit=True``, computes HHI on their stake
        share, returns ``100 * (1 - HHI)`` clamped. HHI < 0.1 → 100,
        HHI > 0.5 → 10. The arXiv 2507.02951 paper found median
        validator-stake Gini = 0.977 across 64 subnets, so this
        criterion captures real cross-subnet variation.
        """
        mg = self._chain_section(data, "metagraph")
        neurons = mg.get("neurons") or []
        validators = [n for n in neurons if n.get("validator_permit")]
        if len(validators) < 2:
            return 50.0  # Not enough data — neutral
        stakes = [float(n.get("stake", 0)) for n in validators]
        total = sum(stakes)
        if total <= 0:
            return 50.0
        shares = [s / total for s in stakes]
        hhi = sum(sh * sh for sh in shares)
        # HHI ranges from 1/n (perfectly even) to 1 (single validator).
        # Map: HHI = 0.1 → ~90, HHI = 0.5 → ~50, HHI = 1.0 → 0
        return max(0.0, min(100.0, round(100.0 * (1.0 - hhi), 2)))

    def score_weight_consensus_divergence(self, data: dict) -> float:
        """
        Score how much validators' weight vectors disagree with each
        other. High mean pairwise cosine similarity ≈ weight copying
        / monoculture (the Opentensor weight-copier paper).

        Reads from ``data['metagraph']`` — when ``weights`` (V × N
        matrix) is present, compute mean off-diagonal cosine
        similarity; lower = healthier. Apply a +20 bonus when the
        subnet has commit-reveal enabled
        (``data['hyperparameters']['commit_reveal_weights_enabled']``).

        Falls back to 50 when the weight matrix wasn't pulled (the
        cheap ``metagraph(lite=True)`` path skips it on purpose).
        """
        mg = self._chain_section(data, "metagraph")
        weights = mg.get("weights")
        if not weights:
            return 50.0
        # weights: list of lists (V x N) of floats
        rows = [list(w) for w in weights if w]
        if len(rows) < 2:
            return 50.0
        # Compute pairwise cosine similarity, average off-diagonal.
        sims: list[float] = []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if len(a) != len(b):
                    continue
                dot = sum(x * y for x, y in zip(a, b))
                norm_a = math.sqrt(sum(x * x for x in a))
                norm_b = math.sqrt(sum(y * y for y in b))
                if norm_a == 0 or norm_b == 0:
                    continue
                sims.append(dot / (norm_a * norm_b))
        if not sims:
            return 50.0
        mean_sim = sum(sims) / len(sims)
        # Map: mean_sim = 0.6 → 100, 0.95 → 0
        if mean_sim < 0.6:
            score = 100.0
        elif mean_sim > 0.95:
            score = 0.0
        else:
            score = 100.0 * (1.0 - (mean_sim - 0.6) / 0.35)
        # Bonus for commit-reveal
        hparams = self._chain_section(data, "hyperparameters")
        if hparams.get("commit_reveal_weights_enabled"):
            score += 20.0
        return max(0.0, min(100.0, round(score, 2)))

    def score_miner_slot_liveness(self, data: dict) -> float:
        """
        Score the ratio of *active* miners to *registered* miner UIDs.

        A subnet where slots are squatted by inactive UIDs is
        capturing emissions for zombies — bad for new miners and a
        red flag for subnet health.

        Reads from ``data['metagraph']['neurons']`` (with
        ``validator_permit=False`` filter), computes the share with
        non-zero ``incentive`` AND recent ``last_update_block``
        (within ``activity_cutoff`` blocks of ``current_block``).
        """
        mg = self._chain_section(data, "metagraph")
        neurons = mg.get("neurons") or []
        miners = [n for n in neurons if not n.get("validator_permit")]
        if not miners:
            return 50.0
        current_block = int(mg.get("block", 0)) or int(
            (data or {}).get("current_block", 0)
            or (data or {}).get("profile", {}).get("current_block", 0)
        )
        cutoff = int(self._chain_section(data, "hyperparameters").get(
            "activity_cutoff", 5_000
        ))
        active = 0
        for m in miners:
            if float(m.get("incentive", 0)) <= 0:
                continue
            last = int(m.get("last_update_block", 0))
            if current_block and (current_block - last) > cutoff:
                continue
            active += 1
        ratio = active / len(miners)
        return round(100.0 * ratio, 2)

    def score_owner_liveness(self, data: dict) -> float:
        """
        Score how recently the subnet owner has been active —
        commits, hyperparameter changes, weight-setting extrinsics.

        Reads from ``data['owner']``:
          - ``days_since_last_commit``: int
          - ``days_since_last_hparam_change``: int

        Composite: ``100 - min(100, commit_days + hparam_days/2)``.
        Below 30 → likely abandoned subnet still drawing emissions.
        Falls back to 50 when no owner data is present.
        """
        owner = self._chain_section(data, "owner")
        if not owner:
            return 50.0
        commit_days = float(owner.get("days_since_last_commit", 365))
        hparam_days = float(owner.get("days_since_last_hparam_change", 365))
        decay = commit_days + hparam_days / 2.0
        score = 100.0 - min(100.0, decay)
        return max(0.0, round(score, 2))

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

        # Score all criteria — the original 10 personal-fit metrics
        # plus the 5 chain-derived quality criteria added per the
        # online research. Chain criteria default to 50 ("unknown")
        # when the caller didn't pass metagraph / taoflow / owner
        # data, so existing callers keep working.
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
            "taoflow_health": self.score_taoflow_health(subnet_data),
            "validator_concentration": self.score_validator_concentration(subnet_data),
            "weight_consensus_divergence": self.score_weight_consensus_divergence(subnet_data),
            "miner_slot_liveness": self.score_miner_slot_liveness(subnet_data),
            "owner_liveness": self.score_owner_liveness(subnet_data),
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
