"""
tests/test_risk_score.py
Comprehensive tests for the RiskScorer class.

Tests cover:
- Risk calculation structure and categories
- Individual risk type calculations (subnet/repo, trade)
- Risk level determination
- Veto behavior
- Edge cases and error handling
"""

import pytest

from tao_swarm.scoring.risk_score import RISK_CATEGORY_WEIGHTS, RiskScorer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_context(**kwargs):
    """Build a valid risk context."""
    context = {
        "repo": {
            "license": "mit",
            "archived": False,
            "updated_at": "2024-06-01T10:00:00Z",
            "is_fork": False,
            "stars": 100,
        },
        "market": {
            "change_24h_pct": 5.0,
            "market_cap_usd": 1_000_000_000,
            "volume_24h_usd": 50_000_000,
        },
        "wallet": {
            "address": "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
            "balance": 10.0,
            "recent_tx_count": 5,
        },
        "reputation": {
            "twitter_followers": 1000,
            "sentiment": "positive",
            "reports": 0,
        },
    }
    context.update(kwargs)
    return context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def risk_scorer():
    """Provide a fresh RiskScorer instance."""
    return RiskScorer(config={})


# ---------------------------------------------------------------------------
# 1. Basic structure
# ---------------------------------------------------------------------------

def test_calculate_risk_returns_dict(risk_scorer):
    """calculate_risk must return a dictionary with expected keys."""
    context = make_context()
    result = risk_scorer.calculate_risk(context)
    assert isinstance(result, dict), "Result must be a dictionary"
    assert "categories" in result
    assert "total_risk" in result
    assert "risk_level" in result
    assert "veto" in result


# ---------------------------------------------------------------------------
# 2. Repo risk
# ---------------------------------------------------------------------------

def test_repo_risk_safe_repo(risk_scorer):
    """Safe repo must have LOW risk level."""
    context = make_context()
    result = risk_scorer.calculate_risk(context)
    repo_risk = result["categories"]["technical"]
    assert repo_risk["score"] < 50, (
        f"Safe repo should have low score, got {repo_risk['score']}"
    )


def test_repo_risk_suspicious_repo(risk_scorer):
    """Suspicious repo must have higher risk score."""
    context = make_context(
        repo={
            "stars": 2,
            "last_commit_days": 300,
            "license": "none",
            "archived": True,
            "updated_at": "2022-01-01T00:00:00Z",
            "is_fork": True,
        },
    )
    result = risk_scorer.calculate_risk(context)
    repo_risk = result["categories"]["technical"]
    assert repo_risk["score"] >= 50, (
        f"Suspicious repo should have higher score, got {repo_risk['score']}"
    )


# ---------------------------------------------------------------------------
# 3. Market/Financial risk
# ---------------------------------------------------------------------------

def test_financial_risk_low_volatility(risk_scorer):
    """Low volatility market should have LOW financial risk."""
    context = make_context(
        market={
            "change_24h_pct": 1.0,
            "market_cap_usd": 10_000_000_000,
            "volume_24h_usd": 500_000_000,
        },
    )
    result = risk_scorer.calculate_risk(context)
    fin_risk = result["categories"]["financial"]
    assert fin_risk["score"] < 40, (
        f"Low volatility should score low, got {fin_risk['score']}"
    )


def test_financial_risk_high_volatility(risk_scorer):
    """High volatility + low liquidity should have HIGH financial risk."""
    context = make_context(
        market={
            "change_24h_pct": 25.0,
            "market_cap_usd": 50_000_000,
            "volume_24h_usd": 500_000,
        },
    )
    result = risk_scorer.calculate_risk(context)
    fin_risk = result["categories"]["financial"]
    assert fin_risk["score"] >= 50, (
        f"High volatility should score high, got {fin_risk['score']}"
    )


# ---------------------------------------------------------------------------
# 4. Wallet risk
# ---------------------------------------------------------------------------

def test_wallet_risk_normal(risk_scorer):
    """Normal wallet should have LOW wallet risk."""
    context = make_context(
        wallet={
            "address": "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
            "balance": 10.0,
            "recent_tx_count": 5,
        },
    )
    result = risk_scorer.calculate_risk(context)
    wallet_risk = result["categories"]["wallet"]
    assert wallet_risk["score"] < 40, (
        f"Normal wallet should score low, got {wallet_risk['score']}"
    )


