"""
Validator Readiness Scoring Algorithm

Assesses system and financial readiness for running a Bittensor validator.
Checks: Hardware, Software, Stake requirements, and uptime capability.

Readiness levels: NOT_READY / PARTIAL / READY
"""

import logging
import shutil
import subprocess
from typing import Optional

from .miner_readiness_score import HARDWARE_TIERS, SOFTWARE_REQUIREMENTS, MinerReadinessScorer

logger = logging.getLogger(__name__)

# Validator-specific hardware requirements (stricter than miner)
VALIDATOR_TIERS = {
    "minimum": {
        "cpu_cores": 8,
        "ram_gb": 32,
        "gpu_vram_gb": 0,
        "disk_gb": 500,
        "internet_mbps": 50,
        "uptime_pct": 95,
    },
    "recommended": {
        "cpu_cores": 16,
        "ram_gb": 64,
        "gpu_vram_gb": 24,
        "disk_gb": 1000,
        "internet_mbps": 100,
        "uptime_pct": 99,
    },
    "optimal": {
        "cpu_cores": 32,
        "ram_gb": 128,
        "gpu_vram_gb": 80,
        "disk_gb": 2000,
        "internet_mbps": 500,
        "uptime_pct": 99.9,
    },
}

# Minimum stake recommendations by subnet (approximate)
STAKE_RECOMMENDATIONS = {
    "default": {"minimum": 100, "recommended": 1000, "optimal": 10000},
    1: {"minimum": 1000, "recommended": 10000, "optimal": 100000},  # Root = high
    2: {"minimum": 50, "recommended": 500, "optimal": 5000},
    3: {"minimum": 10, "recommended": 100, "optimal": 1000},
}


