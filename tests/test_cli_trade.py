"""
CLI smoke tests for the new ``trade`` and ``keystore`` subcommand
groups added in PR 2F.

These do not exercise the bittensor SDK or any real network — the
goal is to confirm the wiring (argparse / Click, error messages,
exit codes, JSON output shape) is correct. The deeper signing and
runner behaviour is covered in ``tests/test_trading_signer.py`` and
``tests/test_trading_runner.py``.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from tao_swarm.cli.tao_swarm import cli


def _run(*args):
    return CliRunner().invoke(cli, list(args))


# ---------------------------------------------------------------------------
# Help / discovery
# ---------------------------------------------------------------------------

def test_top_level_help_lists_trade_and_keystore():
    result = _run("--help")
    assert result.exit_code == 0
    assert "trade" in result.output
    assert "keystore" in result.output


def test_trade_help_lists_subcommands():
    result = _run("trade", "--help")
    assert result.exit_code == 0
    for sub in ("backtest", "run", "status"):
        assert sub in result.output


def test_keystore_help_lists_subcommands():
    result = _run("keystore", "--help")
    assert result.exit_code == 0
    for sub in ("init", "info", "verify"):
        assert sub in result.output


# ---------------------------------------------------------------------------
# trade backtest
# ---------------------------------------------------------------------------

def test_trade_backtest_runs_on_synthetic_snapshots(tmp_path):
    snapshots = [
        {"subnets": [{"netuid": 1, "tao_in": 100.0}],
         "history": {1: [(0.0, 90.0), (1.0, 100.0)]}},
        {"subnets": [{"netuid": 1, "tao_in": 130.0}],
         "history": {1: [(0.0, 110.0), (1.0, 130.0)]}},
    ]
    snap_path = tmp_path / "snaps.json"
    snap_path.write_text(json.dumps(snapshots))
    db = tmp_path / "bt.db"

    result = _run(
        "trade", "backtest",
        "--strategy", "momentum_rotation",
        "--snapshots", str(snap_path),
        "--threshold-pct", "0.05",
        "--slot-size-tao", "1.0",
        "--db", str(db),
        "--json",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["strategy_name"] == "momentum_rotation"
    assert payload["num_steps"] == 2
    assert payload["num_executed"] >= 1


def test_trade_backtest_rejects_missing_snapshots():
    result = _run(
        "trade", "backtest",
        "--strategy", "momentum_rotation",
        "--snapshots", "/no/such/file/__never__.json",
    )
    # Click validates `exists=True` on the path option → exit code 2.
    assert result.exit_code != 0


def test_trade_backtest_rejects_non_list_snapshots(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"not": "a list"}))
    result = _run(
        "trade", "backtest",
        "--strategy", "momentum_rotation",
        "--snapshots", str(bad),
    )
    assert result.exit_code != 0
    assert "list" in result.output.lower()


# ---------------------------------------------------------------------------
# trade run — argument validation (no real run; tests live mode rejection)
# ---------------------------------------------------------------------------

def test_trade_run_live_requires_keystore_path():
    result = _run(
        "trade", "run",
        "--strategy", "momentum_rotation",
        "--live",
    )
    assert result.exit_code != 0
    assert "keystore" in result.output.lower()


def test_trade_run_live_requires_strategy_opt_in(tmp_path):
    # Create a real keystore file so --keystore-path passes the
    # `exists=True` check; we don't unlock it because the next gate
    # (--live-trading) refuses first.
    ks = tmp_path / "ks.json"
    ks.write_text("{}")
    result = _run(
        "trade", "run",
        "--strategy", "momentum_rotation",
        "--live",
        "--keystore-path", str(ks),
    )
    assert result.exit_code != 0
    assert "live-trading" in result.output.lower() or "live_trading" in result.output.lower()


def test_trade_run_live_requires_env_var(tmp_path, monkeypatch):
    monkeypatch.delenv("TAO_LIVE_TRADING", raising=False)
    ks = tmp_path / "ks.json"
    ks.write_text("{}")
    result = _run(
        "trade", "run",
        "--strategy", "momentum_rotation",
        "--live", "--live-trading",
        "--keystore-path", str(ks),
    )
    assert result.exit_code != 0
    assert "TAO_LIVE_TRADING" in result.output


# ---------------------------------------------------------------------------
# trade status
# ---------------------------------------------------------------------------

def test_trade_status_on_empty_ledger(tmp_path):
    # Create an empty ledger first via PaperLedger so the file exists.
    from tao_swarm.trading import PaperLedger
    PaperLedger(str(tmp_path / "trades.db"))
    result = _run("trade", "status", "--ledger-db", str(tmp_path / "trades.db"))
    assert result.exit_code == 0
    assert "no trades" in result.output.lower()


def test_trade_status_shows_recorded_trades(tmp_path):
    from tao_swarm.trading import PaperLedger, TradeRecord
    db = tmp_path / "trades.db"
    ledger = PaperLedger(str(db))
    ledger.record_trade(TradeRecord(
        strategy="x", action="stake", target={"netuid": 1},
        amount_tao=1.0, price_tao=100.0, realised_pnl_tao=0.0, paper=True,
    ))
    result = _run("trade", "status", "--ledger-db", str(db))
    assert result.exit_code == 0
    assert "stake" in result.output


# ---------------------------------------------------------------------------
# keystore init/info/verify — round-trip
# ---------------------------------------------------------------------------

def test_keystore_init_info_verify_round_trip(tmp_path):
    ks = tmp_path / "kp.json"
    seed_hex = "11" * 32
    password = "supersecret-pw-with-len"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "keystore", "init",
            "--path", str(ks),
            "--label", "test-key",
            "--seed-hex", seed_hex,
        ],
        # init prompts for password (twice). Repeat with newlines.
        input=f"{password}\n{password}\n",
    )
    assert result.exit_code == 0, result.output
    assert ks.exists()

    info_result = runner.invoke(cli, ["keystore", "info", "--path", str(ks)])
    assert info_result.exit_code == 0
    assert "test-key" in info_result.output
    assert "argon2id" in info_result.output

    verify_result = runner.invoke(
        cli, ["keystore", "verify", "--path", str(ks)],
        input=f"{password}\n",
    )
    assert verify_result.exit_code == 0
    assert "OK" in verify_result.output


def test_keystore_init_rejects_invalid_hex(tmp_path):
    ks = tmp_path / "kp.json"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "keystore", "init",
            "--path", str(ks),
            "--seed-hex", "not-hex-at-all-zz",
        ],
    )
    assert result.exit_code != 0
    assert "hex" in result.output.lower()


def test_keystore_verify_wrong_password(tmp_path):
    ks = tmp_path / "kp.json"
    runner = CliRunner()
    runner.invoke(
        cli,
        [
            "keystore", "init",
            "--path", str(ks),
            "--seed-hex", "22" * 32,
        ],
        input="rightpasswordlongenough\nrightpasswordlongenough\n",
    )
    result = runner.invoke(
        cli, ["keystore", "verify", "--path", str(ks)],
        input="wrongpasswordlongenough\n",
    )
    assert result.exit_code != 0
    assert "wrong password" in result.output.lower()


def test_keystore_info_on_missing_file_clean_error(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["keystore", "info", "--path", str(tmp_path / "no_such.json")],
    )
    assert result.exit_code != 0