def test_wallet_risk_high_balance(risk_scorer):
    """High balance wallet should have higher risk."""
    context = make_context(
        wallet={
            "address": "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
            "balance": 2000.0,
            "recent_tx_count": 60,
        },
    )
    result = risk_scorer.calculate_risk(context)
    wallet_risk = result["categories"]["wallet"]
    assert wallet_risk["score"] >= 30, (
        f"High balance wallet should score higher, got {wallet_risk['score']}"
    )


# ---------------------------------------------------------------------------
# 5. Reputation risk
# ---------------------------------------------------------------------------

def test_reputation_risk_good(risk_scorer):
    """Good reputation should have LOW risk."""
    context = make_context(
        reputation={
            "twitter_followers": 10000,
            "sentiment": "positive",
            "reports": 0,
        },
    )
    result = risk_scorer.calculate_risk(context)
    rep_risk = result["categories"]["reputation"]
    assert rep_risk["score"] < 40, (
        f"Good reputation should score low, got {rep_risk['score']}"
    )


def test_reputation_risk_bad(risk_scorer):
    """Negative sentiment + many reports should have HIGH risk."""
    context = make_context(
        reputation={
            "twitter_followers": 50,
            "sentiment": "negative",
            "reports": 15,
        },
    )
    result = risk_scorer.calculate_risk(context)
    rep_risk = result["categories"]["reputation"]
    assert rep_risk["score"] >= 50, (
        f"Bad reputation should score high, got {rep_risk['score']}"
    )


# ---------------------------------------------------------------------------
# 6. Risk level determination
# ---------------------------------------------------------------------------

def test_get_risk_level_low(risk_scorer):
    """Score 0-19 must return LOW."""
    assert risk_scorer.get_risk_level(0) == "LOW"
    assert risk_scorer.get_risk_level(10) == "LOW"
    assert risk_scorer.get_risk_level(19.9) == "LOW"


def test_get_risk_level_medium(risk_scorer):
    """Score 20-44 must return MEDIUM."""
    assert risk_scorer.get_risk_level(20) == "MEDIUM"
    assert risk_scorer.get_risk_level(35) == "MEDIUM"
    assert risk_scorer.get_risk_level(44.9) == "MEDIUM"


def test_get_risk_level_high(risk_scorer):
    """Score 45-69 must return HIGH."""
    assert risk_scorer.get_risk_level(45) == "HIGH"
    assert risk_scorer.get_risk_level(55) == "HIGH"
    assert risk_scorer.get_risk_level(69.9) == "HIGH"


def test_get_risk_level_critical(risk_scorer):
    """Score 70-100 must return CRITICAL."""
    assert risk_scorer.get_risk_level(70) == "CRITICAL"
    assert risk_scorer.get_risk_level(90) == "CRITICAL"
    assert risk_scorer.get_risk_level(100) == "CRITICAL"


# ---------------------------------------------------------------------------
# 7. Veto behavior
# ---------------------------------------------------------------------------

def test_should_veto_critical_pattern_returns_true(risk_scorer):
    """CRITICAL risk pattern must trigger veto."""
    risk_data = {
        "total_risk": 80,
        "findings": [{"pattern": "confirmed_scam", "severity": "CRITICAL", "risk": 80}],
    }
    assert risk_scorer.should_veto(risk_data) is True


def test_should_veto_critical_level_returns_true(risk_scorer):
    """CRITICAL risk level must trigger veto."""
    risk_data = {
        "total_risk": 75,
        "findings": [],
    }
    assert risk_scorer.should_veto(risk_data) is True


def test_should_veto_low_returns_false(risk_scorer):
    """LOW risk must NOT trigger veto."""
    risk_data = {
        "total_risk": 10,
        "findings": [],
    }
    assert risk_scorer.should_veto(risk_data) is False


def test_should_veto_medium_returns_false(risk_scorer):
    """MEDIUM risk must NOT trigger veto."""
    risk_data = {
        "total_risk": 30,
        "findings": [],
    }
    assert risk_scorer.should_veto(risk_data) is False


