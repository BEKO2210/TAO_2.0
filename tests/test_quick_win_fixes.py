"""
Regression tests for the quick-win fixes:

* B1 — ``training_experiment_agent`` raised ``KeyError: 'estimated_time'``
  because the consumer in ``_create_training_plan`` looked up a key that
  ``_estimate_hardware`` does not produce. Fix: read ``estimated_time_hours``
  and format it as a string.

* L1/L2 — ``SwarmOrchestrator.execute_task`` returned the ``Classification``
  enum object in its result dict and embedded it in a plan-note f-string,
  so the user-facing note read "This is a Classification.DANGER action."
  Fix: use ``classification.value`` everywhere it crosses an output boundary.
"""

from __future__ import annotations

import json

from src.agents.training_experiment_agent import TrainingExperimentAgent
from src.orchestrator import SwarmOrchestrator
from src.orchestrator.approval_gate import Classification

# ---------------------------------------------------------------------------
# B1 — TrainingExperimentAgent must run end-to-end without raising
# ---------------------------------------------------------------------------

def test_training_experiment_plan_runs_without_keyerror():
    agent = TrainingExperimentAgent({"use_mock_data": True})
    out = agent.run({"type": "training_plan", "params": {"action": "plan"}})
    assert isinstance(out, dict)
    assert out["status"] == "plan_created"
    assert "training_plan" in out
    steps = out["training_plan"]["steps"]
    training_step = next(s for s in steps if s["title"] == "Training")
    # Must be a non-empty human-readable string, not a missing key
    assert isinstance(training_step["estimated_time"], str)
    assert "hour" in training_step["estimated_time"]


def test_training_experiment_plan_carries_hw_estimate_keys():
    agent = TrainingExperimentAgent({"use_mock_data": True})
    out = agent.run({"type": "training_plan",
                     "params": {"action": "plan", "model_name": "bert-base"}})
    hw = out["hardware_estimate"]
    # The producing helper returns *_hours; the bug was the consumer reading
    # 'estimated_time' instead. Lock both names down.
    assert "estimated_time_hours" in hw
    assert "estimated_time" not in hw


# ---------------------------------------------------------------------------
# L1 / L2 — classification must be a plain string everywhere it leaves
# the orchestrator, and the plan-note f-string must not show "Classification."
# ---------------------------------------------------------------------------

def test_blocked_result_classification_is_plain_string():
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    out = orch.execute_task({"type": "execute_trade", "amount": 100})

    assert out["status"] == "blocked"
    cls = out["classification"]
    assert cls == "DANGER"
    # The exact type matters for downstream JSON consumers — must be a plain
    # string, not a Classification enum instance.
    assert type(cls) is str


def test_blocked_plan_note_is_human_readable():
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    out = orch.execute_task({"type": "sign_transaction", "tx": "0xabc"})

    note = out["output"]["note"]
    assert "DANGER" in note
    # Was: "This is a Classification.DANGER action."
    assert "Classification.DANGER" not in note
    assert "Classification" not in note


def test_success_result_classification_is_plain_string():
    """Even on the happy path, classification must serialize cleanly."""
    from src.agents import SystemCheckAgent

    orch = SwarmOrchestrator({"use_mock_data": True})
    orch.register_agent(SystemCheckAgent({"use_mock_data": True}))

    out = orch.execute_task({"type": "system_check"})
    assert out["status"] == "success"
    assert out["classification"] == "SAFE"
    assert type(out["classification"]) is str


def test_validation_error_classification_is_plain_string():
    orch = SwarmOrchestrator({"use_mock_data": True})
    # Trigger a validation failure: missing 'type'
    out = orch.execute_task({})
    assert out["status"] == "error"
    assert out["classification"] == "SAFE"
    assert type(out["classification"]) is str


def test_blocked_result_is_json_serializable_without_default():
    """The whole result dict must round-trip through json.dumps with no
    ``default=str`` workaround — that was the practical pain L2 caused."""
    orch = SwarmOrchestrator({"use_mock_data": True, "wallet_mode": "WATCH_ONLY"})
    out = orch.execute_task({"type": "stake_tao", "amount": 50})

    # Drop the "plan" payload (user task) since it can contain anything;
    # we care that the orchestrator's own fields are clean.
    serializable = {k: v for k, v in out.items() if k != "output"}
    serializable["output"] = {
        "note": out["output"]["note"],
        "plan_keys": list(out["output"]["plan"].keys()),
    }
    encoded = json.dumps(serializable)  # must not raise
    assert "DANGER" in encoded
    assert "Classification." not in encoded


def test_classification_string_equals_enum_value():
    """Sanity: the enum's ``.value`` is the canonical wire format."""
    assert Classification.SAFE.value == "SAFE"
    assert Classification.CAUTION.value == "CAUTION"
    assert Classification.DANGER.value == "DANGER"
