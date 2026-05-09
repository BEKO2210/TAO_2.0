"""
Tests for the 5 chain-derived subnet scoring criteria added per the
online research:

- ``score_taoflow_health``           (15% weight)
- ``score_validator_concentration``  (10%)
- ``score_weight_consensus_divergence`` (10%)
- ``score_miner_slot_liveness``      (8%)
- ``score_owner_liveness``           (7%)

Each test exercises:
1. The "data missing" graceful default (50 = unknown)
2. The "best case" score (100)
3. The "worst case" score (0 or near 0)
4. A realistic intermediate value

Plus integration: ``score_subnet`` reads the new criteria via
``data['profile']['<key>']`` (existing tests' fixture shape) AND
``data['<key>']`` (top-level shape used by chain_readonly output).
"""

from __future__ import annotations

import pytest

from src.scoring.subnet_score import SubnetScorer


@pytest.fixture
def scorer(tmp_path):
    return SubnetScorer(config={"db_path": str(tmp_path / "scores.db")})


# ---------------------------------------------------------------------------
# taoflow_health
# ---------------------------------------------------------------------------

def test_taoflow_missing_returns_50(scorer):
    assert scorer.score_taoflow_health({}) == 50.0
    assert scorer.score_taoflow_health({"profile": {}}) == 50.0


def test_taoflow_negative_flow_zero(scorer):
    assert scorer.score_taoflow_health({"taoflow": {"net_flow_30d": -100}}) == 0.0


def test_taoflow_top_decile_full_score(scorer):
    """Share of emission in top decile (~1.5%) → near 100."""
    score = scorer.score_taoflow_health({
        "taoflow": {"net_flow_30d": 5000, "share_of_emission_pct": 1.6}
    })
    assert score >= 95


def test_taoflow_low_share_partial_score(scorer):
    score = scorer.score_taoflow_health({
        "taoflow": {"net_flow_30d": 100, "share_of_emission_pct": 0.5}
    })
    # 30 + min(70, 0.5*47) = 30 + 23.5 = 53.5
    assert 50 < score < 60


def test_taoflow_via_profile_key(scorer):
    """Confirm the profile-level lookup also fires (existing test-fixture
    shape uses data['profile'][key])."""
    score = scorer.score_taoflow_health({
        "profile": {"taoflow": {"net_flow_30d": 5000, "share_of_emission_pct": 1.6}}
    })
    assert score >= 95


# ---------------------------------------------------------------------------
# validator_concentration
# ---------------------------------------------------------------------------

def test_validator_concentration_missing_returns_50(scorer):
    assert scorer.score_validator_concentration({}) == 50.0


def test_validator_concentration_single_validator_neutral(scorer):
    """1 validator → can't compute meaningful HHI → neutral 50."""
    data = {"metagraph": {"neurons": [
        {"uid": 0, "stake": 1000.0, "validator_permit": True},
    ]}}
    assert scorer.score_validator_concentration(data) == 50.0


def test_validator_concentration_evenly_distributed_high_score(scorer):
    """4 evenly-distributed validators → HHI=0.25 → score ~75."""
    data = {"metagraph": {"neurons": [
        {"uid": i, "stake": 100.0, "validator_permit": True}
        for i in range(4)
    ]}}
    score = scorer.score_validator_concentration(data)
    assert 70 <= score <= 80


def test_validator_concentration_dominant_validator_low(scorer):
    """1 validator with 95% of stake → HHI ~ 0.91 → low score."""
    data = {"metagraph": {"neurons": [
        {"uid": 0, "stake": 9500.0, "validator_permit": True},
        {"uid": 1, "stake": 250.0, "validator_permit": True},
        {"uid": 2, "stake": 250.0, "validator_permit": True},
    ]}}
    score = scorer.score_validator_concentration(data)
    assert score < 15


# ---------------------------------------------------------------------------
# weight_consensus_divergence
# ---------------------------------------------------------------------------

def test_weight_divergence_no_matrix_returns_50(scorer):
    assert scorer.score_weight_consensus_divergence({"metagraph": {}}) == 50.0


def test_weight_divergence_orthogonal_high_score(scorer):
    """Orthogonal weight vectors = 0 cosine similarity → high score."""
    data = {"metagraph": {"weights": [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ]}}
    score = scorer.score_weight_consensus_divergence(data)
    assert score >= 95  # below 0.6 threshold maps to 100


def test_weight_divergence_identical_low_score(scorer):
    """Three identical weight vectors = cosine similarity 1.0 → 0."""
    data = {"metagraph": {"weights": [
        [0.5, 0.3, 0.2],
        [0.5, 0.3, 0.2],
        [0.5, 0.3, 0.2],
    ]}}
    assert scorer.score_weight_consensus_divergence(data) == 0.0


def test_weight_divergence_commit_reveal_bonus(scorer):
    """Commit-reveal enabled adds +20 bonus."""
    data = {
        "metagraph": {"weights": [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
        ]},
        "hyperparameters": {"commit_reveal_weights_enabled": True},
    }
    score = scorer.score_weight_consensus_divergence(data)
    # Already capped at 100, bonus pushes it up but stays clamped
    assert score == 100.0


# ---------------------------------------------------------------------------
# miner_slot_liveness
# ---------------------------------------------------------------------------

