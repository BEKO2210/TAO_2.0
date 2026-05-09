"""
Tests for the Subscan-backed live path in ``WalletWatchOnlyCollector``.

The collector still defaults to deterministic mock data; the live
path is opt-in via ``use_mock_data=False``. These tests mock
``requests.post`` so they run with no network, and verify:

1. Successful Subscan response → balances / delegations parsed and
   ``_meta.mode == "live"``.
2. Subscan returns ``code != 0`` (Subscan's "address not found" /
   error indicator) → fall back to deterministic mock with a
   reasonable ``_meta``.
3. HTTP non-200 → fall back to mock.
4. Network exception → fall back to mock with ``fallback_reason``
   naming the exception type.
5. API key threading: ``SUBSCAN_API_KEY`` env var picked up; explicit
   config beats env; ``X-API-Key`` header set when present.
6. ``_planck_to_tao`` converts integer plancks correctly (0.0 for
   garbage input rather than crashing).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.collectors.wallet_watchonly import (
    _PLANCK_PER_TAO,
    WalletWatchOnlyCollector,
)

_ADDR = "5DAAnrj7VHTznn2AWBemMuyBwZWs6FNFjdyVXUeYum3PTXFy"


def _ok(payload: dict) -> MagicMock:
    """Build a MagicMock that mimics a successful requests.Response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


def _err(status_code: int = 500, payload: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    return resp


# ---------------------------------------------------------------------------
# get_balance: live path
# ---------------------------------------------------------------------------

def test_balance_live_path_parses_subscan_response(tmp_path):
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})

    # 12.345 TAO free, 1.5 TAO reserved (in plancks)
    payload = {
        "code": 0,
        "data": {
            "account": {
                "balance": str(int(12.345 * _PLANCK_PER_TAO)),
                "reserved": str(int(1.5 * _PLANCK_PER_TAO)),
                "balance_lock": "0",
            }
        },
    }
    with patch("src.collectors.wallet_watchonly.requests.post",
               return_value=_ok(payload)):
        bal = c.get_balance(_ADDR)

    assert bal["_meta"]["mode"] == "live"
    assert bal["free"] == pytest.approx(12.345, abs=1e-5)
    assert bal["reserved"] == pytest.approx(1.5, abs=1e-5)
    assert bal["total"] == pytest.approx(13.845, abs=1e-5)


def test_balance_subscan_error_code_falls_back_to_mock(tmp_path):
    """Subscan signals errors via code != 0. We treat that as 'no
    live data' and fall back to deterministic mock — no crash."""
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})

    payload = {"code": 10001, "message": "Address not found", "data": {}}
    with patch("src.collectors.wallet_watchonly.requests.post",
               return_value=_ok(payload)):
        bal = c.get_balance(_ADDR)

    # Falls through to mock, but no fallback_reason because the
    # request *succeeded* — the address just isn't found upstream.
    assert bal["_meta"]["mode"] == "mock"


def test_balance_http_500_falls_back_to_mock(tmp_path):
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})

    with patch("src.collectors.wallet_watchonly.requests.post",
               return_value=_err(500)):
        bal = c.get_balance(_ADDR)
    assert bal["_meta"]["mode"] == "mock"


def test_balance_network_exception_records_fallback_reason(tmp_path):
    import requests as _r

    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})

    with patch("src.collectors.wallet_watchonly.requests.post",
               side_effect=_r.exceptions.Timeout("upstream slow")):
        bal = c.get_balance(_ADDR)

    assert bal["_meta"]["mode"] == "mock"
    assert "Subscan" in bal["_meta"]["fallback_reason"]
    assert "Timeout" in bal["_meta"]["fallback_reason"]


# ---------------------------------------------------------------------------
# get_staking_info: live path
# ---------------------------------------------------------------------------

def test_staking_live_path_parses_delegations(tmp_path):
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})

    payload = {
        "code": 0,
        "data": {
            "list": [
                {
                    "validator_id": "5VAL_A",
                    "amount": str(int(50.0 * _PLANCK_PER_TAO)),
                    "share_pct": 60.0,
                    "apy": 9.2,
                },
                {
                    "validator_id": "5VAL_B",
                    "amount": str(int(33.3 * _PLANCK_PER_TAO)),
                    "share_pct": 40.0,
                    "apy": 11.7,
                },
            ],
            "total": str(int(83.3 * _PLANCK_PER_TAO)),
            "nominator_balance": "0",
        },
    }
    with patch("src.collectors.wallet_watchonly.requests.post",
               return_value=_ok(payload)):
        info = c.get_staking_info(_ADDR)

    assert info["_meta"]["mode"] == "live"
    assert info["num_delegations"] == 2
    assert info["total_staked"] == pytest.approx(83.3, abs=1e-3)
    apys = [d["apy_estimate"] for d in info["delegations"]]
    assert apys == [9.2, 11.7]
    assert info["estimated_apy_pct"] == pytest.approx((9.2 + 11.7) / 2, abs=0.1)


