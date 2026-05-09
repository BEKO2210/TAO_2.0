"""
Regression tests for the Bittensor-specific risk detectors added per
the online security research:

- ``scan_bittensor_dependency`` — catches the May 2024
  ``bittensor==6.12.2`` poisoning and the Aug 2025 typosquat
  campaign (``bitensor``, ``bittenso``, ``bittenso-cli``,
  ``qbittensor``, ``bittensor_cli``, …).
- ``scan_coldkey_swap_pattern`` — catches the
  ``schedule_coldkey_swap`` social-engineering pattern with optional
  watchlist + urgency context.
- ``score_validator_risk`` — computes 0-100 delegation-safety score
  with verdict mapping based on hotkey age, take history, vtrust,
  axon serving, scheduled coldkey swap.

Plus integration: the ``RiskSecurityAgent.run({target: "general"})``
path now invokes the typosquat + coldkey-swap detectors against the
``content`` argument; the ``target: "validator"`` action is new.

ApprovalGate now classifies ``schedule_coldkey_swap`` (and variants)
as DANGER so the orchestrator never lets a planning task touch it
without explicit approval.
"""

from __future__ import annotations

import pytest

from src.agents.risk_security_agent import RiskSecurityAgent
from src.orchestrator.approval_gate import ApprovalGate, Classification


# ---------------------------------------------------------------------------
# scan_bittensor_dependency
# ---------------------------------------------------------------------------

@pytest.fixture
def agent() -> RiskSecurityAgent:
    return RiskSecurityAgent({"strict_mode": True})


def test_dependency_clean_install_no_findings(agent):
    findings, score = agent.scan_bittensor_dependency("pip install bittensor>=8.0.0")
    assert findings == []
    assert score == 0


def test_dependency_poisoned_bittensor_6_12_2_critical(agent):
    findings, score = agent.scan_bittensor_dependency("bittensor==6.12.2")
    assert len(findings) == 1
    f = findings[0]
    assert f["severity"] == "CRITICAL"
    assert f["category"] == "supply_chain_malicious_package"
    assert f["package"] == "bittensor"
    assert f["version"] == "6.12.2"
    assert score == 50


def test_dependency_other_bittensor_versions_are_clean(agent):
    """Don't false-positive on any version of the legit bittensor
    package — only the specific poisoned 6.12.2."""
    for safe in ("bittensor==8.5.0", "bittensor>=10.0", "bittensor"):
        findings, score = agent.scan_bittensor_dependency(safe)
        assert findings == [], f"false positive on {safe!r}"
        assert score == 0


@pytest.mark.parametrize("typosquat", [
    "bitensor",
    "bitensor==9.9.4",
    "bittenso",
    "bittenso-cli==9.9.4",
    "qbittensor==9.9.4",
    "bittensor_cli",
    "bittensoor",
    "bittensr",
])
def test_dependency_typosquats_critical(agent, typosquat):
    """Every known Aug 2025 typosquat package must be flagged
    regardless of version."""
    findings, score = agent.scan_bittensor_dependency(f"pip install {typosquat}")
    assert len(findings) == 1
    assert findings[0]["severity"] == "CRITICAL"
    assert findings[0]["category"] == "supply_chain_malicious_package"
    assert score == 50


def test_dependency_off_pypi_index_is_critical(agent):
    findings, score = agent.scan_bittensor_dependency(
        "pip install --index-url https://evil.example.com/simple bittensor"
    )
    assert any(f["category"] == "supply_chain_off_pypi_index"
               for f in findings)
    assert score >= 50


def test_dependency_pypi_org_index_is_clean(agent):
    """Explicit pypi.org index must NOT trigger off-pypi finding."""
    findings, _ = agent.scan_bittensor_dependency(
        "pip install --index-url https://pypi.org/simple bittensor==8.5.0"
    )
    off_pypi = [f for f in findings
                if f["category"] == "supply_chain_off_pypi_index"]
    assert off_pypi == []


def test_dependency_empty_input_safe(agent):
    findings, score = agent.scan_bittensor_dependency("")
    assert findings == []
    assert score == 0


# ---------------------------------------------------------------------------
# scan_coldkey_swap_pattern
# ---------------------------------------------------------------------------

_VALID_SS58 = "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"
_OTHER_SS58 = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"


def test_coldkey_swap_marker_with_unknown_address_is_critical(agent):
    text = (
        "Your wallet is compromised. Please run "
        f"`btcli wallet schedule_coldkey_swap` to {_VALID_SS58} "
        "execute within the next 5 days."
    )
    findings, score = agent.scan_coldkey_swap_pattern(text)
    assert len(findings) >= 1
    f = next(x for x in findings if x["category"] == "coldkey_swap_social_engineering")
    assert f["severity"] == "CRITICAL"
    assert f["destination_ss58"] == _VALID_SS58
    assert f["in_watchlist"] is False
    assert f["urgency_detected"] is True
    assert score >= 50


def test_coldkey_swap_marker_with_watchlist_address_downgraded(agent):
    """If the destination IS in the user's watchlist, severity drops
    from CRITICAL to HIGH — they may legitimately be moving funds."""
    text = f"schedule_coldkey_swap to {_VALID_SS58}"
    findings, score = agent.scan_coldkey_swap_pattern(
        text, watchlist_addresses={_VALID_SS58}
    )
    assert len(findings) == 1
    assert findings[0]["severity"] == "HIGH"
    assert findings[0]["in_watchlist"] is True
    assert score == 30


