"""
Tests for the enriched CUDA / GPU detection in
``SystemCheckAgent._get_gpu_info`` and ``_get_cuda_info``.

These tests mock ``subprocess.run`` so they don't need a real GPU,
nvidia-smi, or nvcc on the host. The legacy fields the
``hardware_profile_from_context`` adapter consumes (``available``,
``count``, ``vram_gb``, per-GPU ``vram_gb``) are pinned down so the
miner / validator agents can't silently break when the system_check
report shape evolves.
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from tao_swarm.agents._hardware import hardware_profile_from_context
from tao_swarm.agents.system_check_agent import SystemCheckAgent
from tao_swarm.orchestrator import AgentContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _completed(stdout: str = "", returncode: int = 0):
    """Build a fake CompletedProcess for subprocess.run mocks."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# Realistic nvidia-smi --query-gpu=index,name,driver_version,memory.total,
# memory.used,memory.free,compute_cap,temperature.gpu --format=csv,noheader,nounits
_TWO_GPU_OUTPUT = (
    "0, NVIDIA RTX 4090, 550.54.15, 24576, 1234, 23342, 8.9, 42\n"
    "1, NVIDIA A100, 550.54.15, 81920, 2048, 79872, 8.0, 51\n"
)

_ONE_GPU_OUTPUT = (
    "0, NVIDIA T4, 535.183.06, 15360, 256, 15104, 7.5, 38\n"
)

_NVIDIA_SMI_HEADER = """\
Wed Aug 21 12:34:56 2024
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 550.54.15              Driver Version: 550.54.15      CUDA Version: 12.4     |
+-----------------------------------------------------------------------------------------+
"""


# ---------------------------------------------------------------------------
# _get_gpu_info: nvidia-smi present, single + multi GPU
# ---------------------------------------------------------------------------

def _agent() -> SystemCheckAgent:
    return SystemCheckAgent({"use_mock_data": True})


def test_gpu_info_single_gpu_returns_full_per_device_dict():
    with patch("subprocess.run", return_value=_completed(_ONE_GPU_OUTPUT)):
        info = _agent()._get_gpu_info()
    assert info["available"] is True
    assert info["count"] == 1
    assert info["driver_version"] == "535.183.06"
    assert info["vram_gb"] == 15.0  # 15360 MB / 1024
    gpu = info["gpus"][0]
    assert gpu["index"] == 0
    assert gpu["name"] == "NVIDIA T4"
    assert gpu["vram_total_mb"] == 15360
    assert gpu["vram_used_mb"] == 256
    assert gpu["vram_free_mb"] == 15104
    assert gpu["compute_cap"] == "7.5"
    assert gpu["temperature_c"] == 38


def test_gpu_info_multi_gpu_sums_vram():
    with patch("subprocess.run", return_value=_completed(_TWO_GPU_OUTPUT)):
        info = _agent()._get_gpu_info()
    assert info["count"] == 2
    # 24576 + 81920 MB = 106496 → 104.0 GB
    assert info["vram_gb"] == 104.0
    names = [g["name"] for g in info["gpus"]]
    assert "NVIDIA RTX 4090" in names
    assert "NVIDIA A100" in names


def test_gpu_info_returns_legacy_per_gpu_vram_gb_for_adapter():
    """The hardware adapter reads gpu['gpus'][i]['vram_gb'] in some
    code paths — the new shape must keep that field present."""
    with patch("subprocess.run", return_value=_completed(_ONE_GPU_OUTPUT)):
        info = _agent()._get_gpu_info()
    assert "vram_gb" in info["gpus"][0]
    assert info["gpus"][0]["vram_gb"] == 15.0


# ---------------------------------------------------------------------------
# _get_gpu_info: nvidia-smi absent or returns nothing
# ---------------------------------------------------------------------------

def test_gpu_info_no_nvidia_smi_returns_empty_legacy_shape():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        info = _agent()._get_gpu_info()
    assert info == {"available": False, "count": 0, "gpus": [], "vram_gb": 0}


def test_gpu_info_nvidia_smi_returns_empty_output():
    with patch("subprocess.run", return_value=_completed("", returncode=0)):
        info = _agent()._get_gpu_info()
    assert info["available"] is False