def test_staking_empty_delegation_list_yields_zero_totals(tmp_path):
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})

    payload = {"code": 0, "data": {"list": [], "total": "0",
                                    "nominator_balance": "0"}}
    with patch("src.collectors.wallet_watchonly.requests.post",
               return_value=_ok(payload)):
        info = c.get_staking_info(_ADDR)

    assert info["_meta"]["mode"] == "live"
    assert info["num_delegations"] == 0
    assert info["total_staked"] == 0.0
    assert info["estimated_apy_pct"] == 0.0


# ---------------------------------------------------------------------------
# API key threading + headers
# ---------------------------------------------------------------------------

def test_api_key_from_explicit_config_takes_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCAN_API_KEY", "from-env")
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "subscan_api_key": "from-config",
    })
    assert c.api_key == "from-config"


def test_api_key_falls_back_to_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSCAN_API_KEY", "from-env")
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})
    assert c.api_key == "from-env"


def test_api_key_header_sent_on_subscan_call(tmp_path):
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({
        "db_path": str(db),
        "use_mock_data": False,
        "subscan_api_key": "test-key-abc",
    })
    captured = {}

    def _capturing_post(url, json=None, headers=None, timeout=None, **kw):
        captured.update({"url": url, "headers": headers,
                          "json": json, "timeout": timeout})
        return _ok({"code": 0, "data": {"account": {"balance": "0", "reserved": "0"}}})

    with patch("src.collectors.wallet_watchonly.requests.post",
               side_effect=_capturing_post):
        c.get_balance(_ADDR)

    assert captured["headers"]["X-API-Key"] == "test-key-abc"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["timeout"] == c._subscan_timeout_s
    assert captured["json"] == {"key": _ADDR}


def test_no_api_key_header_when_none_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("SUBSCAN_API_KEY", raising=False)
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})
    captured = {}

    def _capturing_post(url, json=None, headers=None, timeout=None, **kw):
        captured.update({"headers": headers})
        return _ok({"code": 0, "data": {"account": {"balance": "0", "reserved": "0"}}})

    with patch("src.collectors.wallet_watchonly.requests.post",
               side_effect=_capturing_post):
        c.get_balance(_ADDR)

    assert "X-API-Key" not in captured["headers"]


# ---------------------------------------------------------------------------
# Mock-mode path unchanged + planck conversion
# ---------------------------------------------------------------------------

def test_mock_mode_does_not_call_subscan(tmp_path):
    """A use_mock_data=True instance must NEVER hit requests.post —
    even setting a key shouldn't matter."""
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({
        "db_path": str(db),
        "use_mock_data": True,
        "subscan_api_key": "ignored",
    })
    with patch("src.collectors.wallet_watchonly.requests.post") as post:
        bal = c.get_balance(_ADDR)
        info = c.get_staking_info(_ADDR)
    assert post.call_count == 0
    assert bal["_meta"]["mode"] == "mock"
    assert info["_meta"]["mode"] == "mock"


def test_planck_to_tao_handles_garbage_safely():
    assert WalletWatchOnlyCollector._planck_to_tao(None) == 0.0
    assert WalletWatchOnlyCollector._planck_to_tao("") == 0.0
    assert WalletWatchOnlyCollector._planck_to_tao("not-a-number") == 0.0
    # Real value: 1 TAO = 10^9 plancks
    assert WalletWatchOnlyCollector._planck_to_tao(_PLANCK_PER_TAO) == 1.0
    # Decimal string from Subscan
    assert WalletWatchOnlyCollector._planck_to_tao(
        str(int(2.5 * _PLANCK_PER_TAO))
    ) == 2.5


# ---------------------------------------------------------------------------
# Network-marked end-to-end test (opt-in via pytest -m network)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_subscan_live_against_real_api(tmp_path):
    """Hits the real Subscan public endpoint. Skipped by default; opt
    in with ``pytest -m network``. May fail on rate limits."""
    db = tmp_path / "ww.db"
    c = WalletWatchOnlyCollector({"db_path": str(db), "use_mock_data": False})
    bal = c.get_balance("5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY")
    # Either we got live data, or the public endpoint rate-limited us
    # — both are acceptable here. We just want to confirm no crash.
    assert bal["_meta"]["mode"] in ("live", "mock")
    assert "address" in bal