class ValidatorReadinessScorer:
    """
    Assesses readiness for Bittensor validator operations.

    Combines hardware checks, software checks, and stake requirement analysis.
    Provides stake recommendations and readiness level classification.
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Initialize the validator readiness scorer.

        Args:
            config: Optional configuration with:
                - 'hardware_tier': minimum/recommended/optimal
                - 'stake_tao': Current available stake in TAO
                - 'target_subnet': Target subnet netuid
        """
        self.config = config or {}
        self.tier = self.config.get("hardware_tier", "recommended")
        self.stake_tao = self.config.get("stake_tao", 0)
        self.target_subnet = self.config.get("target_subnet", None)
        self.requirements = VALIDATOR_TIERS.get(self.tier, VALIDATOR_TIERS["recommended"])

    # ── Hardware Checks ─────────────────────────────────────────────────────

    def _check_hardware(self) -> dict:
        """Run hardware checks using miner scorer as base."""
        miner_scorer = MinerReadinessScorer({"hardware_tier": self.tier})

        cpu = miner_scorer._check_cpu()
        ram = miner_scorer._check_ram()
        gpu = miner_scorer._check_gpu()
        disk = miner_scorer._check_disk()

        # Override scores with validator requirements (stricter)
        hardware_scores = {}
        for component, check, key in [
            ("cpu", cpu, "cpu_cores"),
            ("ram", ram, "ram_gb"),
            ("gpu", gpu, "gpu_vram_gb"),
            ("disk", disk, "disk_gb"),
        ]:
            required = self.requirements[key]
            actual = check.get("cores" if key == "cpu_cores" else
                              "total_gb" if key in ("ram_gb", "gpu_vram_gb") else
                              "free_gb" if key == "disk_gb" else 0, 0)

            if key == "cpu_cores":
                actual = check.get("cores", 0)
            elif key == "ram_gb":
                actual = check.get("total_gb", 0)
            elif key == "gpu_vram_gb":
                actual = check.get("total_vram_gb", 0)
            else:
                actual = check.get("free_gb", 0)

            if actual >= required * 1.5:
                check["score"] = 100
            elif actual >= required:
                check["score"] = 75
            elif actual >= required * 0.5:
                check["score"] = 40
            else:
                check["score"] = 10

            check["meets_requirement"] = check["score"] >= 75
            hardware_scores[component] = check["score"]

        return {
            "cpu": cpu,
            "ram": ram,
            "gpu": gpu,
            "disk": disk,
            "scores": hardware_scores,
            "average": round(sum(hardware_scores.values()) / len(hardware_scores), 2),
        }

    # ── Software Checks ─────────────────────────────────────────────────────

    def _check_software(self) -> dict:
        """Check software requirements."""
        miner_scorer = MinerReadinessScorer({"hardware_tier": self.tier})
        software = miner_scorer._check_software()

        scores = {name: info.get("score", 0) for name, info in software.items()}
        avg = sum(scores.values()) / max(len(scores), 1)

        return {
            "details": software,
            "scores": scores,
            "average": round(avg, 2),
        }

    # ── Stake Checks ────────────────────────────────────────────────────────

    def _check_stake(self) -> dict:
        """Check stake requirements."""
        rec = STAKE_RECOMMENDATIONS.get(
            self.target_subnet, STAKE_RECOMMENDATIONS["default"]
        )

        minimum = rec["minimum"]
        recommended = rec["recommended"]
        optimal = rec["optimal"]

        if self.stake_tao >= optimal:
            score = 100
            level = "optimal"
        elif self.stake_tao >= recommended:
            score = 75
            level = "recommended"
        elif self.stake_tao >= minimum:
            score = 50
            level = "minimum"
        elif self.stake_tao > 0:
            score = 25
            level = "below_minimum"
        else:
            score = 0
            level = "no_stake"

        return {
            "score": score,
            "level": level,
            "available": self.stake_tao,
            "minimum_required": minimum,
            "recommended": recommended,
            "optimal": optimal,
            "meets_requirement": score >= 50,
            "deficit": max(0, minimum - self.stake_tao),
        }

    def get_stake_recommendation(self) -> str:
        """
        Get stake recommendation message.

        Returns:
            Human-readable recommendation string.
        """
        rec = STAKE_RECOMMENDATIONS.get(
            self.target_subnet, STAKE_RECOMMENDATIONS["default"]
        )
        minimum = rec["minimum"]
        recommended = rec["recommended"]

        if self.stake_tao == 0:
            return (
                f"No stake available. Minimum {minimum} TAO required for subnet "
                f"{self.target_subnet or 'default'}. Recommended: {recommended} TAO."
            )
        elif self.stake_tao < minimum:
            deficit = minimum - self.stake_tao
            return (
                f"Stake too low: {self.stake_tao:.2f} TAO available, "
                f"{minimum} TAO minimum required (deficit: {deficit:.2f} TAO)."
            )
        elif self.stake_tao < recommended:
            return (
                f"Stake sufficient for minimum ({self.stake_tao:.2f} TAO >= {minimum} TAO), "
                f"but below recommended ({recommended} TAO)."
            )
        else:
            return (
                f"Stake level good: {self.stake_tao:.2f} TAO "
                f"(recommended: {recommended} TAO)."
            )

    # ── Uptime Check ────────────────────────────────────────────────────────

    def _check_uptime(self) -> dict:
        """Check system uptime capability."""
        result = {"score": 50, "current_uptime_hours": 0}

        # Check current system uptime
        try:
            with open("/proc/uptime") as f:
                uptime_seconds = float(f.readline().split()[0])
                result["current_uptime_hours"] = round(uptime_seconds / 3600, 2)
        except Exception:
            pass

        # Check if systemd is available (suggests proper service management)
        systemd = shutil.which("systemctl")
        if systemd:
            result["has_systemd"] = True
            result["score"] += 20
        else:
            result["has_systemd"] = False

        # Check for screen/tmux (basic session persistence)
        screen = shutil.which("screen")
        tmux = shutil.which("tmux")
        if screen or tmux:
            result["has_session_manager"] = True
            result["score"] += 10
        else:
            result["has_session_manager"] = False

        # Check for docker (containerized deployment)
        docker = shutil.which("docker")
        if docker:
            result["has_docker"] = True
            result["score"] += 10
        else:
            result["has_docker"] = False

        result["meets_requirement"] = result["score"] >= 75
        return result

    # ── Composite Readiness ─────────────────────────────────────────────────

    def calculate_readiness(self, system_info: dict = None, stake_info: dict = None) -> dict:
        """
        Calculate overall validator readiness.

        Args:
            system_info: Optional system info to override auto-detection.
            stake_info: Optional stake info dict with 'stake_tao' key.

        Returns:
            Comprehensive readiness report.
        """
        if system_info:
            # Use provided data
            hardware = system_info.get("hardware", {})
            software = system_info.get("software", {})
            stake = stake_info or system_info.get("stake", {})

            hw_avg = sum(
                hardware.get(c, {}).get("score", 0)
                for c in ["cpu", "ram", "gpu", "disk"]
            ) / 4

            sw_scores = software if isinstance(software, dict) else {}
            sw_avg = sum(sw_scores.values()) / max(len(sw_scores), 1)

            stake_score = stake.get("score", 0) if isinstance(stake, dict) else 0
        else:
            hardware = self._check_hardware()
            software = self._check_software()
            stake = self._check_stake()
            uptime = self._check_uptime()

            hw_avg = hardware["average"]
            sw_avg = software["average"]
            stake_score = stake["score"]

        # Weighted total
        # Hardware: 30%, Software: 20%, Stake: 40%, Uptime: 10%
        total = hw_avg * 0.30 + sw_avg * 0.20 + stake_score * 0.40
        if not system_info:
            total += uptime["score"] * 0.10

        total = round(total, 2)
        level = self._get_readiness_level(total)

        result = {
            "total_score": total,
            "level": level,
            "tier_checked": self.tier,
            "target_subnet": self.target_subnet,
            "hardware": hardware if not system_info else hardware,
            "software": software if not system_info else {"scores": software, "average": sw_avg},
            "stake": stake if not system_info else stake,
            "readiness_level": level,
            "stake_recommendation": self.get_stake_recommendation(),
        }

        if not system_info:
            result["uptime"] = uptime

        return result

    def _get_readiness_level(self, score: float) -> str:
        """Convert score to readiness level."""
        if score >= 80:
            return "READY"
        elif score >= 50:
            return "PARTIAL"
        return "NOT_READY"
