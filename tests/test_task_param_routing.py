"""
Regression tests for findings B2 and B3:

* B2 — ``subnet_scoring_agent.run({type:"subnet_scoring", subnet_id:12})``
  returned ``total_scored: 0`` because the agent only read
  ``params.subnets`` and ignored top-level identifiers.

* B3 — ``wallet_watch_agent.run({type:"wallet_watch", address:"…"})``
  returned ``total_balance_tao: 0`` because the agent only listed already-
  registered addresses and would not auto-watch one passed via the task.

Both agents now accept flat task-level keys (alongside the nested-params
form) and either scaffold sensible defaults or auto-watch.
"""

from __future__ import annotations

from tao_swarm.agents.subnet_scoring_agent import SubnetScoringAgent
from tao_swarm.agents.wallet_watch_agent import WalletWatchAgent

# ---------------------------------------------------------------------------
# B2 — SubnetScoringAgent honours top-level subnet_id / netuid
# ---------------------------------------------------------------------------

def test_b2_top_level_subnet_id_produces_score():
    out = SubnetScoringAgent({}).run({"type": "subnet_scoring", "subnet_id": 12})
    assert out["total_scored"] == 1
    scored = out["scored_subnets"][0]
    assert scored["netuid"] == 12
    assert isinstance(scored["final_score"], (int, float))
    assert scored["recommendation"] in ("RECOMMENDED", "CONDITIONAL", "NOT RECOMMENDED")


def test_b2_top_level_netuid_alias_works():
    out = SubnetScoringAgent({}).run({"netuid": 5})
    assert out["total_scored"] == 1
    assert out["scored_subnets"][0]["netuid"] == 5


def test_b2_nested_params_still_works():
    """The nested-params form must keep working for callers that already
    use it."""
    out = SubnetScoringAgent({}).run({"params": {"netuid": 7}})
    assert out["total_scored"] == 1
    assert out["scored_subnets"][0]["netuid"] == 7


def test_b2_full_subnet_dict_does_not_emit_stub_warning():
    out = SubnetScoringAgent({}).run({
        "params": {
            "subnets": [
                {"netuid": 1, "name": "text", "category": "nlp"},
            ],
        },
    })
    assert out["total_scored"] == 1
    assert "note" not in out
    assert "stub_count" not in out


def test_b2_stub_subnet_emits_explanatory_note():
    out = SubnetScoringAgent({}).run({"subnet_id": 99})
    assert out["total_scored"] == 1
    assert out.get("stub_count") == 1
    assert "stub" in out["note"].lower()


def test_b2_explicit_params_win_over_top_level_alias():
    """If both forms are provided, ``params`` wins — explicit beats fallback."""
    out = SubnetScoringAgent({}).run({
        "subnet_id": 999,                       # top-level fallback
        "params": {"subnets": [{"netuid": 1, "name": "text", "category": "nlp"}]},
    })
    assert out["total_scored"] == 1
    assert out["scored_subnets"][0]["netuid"] == 1


def test_b2_no_input_means_empty_result():
    """If nothing is provided, scoring still returns a coherent (empty) result."""
    out = SubnetScoringAgent({}).run({"type": "subnet_scoring"})
    assert out["total_scored"] == 0
    assert out["scored_subnets"] == []


# ---------------------------------------------------------------------------
# B3 — WalletWatchAgent auto-watches addresses passed via the task
# ---------------------------------------------------------------------------

ADDR = "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"


def test_b3_top_level_address_auto_watches_and_snapshots():
    a = WalletWatchAgent({"use_mock_data": True})
    out = a.run({"type": "wallet_watch", "address": ADDR})
    assert out["success"] is True
    assert out["address_count"] >= 1
    # Mock data should yield non-zero balances; we just assert the field
    # is present and numeric so the test doesn't break if mock values
    # change.
    assert isinstance(out["total_balance_tao"], (int, float))
    assert isinstance(out["total_staked_tao"], (int, float))


def test_b3_nested_params_address_auto_watches():
    a = WalletWatchAgent({"use_mock_data": True})
    out = a.run({"params": {"address": ADDR}})
    assert out["address_count"] >= 1


def test_b3_explicit_watch_action_still_works():
    a = WalletWatchAgent({"use_mock_data": True})
    out = a.run({"params": {"action": "watch", "address": ADDR, "label": "cold1"}})
    assert out["success"] is True
    assert out["status"] in ("added", "already_watched")


def test_b3_pre_registered_address_is_not_re_added():
    a = WalletWatchAgent({"use_mock_data": True, "watched_addresses": [ADDR]})
    out = a.run({"type": "wallet_watch", "address": ADDR})
    # Should still show one address, not two
    assert out["address_count"] == 1


def test_b3_invalid_address_does_not_get_auto_watched():
    a = WalletWatchAgent({"use_mock_data": True})
    out = a.run({"type": "wallet_watch", "address": "not-a-valid-ss58-address"})
    # Address validation rejected it → watch list stays empty.
    assert out["addresses"] == []
    assert a.watch_addresses == []


def test_b3_safety_flags_remain_false_throughout():
    """Auto-watch must never trigger seed/private-key requests."""
    a = WalletWatchAgent({"use_mock_data": True})
    a.run({"type": "wallet_watch", "address": ADDR})
    assert a.requested_seed_phrase is False
    assert a.requested_private_key is False
