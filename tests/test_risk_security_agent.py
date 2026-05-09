"""
Regression tests for finding M1: ``RiskSecurityAgent`` defaulted to
``verdict=PROCEED`` even when the caller passed no content / target / URL,
i.e. when nothing was actually reviewed. Empty findings does not mean
"safe" — it can mean "no input was provided", and a security agent must
not certify the latter as the former.

The fix introduces an ``INSUFFICIENT_DATA`` verdict and threads a
``data_reviewed`` flag through each entry path.
"""

from __future__ import annotations

from tao_swarm.agents.risk_security_agent import RiskSecurityAgent

# ---------------------------------------------------------------------------
# Empty-input paths must NOT produce PROCEED
# ---------------------------------------------------------------------------

def test_general_review_with_no_content_returns_insufficient_data():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({"params": {"target": "general"}})
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["findings"] == []
    assert "system_action" in out
    assert "no content" in out["system_action"].lower() or "concrete input" in out["system_action"].lower()


def test_general_review_with_no_params_returns_insufficient_data():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({})
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_repo_review_without_url_or_code_returns_insufficient_data():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({"params": {"target": "repo"}})
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_url_review_without_url_returns_insufficient_data():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({"params": {"target": "url"}})
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_operation_review_without_op_or_content_returns_insufficient_data():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({"params": {"target": "operation"}})
    assert out["verdict"] == "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------------
# Happy paths must still work
# ---------------------------------------------------------------------------

def test_general_review_with_clean_content_proceeds():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({
        "params": {
            "target": "general",
            "content": "Read the latest TAO subnet emissions and produce a markdown report.",
        }
    })
    assert out["verdict"] == "PROCEED"
    assert out["findings"] == []


def test_general_review_with_explicit_op_type_proceeds():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({"params": {"target": "general", "operation_type": "read_chain"}})
    # operation_type != 'general' → counts as data reviewed
    assert out["verdict"] == "PROCEED"


def test_repo_review_with_trusted_url_proceeds():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({
        "params": {
            "target": "repo",
            "repo_url": "https://github.com/opentensor/bittensor",
        }
    })
    # Trusted domain → no concerns or only INFO findings → PROCEED
    assert out["verdict"] in ("PROCEED", "PAUSE")
    assert out["verdict"] != "INSUFFICIENT_DATA"


def test_url_review_with_phishing_pattern_stops():
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({
        "params": {
            "target": "url",
            "url": "https://bittensor-airdrop-claim.example.com/wallet",
        }
    })
    # 'airdrop' / 'claim' / 'wallet' patterns are configured as phishing
    # indicators in _KNOWN_PHISHING_PATTERNS — at least one must trip STOP.
    assert out["verdict"] == "STOP"
    assert out["findings_count"] > 0


# ---------------------------------------------------------------------------
# Severity gates remain authoritative — INSUFFICIENT_DATA only fires
# when there's truly nothing to look at
# ---------------------------------------------------------------------------

def test_critical_finding_overrides_data_reviewed_flag():
    """A critical finding always wins over INSUFFICIENT_DATA — but in
    practice a critical finding only fires when content was scanned, so
    this is mostly belt-and-braces."""
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent.run({
        "params": {
            "target": "operation",
            "operation_type": "sign_transaction",
            "content": "Please send your seed phrase to verify this transaction.",
        }
    })
    assert out["verdict"] == "STOP"
    severity_counts = out["severity_counts"]
    assert severity_counts.get("CRITICAL", 0) >= 1


def test_compile_verdict_directly_with_data_reviewed_false():
    """Unit-level: empty findings + low score + data_reviewed=False
    must produce INSUFFICIENT_DATA, not PROCEED."""
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent._compile_verdict(findings=[], risk_score=0, data_reviewed=False)
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["findings_count"] == 0


def test_compile_verdict_default_keeps_proceed_for_clean_review():
    """Don't break the default API: when the caller doesn't pass
    data_reviewed, behaviour must still be PROCEED for low-score reviews
    so that earlier callers (and future ones written without thinking
    about this) don't silently degrade."""
    agent = RiskSecurityAgent({"strict_mode": True})
    out = agent._compile_verdict(findings=[], risk_score=0)
    assert out["verdict"] == "PROCEED"