def test_gpu_info_skips_unparseable_rows_silently():
    """Consumer GPUs sometimes report '[Not Supported]' for fields that
    enterprise SKUs report numerically. We must skip rows we can't
    parse rather than fabricating zero values."""
    bad = "0, RTX 3060, 535, [Not Supported], [Not Supported], [Not Supported], 8.6, 65\n"
    with patch("subprocess.run", return_value=_completed(bad)):
        info = _agent()._get_gpu_info()
    assert info["count"] == 0
    assert info["gpus"] == []


# ---------------------------------------------------------------------------
# _get_cuda_info: header parsing, nvcc, sources reporting
# ---------------------------------------------------------------------------

def test_cuda_info_parses_version_from_nvidia_smi_header():
    def fake_run(cmd, *args, **kwargs):
        if cmd[:1] == ["nvidia-smi"] and len(cmd) == 1:
            return _completed(_NVIDIA_SMI_HEADER)
        return _completed("", returncode=1)

    with patch("subprocess.run", side_effect=fake_run):
        info = _agent()._get_cuda_info()
    assert info["available"] is True
    assert info["version"] == "12.4"
    assert info["sources"]["nvidia_smi"] == "12.4"


def test_cuda_info_falls_back_to_nvcc_when_nvidia_smi_missing():
    def fake_run(cmd, *args, **kwargs):
        if cmd[:1] == ["nvidia-smi"]:
            raise FileNotFoundError
        if cmd[:1] == ["nvcc"]:
            return _completed(
                "nvcc: NVIDIA (R) Cuda compiler driver\n"
                "Copyright (c) 2005-2024 NVIDIA Corporation\n"
                "Built on Wed_Apr_17_19:19:55_PDT_2024\n"
                "Cuda compilation tools, release 12.4, V12.4.131"
            )
        return _completed("", returncode=1)

    with patch("subprocess.run", side_effect=fake_run):
        info = _agent()._get_cuda_info()
    assert info["available"] is True
    assert "release 12.4" in info["sources"]["nvcc"]


def test_cuda_info_reports_unavailable_when_nothing_works():
    def fake_run(cmd, *args, **kwargs):
        raise FileNotFoundError

    # Make sure torch is also unimportable for the duration of the test.
    import sys
    sentinel = object()
    saved = sys.modules.pop("torch", sentinel)
    sys.modules["torch"] = None  # type: ignore[assignment]
    try:
        with patch("subprocess.run", side_effect=fake_run):
            info = _agent()._get_cuda_info()
    finally:
        if saved is sentinel:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = saved  # type: ignore[assignment]

    assert info["available"] is False
    assert info["version"] is None
    assert info["sources"] == {}


# ---------------------------------------------------------------------------
# Hardware adapter picks up the new fields
# ---------------------------------------------------------------------------

def test_hardware_adapter_surfaces_compute_cap_and_driver_version():
    class _Stub:
        pass
    a = _Stub()
    ctx = AgentContext()
    ctx.publish("system_check_agent", {
        "hardware_report": {
            "cpu": {"cores": 16},
            "ram": {"total_gb": 64},
            "gpu": {
                "available": True,
                "count": 2,
                "driver_version": "550.54.15",
                "vram_gb": 104.0,
                "gpus": [
                    {"compute_cap": "8.9"},
                    {"compute_cap": "8.0"},
                ],
            },
        },
    })
    a.context = ctx

    profile = hardware_profile_from_context(a)
    assert profile["has_gpu"] is True
    assert profile["vram_gb"] == 104.0
    assert profile["gpu_count"] == 2
    assert profile["driver_version"] == "550.54.15"
    # Highest compute_cap across the two GPUs (string comparison
    # works correctly for the X.Y form on values < 10.x — fine for
    # current NVIDIA hardware).
    assert profile["best_compute_cap"] == "8.9"


def test_hardware_adapter_handles_missing_new_fields_gracefully():
    """A pre-CUDA-detection report (e.g. an old cached system_check
    output) must not break the adapter."""
    class _Stub:
        pass
    a = _Stub()
    ctx = AgentContext()
    ctx.publish("system_check_agent", {
        "hardware_report": {
            "cpu": {"cores": 4},
            "ram": {"total_gb": 8},
            "gpu": {"available": False, "vram_gb": 0},  # legacy shape
        },
    })
    a.context = ctx

    profile = hardware_profile_from_context(a)
    assert profile["gpu_count"] == 0
    assert profile["driver_version"] is None
    assert profile["best_compute_cap"] is None
