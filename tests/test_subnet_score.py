"""
tests/test_subnet_score.py
Comprehensive tests for the SubnetScorer class.

Tests cover:
- Score structure and range validation
- Individual dimension scoring
- Recommendation logic
- Missing data handling
- Weight validation
"""

import pytest

from src.scoring.subnet_score import SubnetScorer, CRITERIA_WEIGHTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_subnet_data(netuid=1, **overrides):
    """Build valid subnet data with all required profile fields."""
    data = {
        "netuid": netuid,
        "profile": {
            "github": {
                "language": "python",
                "size_kb": 1000,
                "stars": 50,
                "forks": 10,
                "description": "A test subnet for testing purposes",
                "updated_at": "2024-01-15T10:00:00Z",
                "open_issues": 5,
                "has_wiki": True,
                "has_discussions": True,
                "license": "mit",
                "is_fork": False,
                "archived": False,
            },
            "hardware_requirements": {
                "gpu": "rtx3080",
                "vram_gb": 16,
                "ram_gb": 32,
                "disk_gb": 500,
                "estimated_cost_monthly_usd": 200,
            },
            "documentation": {
                "has_installation": True,
                "has_api_docs": True,
                "has_examples": True,
                "headings_h2": 6,
                "code_blocks": 10,
                "content_length": 6000,
            },
            "chain_info": {
                "num_neurons": 30,
                "max_neurons": 100,
                "created_at_block": 1000,
            },
            "reward_history": [
                {"reward": 10.0}, {"reward": 11.0}, {"reward": 10.5},
                {"reward": 10.8}, {"reward": 11.2}, {"reward": 10.9},
                {"reward": 11.1},
            ],
        },
    }
    data["profile"].update(overrides)
    return data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scorer():
    """Provide a fresh SubnetScorer instance with temp DB."""
    return SubnetScorer(config={"db_path": "/tmp/test_subnet_scores.db"})


@pytest.fixture
def perfect_subnet():
    """Subnet data with excellent profile."""
    return make_subnet_data(
        netuid=1,
        github={
            "language": "python",
            "size_kb": 500,
            "stars": 200,
            "forks": 50,
            "description": "Excellent documentation and examples",
            "updated_at": "2024-06-15T10:00:00Z",
            "open_issues": 2,
            "has_wiki": True,
            "has_discussions": True,
            "license": "mit",
            "is_fork": False,
            "archived": False,
        },
        hardware_requirements={
            "gpu": "none",
            "vram_gb": 0,
            "ram_gb": 16,
            "disk_gb": 100,
            "estimated_cost_monthly_usd": 50,
        },
        documentation={
            "has_installation": True,
            "has_api_docs": True,
            "has_examples": True,
            "headings_h2": 10,
            "code_blocks": 15,
            "content_length": 10000,
        },
        chain_info={
            "num_neurons": 10,
            "max_neurons": 100,
        },
        reward_history=[
            {"reward": 10.0 + i * 0.1} for i in range(14)
        ],
    )


@pytest.fixture
def poor_subnet():
    """Subnet data with poor profile."""
    return make_subnet_data(
        netuid=2,
        github={
            "language": "",
            "size_kb": 50000,
            "stars": 0,
            "forks": 0,
            "description": "",
            "updated_at": "2023-01-15T10:00:00Z",
            "open_issues": 100,
            "has_wiki": False,
            "has_discussions": False,
            "license": "none",
            "is_fork": True,
            "archived": True,
        },
        hardware_requirements={
            "gpu": "a100",
            "vram_gb": 80,
            "ram_gb": 128,
            "disk_gb": 2000,
            "estimated_cost_monthly_usd": 2000,
        },
        documentation={
            "has_installation": False,
            "has_api_docs": False,
            "has_examples": False,
            "headings_h2": 0,
            "code_blocks": 0,
            "content_length": 0,
        },
        chain_info={
            "num_neurons": 95,
            "max_neurons": 100,
        },
        reward_history=[],
    )


# ---------------------------------------------------------------------------
# 1. Basic structure
# ---------------------------------------------------------------------------

def test_score_subnet_returns_dict_with_total_score(scorer, perfect_subnet):
    """score_subnet must return a dict with 'total_score' key."""
    result = scorer.score_subnet(perfect_subnet)
    assert isinstance(result, dict), "Result must be a dictionary"
    assert "total_score" in result, "Result must contain 'total_score' key"
    assert isinstance(result["total_score"], (int, float)), "total_score must be numeric"


