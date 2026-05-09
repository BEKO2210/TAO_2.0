"""
Shared helper for agents that consume ``system_check_agent``'s
hardware report from the orchestrator context bus.

The system check agent publishes its full report under
``system_check_agent.hardware_report`` with nested cpu/ram/gpu/disk
sub-dicts. Agents that reason about hardware (miner_engineering,
validator_engineering, …) want a flat profile with field names like
``ram_gb`` and ``has_gpu``. This translation lives here once instead
of being duplicated across every agent that needs it.
"""

from __future__ import annotations

from typing import Any


def hardware_profile_from_context(agent: Any) -> dict:
    """
    Pull a flat hardware profile from the agent's context bus.

    Looks up the most recent ``system_check_agent.hardware_report`` and
    adapts it to the field names hardware-aware agents expect:
    ``ram_gb``, ``has_gpu``, ``vram_gb``, ``cpu_cores``. Returns ``{}``
    when context isn't available or no report has been published — the
    caller is expected to fall back to whatever ``status="unknown"``
    path it already has.

    A ``_source`` tag is set on the returned dict so a downstream
    consumer (or a test) can tell where the values came from.
    """
    ctx = getattr(agent, "context", None)
    if ctx is None or not hasattr(ctx, "get"):
        return {}
    report = ctx.get("system_check_agent.hardware_report")
    if not isinstance(report, dict):
        return {}

    ram = report.get("ram") or {}
    gpu = report.get("gpu") or {}
    cpu = report.get("cpu") or {}

    # Pick the richest compute_cap available across the per-GPU list
    # (matters for ``training_experiment`` planning, where the most
    # capable card defines what models can run). Falls back to None if
    # the field wasn't reported (older nvidia-smi output, or no GPU).
    gpu_list = gpu.get("gpus") or []
    compute_caps = [g.get("compute_cap") for g in gpu_list if g.get("compute_cap")]
    best_compute_cap = max(compute_caps, default=None)

    return {
        "ram_gb": ram.get("total_gb", 0),
        "has_gpu": bool(gpu.get("available", False)),
        "vram_gb": gpu.get("vram_gb", 0),
        "cpu_cores": cpu.get("cores", 0),
        "gpu_count": gpu.get("count", 0),
        "driver_version": gpu.get("driver_version"),
        "best_compute_cap": best_compute_cap,
        "_source": "system_check_agent.hardware_report",
    }
