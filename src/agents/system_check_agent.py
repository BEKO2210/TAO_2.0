"""
System Check Agent (Agent 1).

Checks the system environment for Bittensor/TAO readiness.
Inspects hardware (CPU, RAM, GPU, VRAM, Disk) and software
(Python, Node, Docker, Git, CUDA) and produces readiness scores.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "system_check_agent"
AGENT_VERSION: str = "1.0.0"


class SystemCheckAgent:
    """
    Agent that checks system environment for Bittensor readiness.

    Inspects hardware capabilities (CPU, RAM, GPU, VRAM, Disk) and
    software dependencies (Python, Node, Docker, Git, CUDA). Produces
    a comprehensive readiness report with scores for mining,
    validation, and testnet participation.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the SystemCheckAgent.

        Args:
            config: Configuration dictionary with optional keys:
                - check_gpu: Whether to check GPU availability
                - check_docker: Whether to check Docker installation
                - min_ram_gb: Minimum RAM threshold (default 16)
                - min_disk_gb: Minimum disk space threshold (default 100)
        """
        self.config: dict = config
        self._check_gpu: bool = config.get("check_gpu", True)
        self._check_docker: bool = config.get("check_docker", True)
        self._min_ram_gb: int = config.get("min_ram_gb", 16)
        self._min_disk_gb: int = config.get("min_disk_gb", 100)
        self._status: str = "idle"
        self._last_check: dict[str, Any] | None = None
        logger.info(
            "SystemCheckAgent initialized (gpu=%s, docker=%s)",
            self._check_gpu, self._check_docker,
        )

    def run(self, task: dict) -> dict:
        """
        Run the system check.

        Args:
            task: Dictionary with optional 'params' for check customization

        Returns:
            Dictionary with hardware_report, software_report, and readiness_scores
        """
        self._status = "running"
        logger.info("SystemCheckAgent: starting system check")

        try:
            hardware_report = self._check_hardware()
            software_report = self._check_software()
            readiness_scores = self._compute_readiness(
                hardware_report, software_report
            )

            result = {
                "hardware_report": hardware_report,
                "software_report": software_report,
                "readiness_scores": readiness_scores,
                "overall_ready": all(
                    s["ready"] for s in readiness_scores.values()
                ),
            }

            self._last_check = result
            self._status = "complete"
            logger.info("SystemCheckAgent: check complete")
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("SystemCheckAgent: check failed: %s", e)
            raise

    def get_status(self) -> dict:
        """
        Get current agent status.

        Returns:
            Status dictionary with state, version, and last check info
        """
        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "status": self._status,
            "has_previous_check": self._last_check is not None,
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

    def _check_hardware(self) -> dict:
        """
        Check hardware resources.

        Returns:
            Hardware report dictionary
        """
        logger.info("Checking hardware...")

        # CPU
        cpu_count = os.cpu_count() or 1
        cpu_info = self._get_cpu_info()

        # RAM
        ram_info = self._get_ram_info()

        # GPU
        gpu_info = self._get_gpu_info() if self._check_gpu else {"checked": False}

        # Disk
        disk_info = self._get_disk_info()

        return {
            "cpu": {
                "cores": cpu_count,
                "architecture": platform.machine(),
                "processor": cpu_info,
                "ready": cpu_count >= 4,
            },
            "ram": {
                "total_gb": ram_info.get("total_gb", 0),
                "available_gb": ram_info.get("available_gb", 0),
                "ready": ram_info.get("total_gb", 0) >= self._min_ram_gb,
            },
            "gpu": gpu_info,
            "disk": {
                "total_gb": disk_info.get("total_gb", 0),
                "free_gb": disk_info.get("free_gb", 0),
                "ready": disk_info.get("free_gb", 0) >= self._min_disk_gb,
            },
        }

    def _check_software(self) -> dict:
        """
        Check installed software dependencies.

        Returns:
            Software report dictionary
        """
        logger.info("Checking software...")

        python_info = self._get_python_info()
        node_info = self._get_command_version("node", "--version")
        docker_info = self._get_docker_info() if self._check_docker else {"checked": False}
        git_info = self._get_command_version("git", "--version")
        cuda_info = self._get_cuda_info() if self._check_gpu else {"checked": False}

        return {
            "python": python_info,
            "node": node_info,
            "docker": docker_info,
            "git": git_info,
            "cuda": cuda_info,
        }

    def _compute_readiness(
        self, hardware: dict, software: dict
    ) -> dict:
        """
        Compute readiness scores for mining, validation, and testnet.

        Args:
            hardware: Hardware report
            software: Software report

        Returns:
            Readiness score dictionary
        """
        scores: dict[str, Any] = {}

        # Testnet readiness (lowest bar)
        testnet_score = 0
        testnet_checks = []

        if hardware["cpu"]["ready"]:
            testnet_score += 25
            testnet_checks.append("CPU sufficient")
        else:
            testnet_checks.append("CPU may be insufficient")

        if hardware["ram"]["ready"]:
            testnet_score += 25
            testnet_checks.append("RAM sufficient")
        else:
            testnet_checks.append("RAM may be insufficient")

        if software["python"]["installed"]:
            testnet_score += 25
            testnet_checks.append("Python available")
        else:
            testnet_checks.append("Python not found")

        if software["git"]["installed"]:
            testnet_score += 25
            testnet_checks.append("Git available")
        else:
            testnet_checks.append("Git not found")

        scores["testnet"] = {
            "score": testnet_score,
            "ready": testnet_score >= 75,
            "checks": testnet_checks,
        }

        # Miner readiness
        miner_score = testnet_score
        miner_checks = list(testnet_checks)

        if software["cuda"].get("available", False):
            miner_score += 10
            miner_checks.append("CUDA available for GPU mining")
        else:
            miner_checks.append("CUDA not available - CPU-only mining")

        if hardware["gpu"].get("available", False):
            miner_score += 10
            miner_checks.append("GPU detected")
        else:
            miner_checks.append("No GPU - may limit mining options")

        if hardware["disk"]["ready"]:
            miner_score += 10
            miner_checks.append("Disk space sufficient")
        else:
            miner_checks.append("Disk space may be insufficient")

        scores["miner"] = {
            "score": min(miner_score, 100),
            "ready": miner_score >= 70 and hardware["ram"]["ready"],
            "checks": miner_checks,
        }

        # Validator readiness (highest bar)
        validator_score = miner_score
        validator_checks = list(miner_checks)

        if hardware["ram"].get("total_gb", 0) >= 64:
            validator_score += 15
            validator_checks.append("RAM excellent for validation")
        elif hardware["ram"].get("total_gb", 0) >= 32:
            validator_score += 5
            validator_checks.append("RAM acceptable for validation")
        else:
            validator_checks.append("RAM below recommended for validation")

        if hardware["gpu"].get("vram_gb", 0) >= 16:
            validator_score += 15
            validator_checks.append("GPU VRAM excellent")
        elif hardware["gpu"].get("vram_gb", 0) >= 8:
            validator_score += 5
            validator_checks.append("GPU VRAM acceptable")
        else:
            validator_checks.append("GPU VRAM below recommended")

        if software["docker"].get("installed", False):
            validator_score += 5
            validator_checks.append("Docker available")
        else:
            validator_checks.append("Docker not available")

        scores["validator"] = {
            "score": min(validator_score, 100),
            "ready": (
                validator_score >= 80
                and hardware["ram"].get("total_gb", 0) >= 32
                and software["cuda"].get("available", False)
            ),
            "checks": validator_checks,
        }

        return scores

    def _get_cpu_info(self) -> str:
        """Get CPU information string."""
        try:
            if platform.system() == "Linux":
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if "model name" in line:
                            return line.split(":")[1].strip()
            return platform.processor() or "Unknown"
        except Exception as e:
            logger.debug("Could not read CPU info: %s", e)
            return platform.processor() or "Unknown"

    def _get_ram_info(self) -> dict:
        """Get RAM information."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return {
                "total_gb": round(mem.total / (1024 ** 3), 2),
                "available_gb": round(mem.available / (1024 ** 3), 2),
            }
        except ImportError:
            logger.debug("psutil not available, using fallback RAM check")
            try:
                result = subprocess.run(
                    ["free", "-g"],
                    capture_output=True, text=True, timeout=5,
                )
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    parts = lines[1].split()
                    if len(parts) >= 2:
                        return {
                            "total_gb": int(parts[1]),
                            "available_gb": int(parts[6]) if len(parts) > 6 else 0,
                        }
            except Exception as e2:
                logger.debug("Fallback RAM check failed: %s", e2)
        return {"total_gb": 0, "available_gb": 0}

    # nvidia-smi --query-gpu fields requested per device. Order matters —
    # the parser below indexes into the CSV row by position.
    _NVIDIA_SMI_FIELDS = (
        "index",
        "name",
        "driver_version",
        "memory.total",
        "memory.used",
        "memory.free",
        "compute_cap",
        "temperature.gpu",
    )

    def _get_gpu_info(self) -> dict:
        """
        Get rich per-device GPU information via ``nvidia-smi``.

        Returns a dict with the legacy fields ``available``, ``count``,
        ``gpus`` (list), and ``vram_gb`` (sum across GPUs) so the
        miner/validator hardware adapter keeps working unchanged. The
        per-GPU dicts now also carry ``index``, ``vram_used_mb``,
        ``vram_free_mb``, ``compute_cap``, and ``temperature_c``, plus a
        top-level ``driver_version`` for the whole machine — useful for
        diagnosing CUDA/driver mismatches without a separate query.
        """
        empty = {"available": False, "count": 0, "gpus": [], "vram_gb": 0}
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    f"--query-gpu={','.join(self._NVIDIA_SMI_FIELDS)}",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return empty

            gpus: list[dict] = []
            total_vram_mb = 0
            driver_version: str | None = None
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < len(self._NVIDIA_SMI_FIELDS):
                    continue
                idx, name, drv, vt, vu, vf, cc, temp = parts[:8]
                try:
                    vram_total_mb = int(vt)
                    vram_used_mb = int(vu)
                    vram_free_mb = int(vf)
                except ValueError:
                    # Some fields can come back as "[Not Supported]" on
                    # consumer cards. Skip rows we can't trust rather
                    # than reporting fabricated zeros.
                    continue
                gpus.append({
                    "index": int(idx) if idx.isdigit() else 0,
                    "name": name,
                    "vram_total_mb": vram_total_mb,
                    "vram_used_mb": vram_used_mb,
                    "vram_free_mb": vram_free_mb,
                    # Legacy field — sum into vram_gb below.
                    "vram_gb": round(vram_total_mb / 1024, 2),
                    "compute_cap": cc if cc and cc != "[Not Supported]" else None,
                    "temperature_c": int(temp) if temp.isdigit() else None,
                })
                total_vram_mb += vram_total_mb
                driver_version = drv  # same on every line

            return {
                "available": len(gpus) > 0,
                "count": len(gpus),
                "gpus": gpus,
                "driver_version": driver_version,
                "vram_gb": round(total_vram_mb / 1024, 2),
            }
        except FileNotFoundError:
            logger.debug("nvidia-smi not found - no NVIDIA GPU")
        except Exception as e:
            logger.debug("GPU check failed: %s", e)

        return {
            "available": False,
            "count": 0,
            "gpus": [],
            "vram_gb": 0,
        }

    def _get_disk_info(self) -> dict:
        """Get disk space information."""
        try:
            import shutil
            usage = shutil.disk_usage("/")
            return {
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "free_gb": round(usage.free / (1024 ** 3), 2),
            }
        except Exception as e:
            logger.debug("Disk check failed: %s", e)
            return {"total_gb": 0, "free_gb": 0}

    def _get_python_info(self) -> dict:
        """Get Python installation info."""
        version = f"{platform.python_version()}"
        return {
            "installed": True,
            "version": version,
            "path": shutil.which("python3") or shutil.which("python") or "unknown",
            "ready": True,
        }

    def _get_command_version(self, cmd: str, arg: str) -> dict:
        """Get version info for a command-line tool."""
        path = shutil.which(cmd)
        if not path:
            return {"installed": False, "version": None, "path": None, "ready": False}

        try:
            result = subprocess.run(
                [cmd, arg], capture_output=True, text=True, timeout=5,
            )
            version = result.stdout.strip() if result.returncode == 0 else "unknown"
            return {
                "installed": True,
                "version": version,
                "path": path,
                "ready": True,
            }
        except Exception as e:
            logger.debug("Version check failed for %s: %s", cmd, e)
            return {"installed": True, "version": "unknown", "path": path, "ready": True}

    def _get_docker_info(self) -> dict:
        """Get Docker installation info."""
        path = shutil.which("docker")
        if not path:
            return {"installed": False, "version": None, "path": None, "ready": False, "checked": True}

        try:
            result = subprocess.run(
                ["docker", "--version"], capture_output=True, text=True, timeout=5,
            )
            version = result.stdout.strip() if result.returncode == 0 else "unknown"
            return {
                "installed": True,
                "version": version,
                "path": path,
                "ready": True,
                "checked": True,
            }
        except Exception as e:
            logger.debug("Docker check failed: %s", e)
            return {"installed": True, "version": "unknown", "path": path, "ready": False, "checked": True}

    def _get_cuda_info(self) -> dict:
        """
        Get CUDA installation info.

        Detection order, most-authoritative first:

        1. ``nvidia-smi`` — parses the CUDA Version printed in the
           default header. This reports the **driver-installed** CUDA
           runtime, which is what the kernel will actually load.
        2. ``nvcc --version`` — reports the **toolkit** version, which
           may be older than the driver runtime if both are installed.
        3. ``torch.cuda.is_available()`` — last-resort fall-back for
           environments where only PyTorch ships with a bundled
           runtime (e.g. pip-installed wheels in a container).

        All three sources are reported when available so a downstream
        consumer can spot driver/toolkit mismatches.
        """
        sources: dict[str, Any] = {}
        version: str | None = None

        # 1) nvidia-smi default output carries "CUDA Version: 12.4"
        nv_version = self._cuda_version_from_nvidia_smi()
        if nv_version is not None:
            sources["nvidia_smi"] = nv_version
            version = nv_version

        # 2) nvcc toolkit
        try:
            result = subprocess.run(
                ["nvcc", "--version"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                # nvcc output's last informative line typically reads
                # "Cuda compilation tools, release 12.4, V12.4.131"
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                nvcc_line = next(
                    (l for l in lines if "release" in l.lower()),
                    lines[-1] if lines else "unknown",
                )
                sources["nvcc"] = nvcc_line
                version = version or nvcc_line
        except FileNotFoundError:
            logger.debug("nvcc not found")
        except Exception as e:
            logger.debug("nvcc check failed: %s", e)

        # 3) PyTorch fallback
        try:
            import torch  # type: ignore[import-not-found]
            if torch.cuda.is_available():
                pt_version = f"PyTorch CUDA {torch.version.cuda}"
                sources["pytorch"] = pt_version
                version = version or pt_version
        except ImportError:
            pass
        except Exception as e:  # pragma: no cover - torch import-time errors
            logger.debug("torch CUDA check failed: %s", e)

        available = bool(sources)
        return {
            "available": available,
            "version": version,
            "sources": sources,
            "ready": available,
        }

    @staticmethod
    def _cuda_version_from_nvidia_smi() -> str | None:
        """
        Parse the CUDA runtime version out of ``nvidia-smi``'s header.

        The default ``nvidia-smi`` invocation prints a banner like::

            +-----------------------------------------------------------+
            | NVIDIA-SMI 550.54.15  Driver Version: 550.54.15  CUDA Version: 12.4 |
            +-----------------------------------------------------------+

        Returns the matched version string or ``None`` if nvidia-smi
        isn't installed or the line wasn't found.
        """
        try:
            result = subprocess.run(
                ["nvidia-smi"], capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.debug("nvidia-smi (header) failed: %s", e)
            return None
        if result.returncode != 0:
            return None
        match = re.search(r"CUDA Version:\s*([\d.]+)", result.stdout)
        return match.group(1) if match else None
