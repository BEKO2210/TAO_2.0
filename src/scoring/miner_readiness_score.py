"""
Miner Readiness Scoring Algorithm

Assesses system readiness for running a Bittensor miner.
Checks: Hardware (CPU, RAM, GPU, Disk), Software (Python, Docker, Git),
and network connectivity.

Readiness levels: NOT_READY / PARTIAL / READY
"""

import logging
import os
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Hardware requirements by tier
HARDWARE_TIERS = {
    "minimum": {
        "cpu_cores": 4,
        "ram_gb": 16,
        "gpu_vram_gb": 0,  # CPU only
        "disk_gb": 100,
        "internet_mbps": 10,
    },
    "recommended": {
        "cpu_cores": 8,
        "ram_gb": 32,
        "gpu_vram_gb": 16,
        "disk_gb": 500,
        "internet_mbps": 50,
    },
    "optimal": {
        "cpu_cores": 16,
        "ram_gb": 64,
        "gpu_vram_gb": 40,
        "disk_gb": 1000,
        "internet_mbps": 100,
    },
}

# Software requirements
SOFTWARE_REQUIREMENTS = {
    "python": {"command": "python3", "min_version": "3.10", "check": "--version"},
    "git": {"command": "git", "min_version": "2.30", "check": "--version"},
    "docker": {"command": "docker", "min_version": "20.0", "check": "--version"},
    "pip": {"command": "pip3", "min_version": "22.0", "check": "--version"},
}