def test_score_in_valid_range_0_to_100(scorer, perfect_subnet, poor_subnet):
    """Score must always be in range [0, 100]."""
    for data, label in [(perfect_subnet, "perfect"), (poor_subnet, "poor")]:
        result = scorer.score_subnet(data)
        assert 0 <= result["total_score"] <= 100, (
            f"Score for {label} subnet out of range: {result['total_score']}"
        )


# ---------------------------------------------------------------------------
# 2. Individual dimension scoring
# ---------------------------------------------------------------------------

def test_score_technical_fit_python(scorer):
    """Python language should give bonus in technical fit."""
    data = make_subnet_data(github={"language": "python"})
    score = scorer.score_technical_fit(data)
    assert score > 50, f"Python should score above base 50, got {score}"


def test_score_technical_fit_rust(scorer):
    """Rust language should give bonus in technical fit."""
    data = make_subnet_data(github={"language": "rust"})
    score = scorer.score_technical_fit(data)
    assert score > 50, f"Rust should score above base 50, got {score}"


def test_score_technical_fit_no_gpu(scorer):
    """No GPU requirement should give bonus."""
    data = make_subnet_data(
        hardware_requirements={"gpu": "none"},
        github={"language": "python"},
    )
    score = scorer.score_technical_fit(data)
    assert score > 50, f"No GPU should score above base 50, got {score}"


def test_score_hardware_fit_no_gpu(scorer):
    """No GPU (vram=0) should score well in hardware fit."""
    data = make_subnet_data(
        hardware_requirements={
            "vram_gb": 0,
            "ram_gb": 16,
            "estimated_cost_monthly_usd": 50,
        },
    )
    score = scorer.score_hardware_fit(data)
    assert score > 50, f"No GPU + low cost should score well, got {score}"


def test_score_hardware_fit_high_end(scorer):
    """High-end GPU + high cost should score low in hardware fit."""
    data = make_subnet_data(
        hardware_requirements={
            "vram_gb": 80,
            "ram_gb": 128,
            "estimated_cost_monthly_usd": 2000,
        },
    )
    score = scorer.score_hardware_fit(data)
    assert score < 50, f"High-end should score low, got {score}"


def test_score_setup_complexity_with_docs(scorer):
    """Good documentation should score well in setup complexity."""
    data = make_subnet_data(
        documentation={
            "has_installation": True,
            "has_examples": True,
            "code_blocks": 10,
        },
        github={"description": "Well documented subnet", "size_kb": 500},
    )
    score = scorer.score_setup_complexity(data)
    assert score > 50, f"Good docs should score well, got {score}"


def test_score_doc_quality_good_docs(scorer):
    """Good documentation should score well in doc quality."""
    data = make_subnet_data(
        documentation={
            "has_installation": True,
            "has_api_docs": True,
            "has_examples": True,
            "headings_h2": 8,
            "content_length": 8000,
        },
    )
    score = scorer.score_doc_quality(data)
    assert score > 50, f"Good docs should score well, got {score}"


def test_score_competition_low_fill(scorer):
    """Low fill ratio should score well in competition."""
    data = make_subnet_data(
        chain_info={"num_neurons": 10, "max_neurons": 100},
        github={"stars": 5},
    )
    score = scorer.score_competition(data)
    assert score > 50, f"Low fill ratio should score well, got {score}"


def test_score_competition_high_fill(scorer):
    """High fill ratio should score low in competition."""
    data = make_subnet_data(
        chain_info={"num_neurons": 95, "max_neurons": 100},
        github={"stars": 500},
    )
    score = scorer.score_competition(data)
    assert score < 50, f"High fill ratio should score low, got {score}"