def test_coldkey_swap_marker_without_address_still_flagged(agent):
    findings, score = agent.scan_coldkey_swap_pattern(
        "We may need to use schedule_coldkey_swap if your hotkey is at risk."
    )
    assert len(findings) == 1
    assert findings[0]["category"] == "coldkey_swap_marker_only"
    assert findings[0]["severity"] in ("MEDIUM", "HIGH")


def test_coldkey_swap_no_marker_no_findings(agent):
    """Plain SS58 addresses in unrelated text must not trigger the
    detector — only the swap markers do."""
    text = f"Watching wallet {_VALID_SS58} for balance changes."
    findings, score = agent.scan_coldkey_swap_pattern(text)
    assert findings == []
    assert score == 0


# ---------------------------------------------------------------------------
# score_validator_risk
# ---------------------------------------------------------------------------

def test_validator_risk_clean_validator_proceeds(agent):
    out = agent.score_validator_risk({
        "hotkey": "5VAL...",
        "registered_block": 5_000_000,
        "take_pct": 5.0,
        "axon_serving": True,
        "vtrust_per_subnet": {1: 0.85, 2: 0.92},
    }, current_block=5_500_000)  # 500k blocks old → past threshold
    assert out["verdict"] == "PROCEED"
    assert out["score"] < 15


def test_validator_risk_fresh_hotkey_flagged_high(agent):
    out = agent.score_validator_risk({
        "hotkey": "5VAL...",
        "registered_block": 5_400_000,
        "take_pct": 5.0,
    }, current_block=5_500_000)  # 100k blocks → fresh
    cats = [f["category"] for f in out["findings"]]
    assert "fresh_validator_hotkey" in cats
    assert out["verdict"] in ("PAUSE", "REJECT", "STOP")


def test_validator_risk_take_spike_critical(agent):
    out = agent.score_validator_risk({
        "hotkey": "5VAL...",
        "take_pct": 18.0,
        "take_history": [(1000, 5.0), (5000, 18.0)],
    }, current_block=10_000)
    cats = [f["category"] for f in out["findings"]]
    assert "validator_take_spike" in cats


def test_validator_risk_scheduled_coldkey_swap_stops(agent):
    out = agent.score_validator_risk({
        "hotkey": "5VAL...",
        "scheduled_coldkey_swap_block": 5_510_000,
    }, current_block=5_500_000)
    assert out["verdict"] == "STOP"
    assert any(f["category"] == "scheduled_coldkey_swap" for f in out["findings"])


def test_validator_risk_no_axon_serving_flagged(agent):
    out = agent.score_validator_risk({
        "hotkey": "5VAL...",
        "axon_serving": False,
    }, current_block=10_000_000)
    cats = [f["category"] for f in out["findings"]]
    assert "no_axon_serving" in cats


def test_validator_risk_zero_vtrust_with_permit_flagged(agent):
    out = agent.score_validator_risk({
        "hotkey": "5VAL...",
        "vtrust_per_subnet": {1: 0.0, 12: 0.0, 23: 0.85},
    }, current_block=10_000_000)
    cats = [f["category"] for f in out["findings"]]
    assert "zero_vtrust_with_permit" in cats


# ---------------------------------------------------------------------------
# Integration: detectors fire via run({target: "general"})
# ---------------------------------------------------------------------------

def test_general_review_picks_up_typosquat_in_content(agent):
    out = agent.run({
        "params": {
            "target": "general",
            "content": "Try `pip install bitensor==9.9.4` to get the latest CLI.",
        }
    })
    assert out["verdict"] == "STOP"
    cats = [f["category"] for f in out["findings"]]
    assert "supply_chain_malicious_package" in cats


def test_general_review_picks_up_coldkey_swap_in_content(agent):
    out = agent.run({
        "params": {
            "target": "general",
            "content": (
                "Urgent action required: schedule_coldkey_swap to "
                f"{_VALID_SS58} — execute within the next 12 hours."
            ),
        }
    })
    assert out["verdict"] == "STOP"
    cats = [f["category"] for f in out["findings"]]
    assert "coldkey_swap_social_engineering" in cats


def test_general_review_watchlist_param_is_threaded_through(agent):
    """Passing a watchlist downgrades the swap finding from CRITICAL
    to HIGH — verifies the param is actually plumbed."""
    out = agent.run({
        "params": {
            "target": "general",
            "content": f"schedule_coldkey_swap to {_VALID_SS58}",
            "watchlist_addresses": [_VALID_SS58],
        }
    })
    swap_findings = [f for f in out["findings"]
                     if f["category"] == "coldkey_swap_social_engineering"]
    assert len(swap_findings) == 1
    assert swap_findings[0]["severity"] == "HIGH"


def test_validator_target_invokes_score_validator_risk(agent):
    out = agent.run({
        "params": {
            "target": "validator",
            "validator": {
                "hotkey": "5VAL...",
                "scheduled_coldkey_swap_block": 1234,
            },
            "current_block": 1000,
        }
    })
    assert out["verdict"] == "STOP"
    assert out["target"] == "validator"


# ---------------------------------------------------------------------------
# ApprovalGate: schedule_coldkey_swap is DANGER
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", [
    "schedule_coldkey_swap",
    "swap_coldkey",
    "swap_hotkey",
])
def test_approval_gate_classifies_coldkey_swap_actions_as_danger(action):
    gate = ApprovalGate()
    cls = gate.classify_action(action, {})
    assert cls == Classification.DANGER
    assert gate.can_execute(cls) is False