class MinerReadinessScorer:
    """
    Assesses system readiness for Bittensor miner operations.

    Checks hardware capabilities, software installations, and
    generates a readiness report with actionable feedback.
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Initialize the miner readiness scorer.

        Args:
            config: Optional configuration dict.
        """
        self.config = config or {}
        self.tier = self.config.get("hardware_tier", "recommended")
        self.requirements = HARDWARE_TIERS.get(self.tier, HARDWARE_TIERS["recommended"])

    # ── Hardware Checks ─────────────────────────────────────────────────────

    def _check_cpu(self) -> dict:
        """Check CPU information."""
        result = {"available": False, "cores": 0, "score": 0}
        try:
            cores = os.cpu_count()
            result["cores"] = cores or 0
            result["available"] = cores is not None and cores > 0

            # Try to get more info
            try:
                proc = subprocess.run(
                    ["lscpu"], capture_output=True, text=True, timeout=5
                )
                for line in proc.stdout.split("\n"):
                    if "Model name" in line:
                        result["model"] = line.split(":")[1].strip()
                    elif "CPU MHz" in line:
                        result["mhz"] = float(line.split(":")[1].strip())
                    elif "CPU max MHz" in line:
                        result["max_mhz"] = float(line.split(":")[1].strip())
            except Exception:
                pass

            # Score
            required = self.requirements["cpu_cores"]
            if result["cores"] >= required * 1.5:
                result["score"] = 100
            elif result["cores"] >= required:
                result["score"] = 75
            elif result["cores"] >= required * 0.5:
                result["score"] = 50
            else:
                result["score"] = 25

            result["meets_requirement"] = result["score"] >= 75

        except Exception as exc:
            logger.error("CPU check failed: %s", exc)
            result["error"] = str(exc)

        return result

    def _check_ram(self) -> dict:
        """Check RAM availability."""
        result = {"available": False, "total_gb": 0, "score": 0}
        try:
            # Try /proc/meminfo on Linux
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            result["total_gb"] = round(kb / 1024 / 1024, 2)
                            break
            else:
                # Fallback using psutil if available
                try:
                    import psutil

                    result["total_gb"] = round(psutil.virtual_memory().total / (1024 ** 3), 2)
                except ImportError:
                    result["total_gb"] = 0

            result["available"] = result["total_gb"] > 0

            required = self.requirements["ram_gb"]
            if result["total_gb"] >= required * 1.5:
                result["score"] = 100
            elif result["total_gb"] >= required:
                result["score"] = 75
            elif result["total_gb"] >= required * 0.5:
                result["score"] = 50
            else:
                result["score"] = 25

            result["meets_requirement"] = result["score"] >= 75

        except Exception as exc:
            logger.error("RAM check failed: %s", exc)
            result["error"] = str(exc)

        return result

    def _check_gpu(self) -> dict:
        """Check GPU availability."""
        result = {
            "available": False,
            "devices": [],
            "total_vram_gb": 0,
            "score": 0,
        }

        # Try nvidia-smi
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            try:
                proc = subprocess.run(
                    [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                for line in proc.stdout.strip().split("\n"):
                    if line:
                        parts = line.split(",")
                        if len(parts) >= 2:
                            name = parts[0].strip()
                            mem_str = parts[1].strip()
                            # Parse memory (MiB)
                            mem_mb = 0
                            if "MiB" in mem_str:
                                mem_mb = int(mem_str.replace("MiB", "").strip())
                            elif "MB" in mem_str:
                                mem_mb = int(mem_str.replace("MB", "").strip())
                            mem_gb = round(mem_mb / 1024, 2)
                            result["devices"].append({"name": name, "vram_gb": mem_gb})
                            result["total_vram_gb"] += mem_gb

                result["available"] = len(result["devices"]) > 0

            except Exception as exc:
                logger.debug("nvidia-smi check failed: %s", exc)

        # If no GPU found, check for CPU-only mode
        if not result["available"]:
            # Check if CUDA is available via PyTorch
            try:
                import torch

                if torch.cuda.is_available():
                    for i in range(torch.cuda.device_count()):
                        name = torch.cuda.get_device_name(i)
                        mem = torch.cuda.get_device_properties(i).total_memory
                        mem_gb = round(mem / (1024 ** 3), 2)
                        result["devices"].append({"name": name, "vram_gb": mem_gb})
                        result["total_vram_gb"] += mem_gb
                    result["available"] = True
            except ImportError:
                pass

        # Score GPU
        required = self.requirements["gpu_vram_gb"]
        if required == 0:
            # CPU-only mode is acceptable
            if result["available"]:
                result["score"] = 100  # GPU available even though not required = bonus
            else:
                result["score"] = 100  # CPU only is fine
        else:
            if result["total_vram_gb"] >= required * 1.5:
                result["score"] = 100
            elif result["total_vram_gb"] >= required:
                result["score"] = 75
            elif result["total_vram_gb"] >= required * 0.5:
                result["score"] = 40
            else:
                result["score"] = 10

        result["meets_requirement"] = result["score"] >= 75
        return result

    def _check_disk(self) -> dict:
        """Check disk space."""
        result = {"available": False, "total_gb": 0, "free_gb": 0, "score": 0}
        try:
            stat = shutil.disk_usage("/")
            result["total_gb"] = round(stat.total / (1024 ** 3), 2)
            result["free_gb"] = round(stat.free / (1024 ** 3), 2)
            result["available"] = True

            required = self.requirements["disk_gb"]
            if result["free_gb"] >= required * 2:
                result["score"] = 100
            elif result["free_gb"] >= required:
                result["score"] = 75
            elif result["free_gb"] >= required * 0.5:
                result["score"] = 50
            else:
                result["score"] = 25

            result["meets_requirement"] = result["score"] >= 75

        except Exception as exc:
            logger.error("Disk check failed: %s", exc)
            result["error"] = str(exc)

        return result

    # ── Software Checks ─────────────────────────────────────────────────────

    def _check_software(self) -> dict:
        """Check all required software installations."""
        results = {}
        for name, req in SOFTWARE_REQUIREMENTS.items():
            results[name] = self._check_single_software(name, req)

        return results

    def _check_single_software(self, name: str, req: dict) -> dict:
        """Check a single software installation."""
        result = {"installed": False, "version": "", "score": 0}
        command = req["command"]
        check_flag = req["check"]

        # Find command
        cmd_path = shutil.which(command)
        if not cmd_path:
            # Try alternative
            alt_command = command.replace("3", "") if "3" in command else command + "3"
            cmd_path = shutil.which(alt_command)
            if cmd_path:
                command = alt_command

        if not cmd_path:
            result["score"] = 0
            result["meets_requirement"] = False
            return result

        try:
            proc = subprocess.run(
                [command, check_flag],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = (proc.stdout + proc.stderr).strip()
            result["installed"] = True
            result["version"] = output

            # Parse version
            version_str = self._extract_version(output)
            result["parsed_version"] = version_str

            min_version = req["min_version"]
            if version_str and self._version_gte(version_str, min_version):
                result["score"] = 100
            else:
                result["score"] = 50  # Installed but version may be old

            result["meets_requirement"] = result["score"] >= 75

        except Exception as exc:
            logger.debug("Software check failed for %s: %s", name, exc)
            result["error"] = str(exc)
            result["score"] = 0

        return result

    @staticmethod
    def _extract_version(output: str) -> str:
        """Extract version string from command output."""
        import re

        # Common patterns: "version 1.2.3", "v1.2.3", "1.2.3"
        patterns = [
            r"version\s+v?(\d+\.\d+(?:\.\d+)?)",
            r"v?(\d+\.\d+(?:\.\d+)?)",
        ]
        for pat in patterns:
            match = re.search(pat, output, re.IGNORECASE)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _version_gte(version: str, min_version: str) -> bool:
        """Check if version >= min_version."""
        try:
            v_parts = [int(x) for x in version.split(".")[:2]]
            m_parts = [int(x) for x in min_version.split(".")[:2]]
            for v, m in zip(v_parts, m_parts):
                if v > m:
                    return True
                if v < m:
                    return False
            return len(v_parts) >= len(m_parts)
        except (ValueError, IndexError):
            return False

    # ── Composite Readiness ─────────────────────────────────────────────────

    def calculate_readiness(self, system_info: dict = None) -> dict:
        """
        Calculate overall miner readiness score.

        Args:
            system_info: Optional system info dict to override auto-detection.

        Returns:
            Comprehensive readiness report.
        """
        if system_info:
            # Use provided system info
            hardware = system_info.get("hardware", {})
            software = system_info.get("software", {})
            cpu = hardware.get("cpu", {})
            ram = hardware.get("ram", {})
            gpu = hardware.get("gpu", {})
            disk = hardware.get("disk", {})
        else:
            # Auto-detect
            cpu = self._check_cpu()
            ram = self._check_ram()
            gpu = self._check_gpu()
            disk = self._check_disk()
            software = self._check_software()

        hardware_scores = {
            "cpu": cpu.get("score", 0),
            "ram": ram.get("score", 0),
            "gpu": gpu.get("score", 0),
            "disk": disk.get("score", 0),
        }

        software_scores = {
            name: info.get("score", 0)
            for name, info in software.items()
        }

        # Hardware average (GPU is optional if tier allows)
        hw_weights = {"cpu": 0.25, "ram": 0.25, "gpu": 0.25, "disk": 0.25}
        hw_avg = sum(hardware_scores[k] * hw_weights[k] for k in hw_weights)

        # Software average
        sw_avg = sum(software_scores.values()) / max(len(software_scores), 1)

        # Total score
        total = hw_avg * 0.6 + sw_avg * 0.4
        total = round(total, 2)

        # Readiness level
        level = self._get_readiness_level(total)

        return {
            "total_score": total,
            "level": level,
            "tier_checked": self.tier,
            "hardware": {
                "cpu": cpu,
                "ram": ram,
                "gpu": gpu,
                "disk": disk,
                "average": round(hw_avg, 2),
                "scores": hardware_scores,
            },
            "software": {
                "details": software,
                "average": round(sw_avg, 2),
                "scores": software_scores,
            },
            "requirements": self.requirements,
        }

    def get_missing_requirements(self) -> list:
        """
        Get list of missing requirements.

        Returns:
            List of strings describing what's missing or insufficient.
        """
        readiness = self.calculate_readiness()
        missing = []

        hw = readiness.get("hardware", {})
        for component in ["cpu", "ram", "gpu", "disk"]:
            info = hw.get(component, {})
            if not info.get("meets_requirement", False):
                missing.append(
                    f"{component.upper()}: score={info.get('score', 0)}, "
                    f"required={self.requirements.get(f'{component}_gb' if component != 'cpu' else f'{component}_cores', 'N/A')}"
                )

        sw = readiness.get("software", {}).get("details", {})
        for name, info in sw.items():
            if not info.get("meets_requirement", False):
                missing.append(
                    f"{name}: {'not installed' if not info.get('installed') else 'version too old'}"
                )

        return missing

    def _get_readiness_level(self, score: float) -> str:
        """Convert score to readiness level."""
        if score >= 80:
            return "READY"
        elif score >= 50:
            return "PARTIAL"
        return "NOT_READY"
