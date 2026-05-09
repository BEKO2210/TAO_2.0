"""
Tests for the ``tao-swarm`` CLI.

Uses Click's ``CliRunner`` so nothing actually gets shelled out and
no network is touched (mock mode is the default and is enforced
explicitly where it matters).
"""

from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from src.cli.tao_swarm import _config, cli


# ---------------------------------------------------------------------------
# _config: mode resolution
# ---------------------------------------------------------------------------

def test_config_defaults_to_mock_offline_first():
    cfg = _config()
    assert cfg["use_mock_data"] is True
    assert cfg["network"] == "mock"


def test_config_explicit_live_keeps_network():
    cfg = _config(use_mock_data=False, network="finney")
    assert cfg["use_mock_data"] is False
    assert cfg["network"] == "finney"


def test_config_mock_forces_network_to_mock():
    """Even if the caller passes network=finney with use_mock_data=True,
    the chain collector must not contact finney."""
    cfg = _config(use_mock_data=True, network="finney")
    assert cfg["use_mock_data"] is True
    assert cfg["network"] == "mock"


def test_config_env_var_use_mock_off(monkeypatch):
    monkeypatch.setenv("TAO_USE_MOCK", "0")
    cfg = _config()
    assert cfg["use_mock_data"] is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_config_env_var_use_mock_on(monkeypatch, val):
    monkeypatch.setenv("TAO_USE_MOCK", val)
    cfg = _config()
    assert cfg["use_mock_data"] is True


# ---------------------------------------------------------------------------
# CLI surface: top-level help / version, mode banner, mode flags
# ---------------------------------------------------------------------------

def _run(*args):
    runner = CliRunner()
    return runner.invoke(cli, list(args))


def test_help_lists_all_commands():
    result = _run("--help")
    assert result.exit_code == 0
    for cmd in ("status", "subnets", "score", "watch", "market", "risk", "version"):
        assert cmd in result.output


def test_version_shows_mock_banner_by_default():
    result = _run("version")
    assert result.exit_code == 0
    assert "MODE: mock" in result.output


def test_version_shows_live_banner_when_live_flag_set():
    result = _run("--live", "version")
    assert result.exit_code == 0
    assert "MODE: live" in result.output


def test_network_finney_implies_live(monkeypatch, tmp_path):
    """`--network finney` without `--mock` should switch to live mode."""
    monkeypatch.chdir(tmp_path)
    result = _run("--network", "finney", "version")
    assert result.exit_code == 0
    assert "MODE: live" in result.output
    assert "network=finney" in result.output


def test_explicit_mock_beats_network_finney(monkeypatch, tmp_path):
    """Passing both --mock and --network finney must keep mock mode."""
    monkeypatch.chdir(tmp_path)
    result = _run("--mock", "--network", "finney", "version")
    assert result.exit_code == 0
    assert "MODE: mock" in result.output


# ---------------------------------------------------------------------------
# Data commands: subnets / market exercise the collector path in mock mode
# ---------------------------------------------------------------------------

def test_subnets_default_runs_in_mock_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _run("subnets", "--limit", "3")
    assert result.exit_code == 0
    assert "MODE: mock" in result.output
    assert "Bittensor Subnets" in result.output


def test_subnets_json_output_is_valid_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _run("subnets", "--limit", "2", "--json-output")
    assert result.exit_code == 0
    # JSON output should be on stdout — strip any log noise that might
    # appear before. Find the first '[' and parse from there.
    start = result.output.find("[")
    assert start >= 0
    payload = json.loads(result.output[start:])
    assert isinstance(payload, list)
    assert all("netuid" in s for s in payload)


def test_market_runs_and_shows_mode_banner(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _run("market")
    assert result.exit_code == 0
    assert "MODE: mock" in result.output
    assert "Market" in result.output


def test_live_request_without_sdk_shows_fallback_warning(tmp_path, monkeypatch):
    """When --live is requested but bittensor isn't importable, the CLI
    must surface the fallback reason on the subnets command output —
    that's how the user knows their --live flag didn't actually take."""
    monkeypatch.chdir(tmp_path)
    # Force the import path to return None, simulating a clean env
    import src.collectors.chain_readonly as chain_module
    monkeypatch.setattr(chain_module, "_try_import_bittensor", lambda: None)

    result = _run("--live", "subnets", "--limit", "1")
    assert result.exit_code == 0
    assert "MODE: live" in result.output
    assert "fallback" in result.output.lower()
    assert "bittensor" in result.output.lower()