def test_miner_liveness_no_miners_returns_50(scorer):
    assert scorer.score_miner_slot_liveness({"metagraph": {"neurons": []}}) == 50.0


def test_miner_liveness_all_active_full_score(scorer):
    data = {"metagraph": {
        "block": 5_000_000,
        "neurons": [
            {"uid": i, "validator_permit": False, "incentive": 0.001,
             "last_update_block": 4_999_900}
            for i in range(10)
        ],
    }}
    assert scorer.score_miner_slot_liveness(data) == 100.0


def test_miner_liveness_zombies_low_score(scorer):
    """All miners have zero incentive → 0% active."""
    data = {"metagraph": {
        "block": 5_000_000,
        "neurons": [
            {"uid": i, "validator_permit": False, "incentive": 0.0,
             "last_update_block": 4_999_900}
            for i in range(10)
        ],
    }}
    assert scorer.score_miner_slot_liveness(data) == 0.0


def test_miner_liveness_half_active(scorer):
    data = {"metagraph": {
        "block": 5_000_000,
        "neurons": (
            [{"uid": i, "validator_permit": False, "incentive": 0.001,
              "last_update_block": 4_999_900} for i in range(5)]
            + [{"uid": i + 5, "validator_permit": False, "incentive": 0.0,
                "last_update_block": 4_999_900} for i in range(5)]
        ),
    }}
    assert scorer.score_miner_slot_liveness(data) == 50.0


def test_miner_liveness_stale_updates_excluded(scorer):
    """Miners last updated >activity_cutoff blocks ago don't count
    as active even if their incentive is non-zero."""
    data = {
        "metagraph": {
            "block": 5_000_000,
            "neurons": [
                {"uid": 0, "validator_permit": False, "incentive": 0.001,
                 "last_update_block": 4_990_000},  # 10k blocks stale
                {"uid": 1, "validator_permit": False, "incentive": 0.001,
                 "last_update_block": 4_999_999},  # fresh
            ],
        },
        "hyperparameters": {"activity_cutoff": 5_000},
    }
    score = scorer.score_miner_slot_liveness(data)
    assert score == 50.0  # 1/2 active


# ---------------------------------------------------------------------------
# owner_liveness
# ---------------------------------------------------------------------------

def test_owner_liveness_missing_returns_50(scorer):
    assert scorer.score_owner_liveness({}) == 50.0


def test_owner_liveness_recent_activity_high_score(scorer):
    score = scorer.score_owner_liveness({"owner": {
        "days_since_last_commit": 2,
        "days_since_last_hparam_change": 8,
    }})
    # 100 - (2 + 8/2) = 100 - 6 = 94
    assert score == 94.0


def test_owner_liveness_abandoned_zero(scorer):
    score = scorer.score_owner_liveness({"owner": {
        "days_since_last_commit": 365,
        "days_since_last_hparam_change": 365,
    }})
    # decay = 365 + 182.5 = 547.5 — clamped to 100 → score 0
    assert score == 0.0


# ---------------------------------------------------------------------------
# Integration: score_subnet uses all 5 chain criteria
# ---------------------------------------------------------------------------

def test_score_subnet_breakdown_includes_all_chain_criteria(scorer):
    out = scorer.score_subnet({"netuid": 12, "profile": {}})
    chain_keys = {
        "taoflow_health", "validator_concentration",
        "weight_consensus_divergence", "miner_slot_liveness",
        "owner_liveness",
    }
    assert chain_keys <= set(out["breakdown"])


def test_score_subnet_with_full_chain_data_high(scorer):
    out = scorer.score_subnet({
        "netuid": 12,
        "profile": {},
        "metagraph": {
            "block": 5_000_000,
            "neurons": [
                {"uid": i, "stake": 100.0, "validator_permit": True}
                for i in range(4)
            ] + [
                {"uid": 10 + i, "validator_permit": False, "incentive": 0.001,
                 "last_update_block": 4_999_900}
                for i in range(10)
            ],
            "weights": [
                [1.0 if j == i else 0.0 for j in range(4)]
                for i in range(4)
            ],
        },
        "taoflow": {"net_flow_30d": 5000, "share_of_emission_pct": 1.6},
        "owner": {"days_since_last_commit": 2, "days_since_last_hparam_change": 8},
        "hyperparameters": {"commit_reveal_weights_enabled": True,
                            "activity_cutoff": 5_000},
    })
    # Chain criteria contribute 50% of the total weight; if they all
    # score 75+ the total must clear 60.
    assert out["total_score"] >= 60
    assert out["breakdown"]["taoflow_health"] >= 95
    assert out["breakdown"]["miner_slot_liveness"] == 100.0
    assert out["breakdown"]["owner_liveness"] == 94.0


def test_score_subnet_chain_data_via_top_level_keys(scorer):
    """The chain_readonly collector returns metagraph at top level
    (not nested under profile). _chain_section must accept either."""
    out = scorer.score_subnet({
        "netuid": 12,
        "profile": {},
        "metagraph": {
            "neurons": [
                {"uid": 0, "stake": 100.0, "validator_permit": True},
                {"uid": 1, "stake": 100.0, "validator_permit": True},
            ],
        },
    })
    # Validator concentration with 50/50 stake → HHI=0.5 → score ~50
    assert 40 <= out["breakdown"]["validator_concentration"] <= 60