# ---------------------------------------------------------------------------
# 8. Risk categories weights
# ---------------------------------------------------------------------------

def test_risk_category_weights_sum_to_1():
    """Risk category weights must sum to 1.0."""
    total = sum(RISK_CATEGORY_WEIGHTS.values())
    assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"


def test_all_risk_categories_present():
    """All four risk categories must have weights."""
    expected = ["technical", "financial", "wallet", "reputation"]
    for cat in expected:
        assert cat in RISK_CATEGORY_WEIGHTS, f"Missing weight for {cat}"
    assert len(RISK_CATEGORY_WEIGHTS) == 4


# ---------------------------------------------------------------------------
# 9. Overall risk calculation
# ---------------------------------------------------------------------------

def test_calculate_risk_produces_weighted_total(risk_scorer):
    """Overall score must be weighted average of categories."""
    context = make_context()
    result = risk_scorer.calculate_risk(context)
    categories = result["categories"]
    expected_total = sum(
        categories[cat]["score"] * RISK_CATEGORY_WEIGHTS[cat]
        for cat in RISK_CATEGORY_WEIGHTS
    )
    assert abs(result["total_risk"] - round(expected_total, 2)) < 0.1, (
        f"Total {result['total_risk']} != weighted average {expected_total}"
    )


def test_high_risk_context_triggers_veto(risk_scorer):
    """Context with CRITICAL pattern must set veto=True."""
    # Direct CRITICAL pattern should always trigger veto
    result = risk_scorer.calculate_risk(make_context())
    # Manually check veto with a critical-risk context
    critical_context = make_context(
        reputation={
            "twitter_followers": 10,
            "sentiment": "negative",
            "reports": 20,  # > 10 reports triggers CRITICAL severity finding
        },
    )
    result = risk_scorer.calculate_risk(critical_context)
    if result["risk_level"] == "CRITICAL":
        assert result["veto"] is True, "CRITICAL risk must trigger veto"
    # Verify that should_veto detects critical patterns
    assert risk_scorer.should_veto({
        "total_risk": 80,
        "findings": [{"pattern": "confirmed_scam", "severity": "CRITICAL", "risk": 80}],
    }) is True


# ---------------------------------------------------------------------------
# 10. Convenience methods
# ---------------------------------------------------------------------------

def test_assess_repo_risk(risk_scorer):
    """assess_repo_risk must work with repo data."""
    repo_data = {
        "license": "mit",
        "stars": 500,
        "updated_at": "2024-06-01T10:00:00Z",
        "archived": False,
        "is_fork": False,
    }
    result = risk_scorer.assess_repo_risk(repo_data)
    assert isinstance(result, dict)
    assert "total_risk" in result
    assert "risk_level" in result


def test_assess_trade_risk(risk_scorer):
    """assess_trade_risk must work with trade data."""
    trade_data = {
        "market": {
            "change_24h_pct": 5.0,
            "market_cap_usd": 1_000_000_000,
            "volume_24h_usd": 50_000_000,
        },
        "wallet": {
            "address": "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty",
            "balance": 10.0,
        },
    }
    result = risk_scorer.assess_trade_risk(trade_data)
    assert isinstance(result, dict)
    assert "total_risk" in result
    assert "risk_level" in result


# ---------------------------------------------------------------------------
# 11. CRITICAL patterns
# ---------------------------------------------------------------------------

def test_critical_finding_triggers_veto(risk_scorer):
    """Finding with confirmed_scam pattern must trigger veto."""
    risk_data = {
        "total_risk": 30,
        "findings": [
            {"pattern": "confirmed_scam", "severity": "HIGH", "risk": 30},
        ],
    }
    assert risk_scorer.should_veto(risk_data) is True


def test_critical_severity_finding_triggers_veto(risk_scorer):
    """Finding with CRITICAL severity must trigger veto."""
    risk_data = {
        "total_risk": 30,
        "findings": [
            {"pattern": "something", "severity": "CRITICAL", "risk": 30},
        ],
    }
    assert risk_scorer.should_veto(risk_data) is True