def test_score_maintenance_recent(scorer):
    """Recent updates should score well in maintenance."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    data = make_subnet_data(
        github={
            "updated_at": now,
            "open_issues": 2,
            "has_wiki": True,
            "has_discussions": True,
        },
    )
    score = scorer.score_maintenance(data)
    assert score > 50, f"Recent updates should score well, got {score}"


def test_score_maintenance_old(scorer):
    """Old updates should score low in maintenance."""
    data = make_subnet_data(
        github={
            "updated_at": "2022-01-01T00:00:00Z",
            "open_issues": 100,
            "has_wiki": False,
            "has_discussions": False,
        },
    )
    score = scorer.score_maintenance(data)
    assert score < 50, f"Old updates should score low, got {score}"


def test_score_security_risk_good(scorer):
    """Good security indicators should score well."""
    data = make_subnet_data(
        github={
            "license": "mit",
            "is_fork": False,
            "archived": False,
        },
    )
    score = scorer.score_security_risk(data)
    assert score > 50, f"Good security should score well, got {score}"


def test_score_security_risk_archived(scorer):
    """Archived repo should score low in security risk."""
    data = make_subnet_data(
        github={
            "license": "none",
            "is_fork": True,
            "archived": True,
        },
    )
    score = scorer.score_security_risk(data)
    assert score < 50, f"Archived repo should score low, got {score}"


# ---------------------------------------------------------------------------
# 3. Recommendation logic
# ---------------------------------------------------------------------------

def test_get_recommendation_dict_return(scorer):
    """get_recommendation must return a dict with label key."""
    rec = scorer.get_recommendation(50)
    assert isinstance(rec, dict), "Recommendation must be a dict"
    assert "label" in rec, "Recommendation must have 'label' key"


def test_get_recommendation_high_score(scorer):
    """Score >= 88 must return Validator-Kandidat."""
    rec = scorer.get_recommendation(88)
    assert rec["label"] == "Validator-Kandidat", f"Got {rec['label']}"
    rec = scorer.get_recommendation(95)
    assert rec["label"] == "Validator-Kandidat", f"Got {rec['label']}"


def test_get_recommendation_medium_score(scorer):
    """Score 75-87 must return Miner-Kandidat."""
    rec = scorer.get_recommendation(75)
    assert rec["label"] == "Miner-Kandidat", f"Got {rec['label']}"
    rec = scorer.get_recommendation(80)
    assert rec["label"] == "Miner-Kandidat", f"Got {rec['label']}"


def test_get_recommendation_low_score(scorer):
    """Score < 20 must return Ignorieren."""
    rec = scorer.get_recommendation(0)
    assert rec["label"] == "Ignorieren", f"Got {rec['label']}"
    rec = scorer.get_recommendation(10)
    assert rec["label"] == "Ignorieren", f"Got {rec['label']}"


# ---------------------------------------------------------------------------
# 4. Data handling
# ---------------------------------------------------------------------------

def test_score_subnet_with_valid_data(scorer, perfect_subnet):
    """Valid data should produce a valid score."""
    result = scorer.score_subnet(perfect_subnet)
    assert "total_score" in result
    assert "breakdown" in result
    assert "recommendation" in result
    assert result["netuid"] == 1


def test_empty_profile_handling(scorer):
    """Empty profile should still produce a valid score."""
    data = {"netuid": 99, "profile": {}}
    result = scorer.score_subnet(data)
    assert isinstance(result, dict)
    assert "total_score" in result
    assert 0 <= result["total_score"] <= 100


# ---------------------------------------------------------------------------
# 5. Score breakdown structure
# ---------------------------------------------------------------------------

def test_score_breakdown_contains_all_dimensions(scorer, perfect_subnet):
    """Score result must contain all 10 scoring dimensions."""
    result = scorer.score_subnet(perfect_subnet)
    breakdown = result.get("breakdown", {})
    expected_dimensions = [
        "technical_fit", "hardware_fit", "setup_complexity", "doc_quality",
        "competition", "reward_realism", "maintenance", "security_risk",
        "learning_value", "long_term",
    ]
    for dim in expected_dimensions:
        assert dim in breakdown, f"Missing dimension '{dim}' in score breakdown"


def test_perfect_subnet_high_score(scorer, perfect_subnet):
    """A perfect subnet must score highly (>= 70)."""
    result = scorer.score_subnet(perfect_subnet)
    assert result["total_score"] >= 70, (
        f"Perfect subnet should score >= 70, got {result['total_score']}"
    )


def test_poor_subnet_low_score(scorer, poor_subnet):
    """A poor subnet must score low (< 60)."""
    result = scorer.score_subnet(poor_subnet)
    assert result["total_score"] < 60, (
        f"Poor subnet should score < 60, got {result['total_score']}"
    )


# ---------------------------------------------------------------------------
# 6. Weight validation
# ---------------------------------------------------------------------------

def test_weight_sum_equals_1():
    """Sum of all dimension weights must equal 1.0."""
    total = sum(CRITERIA_WEIGHTS.values())
    assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"


def test_all_dimensions_have_weights():
    """All expected dimensions must have weights defined."""
    expected = [
        "technical_fit", "hardware_fit", "setup_complexity", "doc_quality",
        "competition", "reward_realism", "maintenance", "security_risk",
        "learning_value", "long_term",
    ]
    for dim in expected:
        assert dim in CRITERIA_WEIGHTS, f"Missing weight for {dim}"
    assert len(CRITERIA_WEIGHTS) == 10
