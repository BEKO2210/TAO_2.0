"""
TAO Swarm CLI

Click-based command line interface for the TAO/Bittensor Multi-Agent System.

Commands:
    status      Show system status
    check       Run system check
    subnets     List subnets
    score       Score a subnet
    watch       Watch a wallet (read-only!)
    unwatch     Stop watching a wallet
    market      Show market data
    risk        Show risk review
    run         Start orchestrator run
    report      Generate report
    dashboard   Start dashboard
    version     Show version

All wallet operations are read-only. No trades are auto-executed.
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import click

# ── Setup logging ─────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Version ───────────────────────────────────────────────────────────────

VERSION = "1.0.0"

# ── Default config ────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "db_dir": os.environ.get("TAO_DATA_DIR", "data"),
    "network": os.environ.get("TAO_NETWORK", "mock"),
    "cache_ttl": 300,
    "request_timeout": 15,
}


def _config(use_mock_data: bool | None = None, network: str | None = None) -> dict:
    """
    Build runtime config dict.

    Args:
        use_mock_data: If set, forces collectors offline (True) or live
            (False). When None, falls back to TAO_USE_MOCK env var, then
            defaults to True (offline-first per swarm convention).
        network: Bittensor network for chain reads ("finney", "test",
            "mock"). Falls back to TAO_NETWORK env var, then "mock".
    """
    if use_mock_data is None:
        env_val = os.environ.get("TAO_USE_MOCK", "").lower()
        if env_val in ("1", "true", "yes", "on"):
            use_mock_data = True
        elif env_val in ("0", "false", "no", "off"):
            use_mock_data = False
        else:
            use_mock_data = True

    if network is None:
        network = DEFAULT_CONFIG["network"]
    # In mock mode, force network='mock' so the chain collector doesn't
    # try to contact finney even if the user only flipped --mock.
    if use_mock_data:
        network = "mock"

    return {
        **DEFAULT_CONFIG,
        "db_path": f"{DEFAULT_CONFIG['db_dir']}/chain_cache.db",
        "use_mock_data": use_mock_data,
        "network": network,
    }


def _mode_banner(config: dict) -> str:
    """One-line banner showing which data source the command will use."""
    if config.get("use_mock_data", True):
        return click.style(
            "  MODE: mock (offline fixtures)  — pass --live for real data",
            fg="yellow",
        )
    network = config.get("network", "finney")
    return click.style(
        f"  MODE: live (network={network})  — pass --mock for offline fixtures",
        fg="green",
    )


# ── Custom Group ──────────────────────────────────────────────────────────

class TaoSwarmCLI(click.Group):
    """Custom CLI group with shared options."""

    def format_help(self, ctx, formatter):
        formatter.write("\n")
        formatter.write("  TAO Swarm — Bittensor Multi-Agent Intelligence System\n")
        formatter.write(f"  Version: {VERSION}\n\n")
        formatter.write("  All operations are read-only by default.\n")
        formatter.write("  No wallet seeds or private keys are ever stored.\n")
        formatter.write("  No trades are auto-executed.\n\n")
        formatter.write("  Commands:\n")
        for name, cmd in self.commands.items():
            formatter.write(f"    {name:12}  {cmd.get_short_help_str()}\n")
        formatter.write("\n  Run 'tao-swarm COMMAND --help' for details.\n\n")


@click.group(cls=TaoSwarmCLI, invoke_without_command=False)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option(
    "--live/--mock",
    "live_mode",
    default=None,
    help=(
        "Use live upstream data (--live) or offline fixtures (--mock). "
        "Default: mock (offline-first). Override the default permanently "
        "with TAO_USE_MOCK=0/1."
    ),
)
@click.option(
    "--network",
    type=click.Choice(["mock", "finney", "test"]),
    default=None,
    help=(
        "Bittensor network for chain reads. Implies --live unless "
        "'mock' is selected. Defaults to TAO_NETWORK or 'mock'."
    ),
)
@click.pass_context
def cli(ctx, verbose, live_mode, network):
    """TAO Swarm CLI — Bittensor Multi-Agent Intelligence System."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # If the user passed --network finney|test, that's an opt-in to live
    # mode unless they also explicitly passed --mock.
    if network in ("finney", "test") and live_mode is None:
        live_mode = True

    # Symmetric default: --live without --network should target the
    # mainnet, not the mock pseudo-network (chain_readonly treats
    # network=mock as an alias for use_mock_data=True).
    if live_mode is True and network is None:
        network = "finney"

    use_mock_data: bool | None
    if live_mode is None:
        use_mock_data = None
    else:
        use_mock_data = not live_mode

    ctx.ensure_object(dict)
    ctx.obj["config"] = _config(use_mock_data=use_mock_data, network=network)


# ── status ────────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def status(ctx):
    """Show system status."""
    config = ctx.obj["config"]

    click.echo(click.style("\n=== TAO Swarm System Status ===", fg="blue", bold=True))

    # Check databases
    db_dir = Path(config["db_dir"])
    dbs = list(db_dir.glob("*.db")) if db_dir.exists() else []
    click.echo(f"\nDatabase directory: {db_dir.absolute()}")
    click.echo(f"Database files: {len(dbs)}")
    for db in dbs:
        size = db.stat().st_size
        size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.1f} MB"
        click.echo(f"  {db.name:25s} {size_str}")

    # Check Python
    click.echo(f"\nPython: {sys.version.split()[0]}")
    click.echo(f"Platform: {sys.platform}")

    # Module status (importable check, not filesystem-path check —
    # ``Path("tao_swarm.collectors")`` looks for a literal dotted directory
    # name and always reports "not found" even when the package is
    # importable, which the previous implementation did).
    import importlib.util as _ilu
    modules = [
        ("Collectors", "tao_swarm.collectors"),
        ("Scoring", "tao_swarm.scoring"),
        ("Dashboard", "tao_swarm.dashboard"),
    ]
    click.echo("\nModules:")
    for name, mod_path in modules:
        spec = _ilu.find_spec(mod_path)
        ok = spec is not None
        status_text = "found" if ok else "not found"
        color = "green" if ok else "red"
        click.echo(f"  {name:15s} {mod_path:20s} ", nl=False)
        click.echo(click.style(status_text, fg=color))

    # Mode
    click.echo("\n" + click.style("Mode: READ-ONLY", fg="green", bold=True))
    click.echo(click.style("Safety: No secrets stored, no auto-trades", fg="green"))
    click.echo()


# ── check ─────────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def check(ctx):
    """Run system check."""
    click.echo(click.style("\n=== System Check ===", fg="blue", bold=True))

    checks = []

    # Python version
    py_ok = sys.version_info >= (3, 10)
    checks.append(("Python 3.10+", py_ok, f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"))

    # Core dependencies
    deps = ["click", "requests", "sqlite3"]
    for dep in deps:
        try:
            if dep == "sqlite3":
                __import__("sqlite3")
            else:
                __import__(dep)
            checks.append((f"{dep} installed", True, "OK"))
        except ImportError:
            checks.append((f"{dep} installed", False, "MISSING"))

    # Optional dependencies
    for dep in ["streamlit", "pandas", "plotly"]:
        try:
            __import__(dep)
            checks.append((f"{dep} installed", True, "OK"))
        except ImportError:
            checks.append((f"{dep} installed", False, "optional"))

    # Data directory
    db_dir = Path(ctx.obj["config"]["db_dir"])
    db_ok = db_dir.exists() or db_dir.mkdir(parents=True, exist_ok=True)
    checks.append(("Data directory", bool(db_ok), str(db_dir)))

    # Display results
    click.echo()
    for name, ok, detail in checks:
        symbol = "PASS" if ok else "FAIL"
        color = "green" if ok else "red"
        click.echo(f"  [{click.style(symbol, fg=color)}] {name:25s} {detail}")

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    click.echo(f"\nResult: {passed}/{total} checks passed")
    click.echo()


# ── subnets ───────────────────────────────────────────────────────────────

@cli.command()
@click.option("--limit", "-l", default=10, help="Maximum number of subnets to show")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
@click.pass_context
def subnets(ctx, limit, json_output):
    """List all Bittensor subnets."""
    try:
        from tao_swarm.collectors.chain_readonly import ChainReadOnlyCollector
    except ImportError:
        from collectors.chain_readonly import ChainReadOnlyCollector

    config = ctx.obj["config"]
    collector = ChainReadOnlyCollector(config)
    subnet_list = collector.get_subnet_list()

    if json_output:
        click.echo(json.dumps(subnet_list[:limit], indent=2, default=str))
        return

    click.echo(click.style("\n=== Bittensor Subnets ===", fg="blue", bold=True))
    click.echo(_mode_banner(config))
    if collector._mock_fallback_reason:
        click.echo(click.style(
            f"  fallback: {collector._mock_fallback_reason}", fg="yellow",
        ))
    click.echo()
    # Detect chain-rich payload (post-#28 shape) vs legacy mock shape.
    # Rich entries carry ``tao_in`` / ``symbol`` / nested ``identity``;
    # legacy mock entries have ``num_neurons`` / ``block`` instead.
    sample = subnet_list[0] if subnet_list else {}
    has_rich = "tao_in" in sample or "symbol" in sample

    if has_rich:
        click.echo(
            f"  {'ID':>4s}  {'Name':20s} {'Sym':>3s} "
            f"{'TAO_in':>10s} {'Volume':>12s}  Description"
        )
        click.echo(
            f"  {'-'*4:>4s}  {'-'*20:20s} {'-'*3:>3s} "
            f"{'-'*10:>10s} {'-'*12:>12s}  {'-'*30}"
        )
        for s in subnet_list[:limit]:
            ident = s.get("identity") or {}
            desc = (ident.get("description") or "")[:40]
            tao_in = float(s.get("tao_in") or 0.0)
            volume = float(s.get("subnet_volume") or 0.0)
            symbol = (s.get("symbol") or "?")[:3]
            click.echo(
                f"  {int(s['netuid']):>4d}  {str(s['name'])[:20]:20s} {symbol:>3s} "
                f"{tao_in:>10,.0f} {volume:>12,.0f}  {desc}"
            )
    else:
        click.echo(
            f"  {'ID':>4s}  {'Name':20s} "
            f"{'Neurons':>8s} {'Emission':>10s} {'Block':>10s}"
        )
        click.echo(
            f"  {'-'*4:>4s}  {'-'*20:20s} "
            f"{'-'*8:>8s} {'-'*10:>10s} {'-'*10:>10s}"
        )
        for s in subnet_list[:limit]:
            click.echo(
                f"  {s['netuid']:>4d}  {s['name']:20s} "
                f"{s.get('num_neurons', 0):>8d} "
                f"{s.get('emission', 0):>10.2f} "
                f"{s.get('block', 0):>10d}"
            )

    click.echo(f"\n  Total: {len(subnet_list)} subnets")
    click.echo()


# ── score ─────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("netuid", type=int)
@click.option("--detailed", "-d", is_flag=True, help="Show detailed breakdown")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
@click.pass_context
def score(ctx, netuid, detailed, json_output):
    """Score a specific subnet by netuid."""
    try:
        from tao_swarm.collectors.subnet_metadata import SubnetMetadataCollector
        from tao_swarm.scoring.subnet_score import SubnetScorer
    except ImportError:
        from collectors.subnet_metadata import SubnetMetadataCollector
        from scoring.subnet_score import SubnetScorer

    config = ctx.obj["config"]

    click.echo(click.style(f"\n=== Scoring Subnet {netuid} ===", fg="blue", bold=True))
    click.echo(_mode_banner(config))

    # Build profile
    meta_collector = SubnetMetadataCollector(config)
    with click.progressbar(length=3, label="Collecting data") as bar:
        profile = meta_collector.build_subnet_profile(netuid)
        bar.update(1)
        time.sleep(0.1)
        bar.update(1)

    # Score
    scorer = SubnetScorer(config)
    subnet_data = {"netuid": netuid, "profile": profile}
    result = scorer.score_subnet(subnet_data)
    bar.update(1)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
        return

    # Display
    click.echo()
    total = result["total_score"]
    color = "green" if total >= 75 else "yellow" if total >= 50 else "red"
    click.echo(f"  Total Score: {click.style(f'{total:.1f}/100', fg=color, bold=True)}")

    rec = result["recommendation"]
    click.echo(f"  Recommendation: {click.style(rec['label'], fg=color, bold=True)}")
    click.echo(f"  Description: {rec['description']}")

    if detailed:
        click.echo()
        click.echo("  Breakdown:")
        for criterion, value in result["breakdown"].items():
            weight = result["weights"][criterion]
            weighted = value * weight
            click.echo(
                f"    {criterion:20s} {value:>6.1f} x {weight:4.2f} = {weighted:>6.2f}"
            )

    click.echo()


# ── watch ─────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("address")
@click.option("--label", "-l", default="", help="Label for the wallet")
@click.pass_context
def watch(ctx, address, label):
    """Watch a wallet address (read-only)."""
    try:
        from tao_swarm.collectors.wallet_watchonly import WalletWatchOnlyCollector
    except ImportError:
        from collectors.wallet_watchonly import WalletWatchOnlyCollector

    config = ctx.obj["config"]
    collector = WalletWatchOnlyCollector(config)

    click.echo(click.style("\n=== Watch Wallet ===", fg="blue", bold=True))
    click.echo()

    # Validate address
    is_valid = collector.validate_address(address)
    if not is_valid:
        click.echo(click.style(f"  ERROR: Invalid SS58 address: {address}", fg="red"))
        click.echo()
        sys.exit(1)

    click.echo(click.style("  Address format: VALID (SS58)", fg="green"))

    # Add to watch list
    added = collector.add_watch_address(address, label)
    if added:
        click.echo(click.style(f"  Added to watch list: {address[:20]}...", fg="green"))
        if label:
            click.echo(f"  Label: {label}")
    else:
        click.echo(click.style("  Address is already being watched", fg="yellow"))

    # Show balance
    balance = collector.get_balance(address)
    click.echo("\n  Balance:")
    click.echo(f"    Free:      {balance.get('free', 0):.6f} TAO")
    click.echo(f"    Reserved:  {balance.get('reserved', 0):.6f} TAO")
    click.echo(f"    Total:     {balance.get('total', 0):.6f} TAO")

    # Show staking
    staking = collector.get_staking_info(address)
    click.echo("\n  Staking:")
    click.echo(f"    Total Staked: {staking.get('total_staked', 0):.6f} TAO")
    click.echo(f"    Delegations:  {staking.get('num_delegations', 0)}")
    click.echo(f"    Est. APY:     {staking.get('estimated_apy_pct', 0):.2f}%")

    click.echo()
    click.echo(click.style("  SAFE: Only public address watched. No private keys stored.", fg="green"))
    click.echo()


# ── unwatch ───────────────────────────────────────────────────────────────

@cli.command()
@click.argument("address")
@click.pass_context
def unwatch(ctx, address):
    """Stop watching a wallet address."""
    try:
        from tao_swarm.collectors.wallet_watchonly import WalletWatchOnlyCollector
    except ImportError:
        from collectors.wallet_watchonly import WalletWatchOnlyCollector

    config = ctx.obj["config"]
    collector = WalletWatchOnlyCollector(config)

    click.echo(click.style("\n=== Unwatch Wallet ===", fg="blue", bold=True))

    removed = collector.remove_watch_address(address)
    if removed:
        click.echo(click.style(f"\n  Removed: {address[:20]}...", fg="green"))
    else:
        click.echo(click.style("\n  Address not found in watch list", fg="yellow"))

    click.echo()


# ── market ────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--days", "-d", default=0, help="Show historical data for N days")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
@click.pass_context
def market(ctx, days, json_output):
    """Show TAO market data."""
    try:
        from tao_swarm.collectors.market_data import MarketDataCollector
    except ImportError:
        from collectors.market_data import MarketDataCollector

    config = ctx.obj["config"]
    collector = MarketDataCollector(config)

    click.echo(click.style("\n=== TAO Market Data ===", fg="blue", bold=True))
    click.echo(_mode_banner(config))
    if collector._mock_fallback_reason:
        click.echo(click.style(
            f"  fallback: {collector._mock_fallback_reason}", fg="yellow",
        ))

    # Current price
    price = collector.get_tao_price()
    if "error" not in price:
        click.echo()
        click.echo(f"  TAO/USD:    ${price.get('price_usd', 0):,.2f}")
        click.echo(f"  TAO/BTC:    {price.get('price_btc', 0):.8f}")
        change = price.get('change_24h_pct', 0)
        color = "green" if change >= 0 else "red"
        click.echo(f"  24h Change: {click.style(f'{change:+.2f}%', fg=color)}")
        click.echo(f"  Market Cap: ${price.get('market_cap_usd', 0)/1e9:.2f}B")
        click.echo(f"  24h Volume: ${price.get('volume_24h_usd', 0)/1e6:.2f}M")

    # Full market data
    market_data = collector.get_market_data()
    if "error" not in market_data:
        click.echo()
        click.echo("  Price Change:")
        for period, val in market_data.get("price_change", {}).items():
            color = "green" if val >= 0 else "red"
            click.echo(f"    {period:10s}: {click.style(f'{val:+.2f}%', fg=color)}")

        supply = market_data.get("supply", {})
        click.echo("\n  Supply:")
        click.echo(f"    Circulating: {supply.get('circulating', 0):,.0f}")
        click.echo(f"    Total:       {supply.get('total', 0):,.0f}")
        click.echo(f"    Max:         {supply.get('max', 0):,.0f}")

    # Historical data
    if days > 0:
        click.echo(f"\n  Historical data ({days} days):")
        history = collector.get_historical_data(days)
        if history:
            if json_output:
                click.echo(json.dumps(history, indent=2, default=str))
            else:
                click.echo(f"    Entries: {len(history)}")
                if history:
                    click.echo(f"    First:   {history[0]['date']} @ ${history[0]['price_usd']:,.2f}")
                    click.echo(f"    Last:    {history[-1]['date']} @ ${history[-1]['price_usd']:,.2f}")
                    pct_change = ((history[-1]['price_usd'] - history[0]['price_usd']) / history[0]['price_usd'] * 100)
                    color = "green" if pct_change >= 0 else "red"
                    click.echo(f"    Change:  {click.style(f'{pct_change:+.2f}%', fg=color)}")
        else:
            click.echo(click.style("    No data available", fg="yellow"))

    if json_output and not days:
        click.echo(json.dumps(market_data, indent=2, default=str))

    click.echo()


# ── risk ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--subnet", "-s", type=int, help="Check risk for a specific subnet")
@click.option("--repo", "-r", help="Check risk for a GitHub repo URL")
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
@click.pass_context
def risk(ctx, subnet, repo, json_output):
    """Show risk review."""
    try:
        from tao_swarm.scoring.risk_score import RiskScorer
    except ImportError:
        from scoring.risk_score import RiskScorer

    scorer = RiskScorer()
    config = ctx.obj["config"]

    click.echo(click.style("\n=== Risk Review ===", fg="blue", bold=True))
    click.echo(_mode_banner(config))

    if subnet:
        click.echo(f"\n  Assessing subnet {subnet}...")
        # Build mock subnet data
        subnet_data = {
            "github": {
                "stars": 150,
                "forks": 30,
                "updated_at": "2024-01-15T00:00:00Z",
                "license": "MIT",
                "archived": False,
                "is_fork": False,
                "open_issues": 12,
            },
            "scores": {"activity_score": 45},
        }
        result = scorer.assess_subnet_risk(subnet_data)
    elif repo:
        click.echo(f"\n  Assessing repo {repo}...")
        repo_data = {
            "stars": 50,
            "forks": 10,
            "updated_at": "2024-01-15T00:00:00Z",
            "license": "MIT",
            "archived": False,
            "is_fork": False,
            "open_issues": 20,
        }
        result = scorer.assess_repo_risk(repo_data)
    else:
        # General risk overview
        context = {
            "repo": {
                "stars": 100,
                "forks": 25,
                "updated_at": "2024-02-01T00:00:00Z",
                "license": "MIT",
                "archived": False,
                "is_fork": False,
                "open_issues": 15,
            },
            "market": {
                "change_24h_pct": -5.2,
                "market_cap_usd": 500_000_000,
                "volume_24h_usd": 5_000_000,
            },
            "wallet": {"address": "", "balance": 100, "recent_tx_count": 5},
            "reputation": {"twitter_followers": 5000, "sentiment": "neutral", "reports": 0},
        }
        result = scorer.calculate_risk(context)

    if json_output:
        click.echo(json.dumps(result, indent=2, default=str))
        return

    total = result.get("total_risk", 0)
    level = result.get("risk_level", "UNKNOWN")
    color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "red"}.get(level, "white")

    click.echo()
    click.echo(f"  Total Risk: {click.style(f'{total:.1f}/100', fg=color, bold=True)}")
    click.echo(f"  Risk Level: {click.style(level, fg=color, bold=True)}")

    if result.get("veto"):
        click.echo(click.style("\n  !!! VETO TRIGGERED !!!", fg="red", bold=True))
        click.echo(f"  Reason: {result.get('veto_reason', 'Critical risk detected')}")

    click.echo()
    click.echo("  Categories:")
    categories = result.get("categories", {})
    for cat, data in categories.items():
        cat_score = data.get("score", 0)
        cat_color = "green" if cat_score < 25 else "yellow" if cat_score < 45 else "red"
        click.echo(f"    {cat:15s}: {click.style(f'{cat_score:.1f}', fg=cat_color)}")

    findings = result.get("findings", [])
    if findings:
        click.echo(f"\n  Findings ({len(findings)}):")
        for f in findings[:10]:
            sev = f.get("severity", "LOW")
            sev_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "red"}.get(sev, "white")
            click.echo(f"    [{click.style(sev, fg=sev_color)}] {f.get('pattern', 'unknown')}")

    click.echo()


# ── run ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--agent", "-a", help="Run a specific agent")
@click.option("--task", "-t", help="Task JSON string")
@click.option("--dry-run", is_flag=True, help="Simulate run without executing")
@click.pass_context
def run(ctx, agent, task, dry_run):
    """
    Execute an orchestrator task end-to-end.

    Without ``--task``, runs ``system_check`` as the default smoke
    task. With ``--task '{"type": "subnet_discovery", ...}'`` runs
    the given task through the full orchestrator (ApprovalGate +
    TaskRouter + agent.run + result wrap). With ``--agent NAME``,
    only registers the single named agent; otherwise registers all
    15 built-ins (matches the ``capabilities`` command).
    """
    click.echo(click.style("\n=== Orchestrator Run ===", fg="blue", bold=True))
    config = ctx.obj["config"]
    click.echo(_mode_banner(config))

    # Parse --task before doing anything expensive so a typo aborts early.
    if task:
        try:
            task_dict = json.loads(task)
        except json.JSONDecodeError as exc:
            click.echo(click.style(
                f"  Invalid task JSON: {exc}", fg="red",
            ), err=True)
            raise click.Abort()
    else:
        task_dict = {"type": "system_check"}
        click.echo(click.style(
            "  No --task given — running default 'system_check'", fg="yellow",
        ))

    if dry_run:
        click.echo(click.style(
            "\n  [DRY RUN] Task validated; no agent will be invoked.", fg="yellow",
        ))
        click.echo(f"  Task: {json.dumps(task_dict, indent=2)}")
        return

    # Lazy import — keeps the CLI smoke-light when this command isn't called.
    try:
        from tao_swarm.agents import (
            DashboardDesignAgent,
            DocumentationAgent,
            FullstackDevAgent,
            InfraDevopsAgent,
            MarketTradeAgent,
            MinerEngineeringAgent,
            ProtocolResearchAgent,
            QATestAgent,
            RiskSecurityAgent,
            SubnetDiscoveryAgent,
            SubnetScoringAgent,
            SystemCheckAgent,
            TrainingExperimentAgent,
            ValidatorEngineeringAgent,
            WalletWatchAgent,
        )
        from tao_swarm.orchestrator import SwarmOrchestrator, load_plugins
    except ImportError as exc:
        click.echo(click.style(
            f"  Import failed: {exc}", fg="red",
        ), err=True)
        raise click.Abort()

    all_classes = {
        "system_check_agent": SystemCheckAgent,
        "protocol_research_agent": ProtocolResearchAgent,
        "subnet_discovery_agent": SubnetDiscoveryAgent,
        "subnet_scoring_agent": SubnetScoringAgent,
        "wallet_watch_agent": WalletWatchAgent,
        "market_trade_agent": MarketTradeAgent,
        "risk_security_agent": RiskSecurityAgent,
        "miner_engineering_agent": MinerEngineeringAgent,
        "validator_engineering_agent": ValidatorEngineeringAgent,
        "training_experiment_agent": TrainingExperimentAgent,
        "infra_devops_agent": InfraDevopsAgent,
        "dashboard_design_agent": DashboardDesignAgent,
        "fullstack_dev_agent": FullstackDevAgent,
        "qa_test_agent": QATestAgent,
        "documentation_agent": DocumentationAgent,
    }

    orch = SwarmOrchestrator({**config, "wallet_mode": "WATCH_ONLY"})
    if agent:
        cls = all_classes.get(agent)
        if cls is None:
            click.echo(click.style(
                f"  Unknown agent '{agent}'. Known: "
                f"{sorted(all_classes.keys())}", fg="red",
            ), err=True)
            raise click.Abort()
        orch.register_agent(cls(config))
    else:
        for cls in all_classes.values():
            try:
                orch.register_agent(cls(config))
            except Exception as exc:  # noqa: BLE001 — surface but don't crash
                click.echo(click.style(
                    f"  warning: failed to register {cls.__name__}: {exc}",
                    fg="yellow",
                ), err=True)

    # Pull in any user plug-ins from TAO_PLUGIN_PATHS (or skip
    # silently when the env var isn't set).
    load_plugins(orch)

    click.echo(f"\n  Registered agents: {len(orch.agents)}")
    click.echo(f"  Task: {json.dumps(task_dict, indent=2)}")
    click.echo()

    result = orch.execute_task(task_dict)

    status = result.get("status")
    color = {"success": "green", "blocked": "yellow", "error": "red"}.get(
        status, "white",
    )
    click.echo(click.style(f"  Status: {status}", fg=color, bold=True))
    if "agent_name" in result and result["agent_name"]:
        click.echo(f"  Agent:  {result['agent_name']}")
    if "agent_result_status" in result and result["agent_result_status"]:
        click.echo(f"  Agent status: {result['agent_result_status']}")
    if "classification" in result:
        click.echo(f"  Classification: {result['classification']}")
    if status == "error" and "error" in result:
        click.echo(click.style(f"  Error: {result['error']}", fg="red"))
    output = result.get("output")
    if isinstance(output, dict):
        click.echo("\n  Output:")
        click.echo(json.dumps(output, indent=2, default=str)[:2000])

    click.echo()


# ── report ────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--type", "report_type", type=click.Choice(["subnet", "wallet", "market", "system", "full"]),
              default="full", help="Report type")
@click.option("--output", "-o", help="Output file path")
@click.option("--format", "output_format", type=click.Choice(["json", "markdown", "text"]),
              default="text", help="Output format")
@click.option("--subnet", "-s", type=int, help="Subnet ID for subnet report")
@click.pass_context
def report(ctx, report_type, output, output_format, subnet):
    """Generate a report."""
    click.echo(click.style(f"\n=== {report_type.upper()} Report ===", fg="blue", bold=True))

    if report_type == "subnet" and subnet:
        try:
            from tao_swarm.scoring.subnet_score import SubnetScorer
        except ImportError:
            from scoring.subnet_score import SubnetScorer

        scorer = SubnetScorer()
        result = scorer.generate_score_report(subnet)

        if output_format == "json":
            content = json.dumps(result, indent=2, default=str)
        elif output_format == "markdown":
            latest = result.get("latest_score", {})
            content = f"""# Subnet {subnet} Report

## Score: {latest.get('score', 'N/A') if latest else 'N/A'}

- **Subnet ID**: {subnet}
- **Scored At**: {time.strftime('%Y-%m-%d %H:%M:%S') if result.get('generated_at') else 'N/A'}
- **Trend**: {result.get('trend', 'N/A')}
- **Total Scores**: {result.get('score_count', 0)}

*Generated by TAO Swarm v{VERSION}*
"""
        else:
            content = f"Subnet {subnet} Report:\n"
            if result.get("latest_score"):
                ls = result["latest_score"]
                content += f"  Score: {ls.get('score', 'N/A')}\n"
            content += f"  Trend: {result.get('trend', 'N/A')}\n"
            content += f"  History entries: {result.get('score_count', 0)}\n"

        if output:
            Path(output).write_text(content)
            click.echo(click.style(f"\n  Report written to: {output}", fg="green"))
        else:
            click.echo()
            click.echo(content)

    elif report_type == "system":
        content = f"""# System Report

- **Version**: {VERSION}
- **Time**: {time.strftime('%Y-%m-%d %H:%M:%S')}
- **Mode**: READ-ONLY
- **Python**: {sys.version.split()[0]}
- **Platform**: {sys.platform}

All systems operational.
"""
        if output:
            Path(output).write_text(content)
            click.echo(click.style(f"\n  Report written to: {output}", fg="green"))
        else:
            click.echo()
            click.echo(content)

    else:
        click.echo(f"\n  Report type: {report_type}")
        click.echo("  Use --output to save to file, --format for output format")

    click.echo()


# ── dashboard ─────────────────────────────────────────────────────────────

@cli.command()
@click.option("--port", "-p", default=8501, help="Dashboard port")
@click.option("--host", "-h", default="127.0.0.1", help="Dashboard host")
@click.option("--no-browser", is_flag=True, help="Don't open browser")
@click.pass_context
def dashboard(ctx, port, host, no_browser):
    """Start the Streamlit dashboard."""
    click.echo(click.style("\n=== Starting Dashboard ===", fg="blue", bold=True))

    dashboard_path = Path("tao_swarm/dashboard/app.py")
    if not dashboard_path.exists():
        click.echo(click.style("  Dashboard not found at src/dashboard/app.py", fg="red"))
        sys.exit(1)

    click.echo(f"  Host: {host}")
    click.echo(f"  Port: {port}")
    click.echo(f"  File: {dashboard_path.absolute()}")

    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(dashboard_path),
        "--server.port", str(port),
        "--server.address", host,
    ]
    if no_browser:
        cmd.extend(["--server.headless", "true"])

    click.echo(click.style("\n  Starting streamlit...", fg="green"))
    click.echo(f"  Command: {' '.join(cmd)}\n")

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        click.echo(click.style("\n  Dashboard stopped", fg="yellow"))


# ── version ───────────────────────────────────────────────────────────────

@cli.command()
@click.option("--json-output", "-j", is_flag=True, help="Output as JSON")
@click.option("--plugin-paths", multiple=True,
              help="Additional paths to scan for plug-in agents.")
@click.pass_context
def capabilities(ctx, json_output, plugin_paths):
    """List all agent capabilities (built-ins + loaded plug-ins).

    Builds a temporary orchestrator with every built-in agent registered
    plus any plug-ins on TAO_PLUGIN_PATHS / --plugin-paths, then prints
    the full capability table — what tasks the swarm can execute right
    now and which agent handles each one.
    """
    try:
        from tao_swarm.agents import (
            DashboardDesignAgent,
            DocumentationAgent,
            FullstackDevAgent,
            InfraDevopsAgent,
            MarketTradeAgent,
            MinerEngineeringAgent,
            ProtocolResearchAgent,
            QATestAgent,
            RiskSecurityAgent,
            SubnetDiscoveryAgent,
            SubnetScoringAgent,
            SystemCheckAgent,
            TrainingExperimentAgent,
            ValidatorEngineeringAgent,
            WalletWatchAgent,
        )
        from tao_swarm.orchestrator import SwarmOrchestrator, load_plugins
    except ImportError as exc:
        click.echo(click.style(f"Import failed: {exc}", fg="red"), err=True)
        raise click.Abort()

    config = ctx.obj["config"]
    orch = SwarmOrchestrator({**config, "wallet_mode": "WATCH_ONLY"})
    for cls in (
        SystemCheckAgent, ProtocolResearchAgent, SubnetDiscoveryAgent,
        SubnetScoringAgent, WalletWatchAgent, MarketTradeAgent,
        RiskSecurityAgent, MinerEngineeringAgent, ValidatorEngineeringAgent,
        TrainingExperimentAgent, InfraDevopsAgent, DashboardDesignAgent,
        FullstackDevAgent, QATestAgent, DocumentationAgent,
    ):
        try:
            orch.register_agent(cls(config))
        except Exception as exc:
            click.echo(click.style(
                f"  warning: failed to register {cls.__name__}: {exc}",
                fg="yellow",
            ), err=True)

    summary = load_plugins(orch, paths=list(plugin_paths) or None)
    capabilities_list = orch.task_router.list_capabilities()
    routable = sorted(orch.task_router.list_task_types())

    if json_output:
        click.echo(json.dumps({
            "agents": orch.task_router.list_agents(),
            "task_types": routable,
            "capabilities": capabilities_list,
            "plugins": summary.as_dict(),
        }, indent=2, default=str))
        return

    click.echo(click.style("\n=== TAO Swarm Capabilities ===", fg="blue", bold=True))
    click.echo(_mode_banner(config))
    if summary.loaded:
        click.echo(click.style(
            f"  + {len(summary.loaded)} plug-in(s) loaded: "
            f"{', '.join(summary.loaded)}", fg="green",
        ))
    click.echo()
    click.echo(f"  {'task_type':<30} {'agent':<28} description")
    click.echo(f"  {'-'*30} {'-'*28} {'-'*30}")
    if capabilities_list:
        for cap in sorted(capabilities_list, key=lambda c: c["task_type"]):
            desc = (cap.get("description") or "")[:35]
            click.echo(
                f"  {cap['task_type'][:30]:<30} "
                f"{cap['agent'][:28]:<28} "
                f"{desc}"
            )
        click.echo()
    else:
        click.echo("  (no agent declares AGENT_CAPABILITIES yet — "
                   "see docs/plugins.md for the format)")
    click.echo()
    click.echo(f"  Routable task_types ({len(routable)}):")
    cols = 3
    for i in range(0, len(routable), cols):
        row = routable[i:i + cols]
        click.echo("    " + "  ".join(f"{t:<24}" for t in row))
    click.echo()


@cli.command()
@click.pass_context
def version(ctx):
    """Show version information."""
    config = ctx.obj["config"]
    click.echo(click.style("\n=== TAO Swarm ===", fg="blue", bold=True))
    click.echo()
    click.echo(f"  Version:    {VERSION}")
    click.echo(f"  Python:     {sys.version.split()[0]}")
    click.echo(f"  Platform:   {sys.platform}")
    click.echo("  Mode:       READ-ONLY (SAFE)")
    click.echo(_mode_banner(config))
    click.echo()
    click.echo("  Safety Rules:")
    click.echo("    - No seed phrases stored")
    click.echo("    - No private keys stored")
    click.echo("    - No auto-trades executed")
    click.echo("    - Public addresses only")
    click.echo()


# ── keystore: encrypted hot-key management ────────────────────────────────

@cli.group()
@click.pass_context
def keystore(ctx):
    """Manage the encrypted hot-key keystore (Argon2id + AES-256-GCM)."""


@keystore.command("init")
@click.option(
    "--path", "path_",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Where to write the encrypted keystore file (chmod 0o600).",
)
@click.option(
    "--label",
    default="",
    help="Optional human-readable label stored in the file metadata.",
)
@click.option(
    "--seed-hex",
    default=None,
    help=(
        "Raw seed bytes as hex (with or without 0x prefix). If omitted "
        "you will be prompted; the value is read from a hidden TTY "
        "input and never echoed."
    ),
)
@click.option(
    "--overwrite", is_flag=True,
    help="Replace an existing keystore at the same path.",
)
def keystore_init(path_, label, seed_hex, overwrite):
    """Create a new encrypted keystore.

    The seed never touches disk in plaintext; it goes straight into
    Argon2id-derived AES-256-GCM ciphertext. The password is read
    twice from a hidden prompt and confirmed before any I/O happens.
    """
    from tao_swarm.trading import Keystore, KeystoreError

    click.echo(click.style(
        "\n!! AUTO_TRADING keystore — read this before continuing.", fg="yellow", bold=True,
    ))
    click.echo("   - Use a DEDICATED trading key, never your main coldkey.")
    click.echo("   - Fund it only with the cap amount you can afford to lose.")
    click.echo("   - Loss of the password = loss of the keystore. There is no recovery.")
    click.echo()

    if seed_hex is None:
        seed_hex = click.prompt(
            "Seed (hex, hidden)", hide_input=True, confirmation_prompt=True,
        )
    seed_hex = seed_hex.strip()
    if seed_hex.startswith("0x") or seed_hex.startswith("0X"):
        seed_hex = seed_hex[2:]
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError:
        raise click.ClickException("seed-hex must be a valid hex string")
    if not seed:
        raise click.ClickException("seed cannot be empty")

    password = click.prompt(
        "Keystore password (hidden, min 8 chars)",
        hide_input=True, confirmation_prompt=True,
    )
    try:
        info = Keystore.init(
            path_, password, seed, label=label, overwrite=overwrite,
        )
    except KeystoreError as exc:
        raise click.ClickException(str(exc))
    click.echo(click.style(
        f"\n  Keystore written: {path_}", fg="green",
    ))
    click.echo(f"    label:       {info.label!r}")
    click.echo(f"    created_at:  {info.created_at:.0f}")
    click.echo(f"    kdf_params:  {info.kdf_params}")
    click.echo()


@keystore.command("info")
@click.option(
    "--path", "path_",
    type=click.Path(dir_okay=False, exists=True, path_type=Path),
    required=True,
)
def keystore_info(path_):
    """Show non-secret metadata about a keystore file (no password needed)."""
    from tao_swarm.trading import Keystore, KeystoreError

    try:
        info = Keystore.info(path_)
    except KeystoreError as exc:
        raise click.ClickException(str(exc))
    click.echo(click.style(f"\n  Keystore: {path_}", fg="blue", bold=True))
    click.echo(f"    version:     {info.version}")
    click.echo(f"    label:       {info.label!r}")
    click.echo(f"    created_at:  {info.created_at:.0f}")
    click.echo(f"    kdf:         {info.kdf}")
    click.echo(f"    kdf_params:  {info.kdf_params}")
    click.echo()


@keystore.command("verify")
@click.option(
    "--path", "path_",
    type=click.Path(dir_okay=False, exists=True, path_type=Path),
    required=True,
)
def keystore_verify(path_):
    """Prompt for the password and confirm decryption succeeds.

    The decrypted seed is held in memory only for the duration of
    this command and is wiped on exit. Useful for confirming you
    still know the password without running the trader.
    """
    from tao_swarm.trading import Keystore, KeystoreError, WrongPasswordError

    password = click.prompt("Keystore password (hidden)", hide_input=True)
    try:
        with Keystore.unlock(path_, password) as handle:
            click.echo(click.style(
                f"\n  OK — keystore unlocked (label={handle.label!r}).",
                fg="green",
            ))
    except WrongPasswordError:
        raise click.ClickException("wrong password")
    except KeystoreError as exc:
        raise click.ClickException(str(exc))
    click.echo()


# ── trade: backtest + live runner ─────────────────────────────────────────

@cli.group()
@click.pass_context
def trade(ctx):
    """Run trading strategies — paper-default, live behind explicit gates."""


_BUILTIN_STRATEGIES = ("momentum_rotation", "mean_reversion")


def _build_registry(plugin_paths: tuple[str, ...] | None = None):
    """Build a StrategyRegistry with built-ins + optional plug-ins."""
    from tao_swarm.trading import StrategyRegistry, load_strategy_plugins

    registry = StrategyRegistry()
    registry.register_builtins()
    if plugin_paths:
        summary = load_strategy_plugins(registry, paths=plugin_paths)
        for err in summary.errors:
            click.echo(click.style(
                f"  strategy plug-in error: {err}", fg="red",
            ))
        for skip in summary.skipped:
            click.echo(click.style(
                f"  strategy plug-in skipped: {skip}", fg="yellow",
            ))
        for name in summary.loaded:
            click.echo(click.style(
                f"  strategy plug-in loaded: {name}", fg="green",
            ))
    else:
        # Even without explicit --plugin-paths, honour TAO_STRATEGY_PATHS.
        load_strategy_plugins(registry)
    return registry


def _load_strategy(name: str, plugin_paths=None, **kwargs):
    """Load a strategy by name from the registry (built-in or plug-in)."""
    registry = _build_registry(plugin_paths=plugin_paths)
    if name not in registry:
        raise click.ClickException(
            f"unknown strategy {name!r}; available: {registry.names()}"
        )
    cls = registry.get(name)
    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise click.ClickException(
            f"strategy {name!r} construction failed: {exc}"
        )


@trade.command("backtest")
@click.option(
    "--strategy", "strategy_name",
    type=click.Choice(list(_BUILTIN_STRATEGIES)),
    required=True,
)
@click.option(
    "--snapshots",
    type=click.Path(dir_okay=False, exists=True, path_type=Path),
    required=True,
    help="Path to a JSON file with a list of market_state snapshots.",
)
@click.option(
    "--threshold-pct", default=0.05, type=float, show_default=True,
    help="Strategy momentum threshold (e.g. 0.05 = 5%).",
)
@click.option(
    "--slot-size-tao", default=1.0, type=float, show_default=True,
)
@click.option(
    "--db",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="SQLite path for the paper ledger; defaults to a tmp file.",
)
@click.option(
    "--json", "json_output", is_flag=True,
    help="Print the backtest result as JSON.",
)
def trade_backtest(
    strategy_name, snapshots, threshold_pct, slot_size_tao, db, json_output,
):
    """Run a deterministic backtest from a JSON snapshot file."""
    from tao_swarm.trading import Backtester

    try:
        with snapshots.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"failed to read snapshots: {exc}")
    if not isinstance(data, list):
        raise click.ClickException("snapshots file must contain a JSON list")

    strat = _load_strategy(
        strategy_name,
        threshold_pct=threshold_pct, slot_size_tao=slot_size_tao,
    )
    bt = Backtester(strat, paper_db_path=str(db) if db else ":memory:")
    result = bt.run(data)
    if json_output:
        click.echo(json.dumps(result.as_dict(), indent=2))
        return
    d = result.as_dict()
    click.echo(click.style(
        f"\n  Backtest — {d['strategy_name']}", fg="blue", bold=True,
    ))
    click.echo(f"    steps:        {d['num_steps']}")
    click.echo(f"    proposals:    {d['num_proposals']}")
    click.echo(f"    executed:     {d['num_executed']}")
    click.echo(f"    refused:      {d['num_refused']}")
    click.echo(f"    total_pnl:    {d['total_pnl_tao']:+.4f} TAO")
    click.echo(f"    win_rate:     {d['win_rate']:.2%}")
    click.echo(f"    max_drawdown: {d['max_drawdown_tao']:.4f} TAO")
    click.echo(f"    sharpe:       {d['sharpe_ratio']:.4f}")
    if d["refusals"]:
        click.echo("    refusals (unique reasons):")
        for r in d["refusals"]:
            click.echo(f"      - {r}")
    click.echo()


def _confirm_live_walkthrough(*, strategy_meta, keystore_path, env) -> bool:
    """Interactive triple-check before the runner is started in live mode.

    Returns ``True`` only when the operator types "I UNDERSTAND" and
    every authorisation gate is green. Prints a summary either way.
    """
    from tao_swarm.trading import LIVE_TRADING_ENV

    click.echo(click.style(
        "\n!! LIVE TRADING — final confirmation",
        fg="red", bold=True,
    ))
    click.echo("   Strategy:        {}".format(strategy_meta.name))
    click.echo("   live_trading:    {}".format(strategy_meta.live_trading))
    click.echo("   max_position:    {} TAO".format(strategy_meta.max_position_tao))
    click.echo("   max_daily_loss:  {} TAO".format(strategy_meta.max_daily_loss_tao))
    click.echo("   keystore:        {}".format(keystore_path))
    click.echo("   {} = {!r}".format(
        LIVE_TRADING_ENV, env.get(LIVE_TRADING_ENV),
    ))
    click.echo()
    click.echo("   This will sign and broadcast real Bittensor extrinsics.")
    click.echo("   Type exactly 'I UNDERSTAND' to proceed (anything else aborts):")
    answer = click.prompt("   > ", default="", show_default=False)
    return answer.strip() == "I UNDERSTAND"


@trade.command("run")
@click.option(
    "--strategy", "strategy_name",
    type=click.Choice(list(_BUILTIN_STRATEGIES)),
    required=True,
)
@click.option(
    "--paper/--live", "paper", default=True,
    help="Paper-trade the strategy (default) or attempt live signing.",
)
@click.option(
    "--keystore-path",
    type=click.Path(dir_okay=False, exists=True, path_type=Path),
    default=None,
    help="Required for --live. Operator will be prompted for the password.",
)
@click.option(
    "--threshold-pct", default=0.05, type=float, show_default=True,
)
@click.option(
    "--slot-size-tao", default=1.0, type=float, show_default=True,
)
@click.option(
    "--max-position-tao", default=1.0, type=float, show_default=True,
)
@click.option(
    "--max-daily-loss-tao", default=5.0, type=float, show_default=True,
)
@click.option(
    "--max-total-tao", default=10.0, type=float, show_default=True,
    help="Operator-level total exposure cap across all positions.",
)
@click.option(
    "--tick-interval-s", default=60.0, type=float, show_default=True,
)
@click.option(
    "--max-ticks", default=None, type=int,
    help="Stop after this many ticks (default: run until Ctrl-C).",
)
@click.option(
    "--ledger-db",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("data") / "trades.db",
    show_default=True,
)
@click.option(
    "--kill-switch-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("data") / ".kill",
    show_default=True,
    help="Touch this file to halt trading at the next tick.",
)
@click.option(
    "--watchlist", default=None,
    help="Comma-separated netuids the strategy is allowed to trade.",
)
@click.option(
    "--reconcile-from-coldkey", "reconcile_coldkey", default=None,
    help=(
        "Cold-start reconciliation: read on-chain stake for this coldkey "
        "ss58 before the first tick so the position cap sees the real "
        "current_total_tao after a process restart. Strongly recommended "
        "in --live mode."
    ),
)
@click.option(
    "--verify-broadcasts", is_flag=True,
    help=(
        "After each successful live broadcast, re-read the on-chain "
        "stake to confirm the delta matches the proposal direction "
        "within tolerance (1% by default). Mismatches are recorded in "
        "the ledger with action '<verb>_verification_failed' but do NOT "
        "abort the runner. Recommended in --live mode."
    ),
)
@click.option(
    "--status-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Write the runner's status as JSON to this path after every "
        "tick. The dashboard's Trading panel reads it. Recommended "
        "to set ``data/runner_status.json`` so the default dashboard "
        "discovery picks it up."
    ),
)
@click.option(
    "--live-trading", is_flag=True,
    help=(
        "Set StrategyMeta.live_trading=True. Required (along with "
        f"{'TAO_LIVE_TRADING'}=1 and --keystore-path) for live execution."
    ),
)
@click.option(
    "--yes-i-understand", is_flag=True,
    help=(
        "Skip the interactive 'I UNDERSTAND' confirmation. Intended "
        "for non-interactive deployments where the gate is already "
        "enforced by an external orchestrator."
    ),
)
@click.pass_context
def trade_run(  # noqa: C901 - long but linear; readability beats decomposition
    ctx, strategy_name, paper, keystore_path,
    threshold_pct, slot_size_tao, max_position_tao, max_daily_loss_tao,
    max_total_tao, tick_interval_s, max_ticks, ledger_db, kill_switch_path,
    watchlist, reconcile_coldkey, verify_broadcasts, status_file,
    live_trading, yes_i_understand,
):
    """Run a strategy live or in paper mode against the read-only collectors."""
    from tao_swarm.collectors.chain_readonly import ChainReadOnlyCollector
    from tao_swarm.trading import (
        BittensorChainPositionReader,
        BittensorSigner,
        DailyLossLimit,
        Executor,
        Keystore,
        KeystoreError,
        KillSwitch,
        PaperLedger,
        PositionCap,
        TradingRunner,
        WalletMode,
        WrongPasswordError,
    )

    config = ctx.obj["config"]
    click.echo(_mode_banner(config))

    # 1. Build strategy.
    watch = None
    if watchlist:
        try:
            watch = [int(n.strip()) for n in watchlist.split(",") if n.strip()]
        except ValueError:
            raise click.ClickException("watchlist must be comma-separated integers")
    strat = _load_strategy(
        strategy_name,
        threshold_pct=threshold_pct,
        slot_size_tao=slot_size_tao,
        max_position_tao=max_position_tao,
        max_daily_loss_tao=max_daily_loss_tao,
        watchlist=watch,
    )
    meta = strat.meta()

    # Force the live-trading flag onto a fresh meta if --live-trading was
    # passed. The strategy's own meta() may default to False; this is the
    # operator's per-run override.
    if live_trading:
        # The momentum strategy returns a fresh meta() each call, so we
        # patch the class attribute by wrapping the meta method.
        original_meta = strat.meta

        def patched_meta(_orig=original_meta):
            base = _orig()
            return base.__class__(
                name=base.name, version=base.version,
                max_position_tao=base.max_position_tao,
                max_daily_loss_tao=base.max_daily_loss_tao,
                description=base.description,
                actions_used=base.actions_used,
                live_trading=True,
            )

        strat.meta = patched_meta  # type: ignore[method-assign]
        meta = strat.meta()

    # 2. Build executor + guards + ledger.
    Path(ledger_db).parent.mkdir(parents=True, exist_ok=True)
    ledger = PaperLedger(str(ledger_db))
    kill = KillSwitch(flag_path=str(kill_switch_path))
    cap = PositionCap(
        max_per_position_tao=max_position_tao,
        max_total_tao=max_total_tao,
    )
    loss = DailyLossLimit(
        max_daily_loss_tao=max_daily_loss_tao, ledger=ledger,
    )

    # 3. Live-mode prerequisites.
    signer_factory = None
    handle = None
    if not paper:
        if keystore_path is None:
            raise click.ClickException("--live requires --keystore-path")
        if not live_trading:
            raise click.ClickException(
                "--live requires --live-trading (per-strategy opt-in)"
            )
        if os.environ.get("TAO_LIVE_TRADING") != "1":
            raise click.ClickException(
                "--live requires TAO_LIVE_TRADING=1 in the environment"
            )
        password = click.prompt("Keystore password (hidden)", hide_input=True)
        try:
            handle = Keystore.unlock(keystore_path, password)
        except WrongPasswordError:
            raise click.ClickException("wrong password")
        except KeystoreError as exc:
            raise click.ClickException(str(exc))

        if not yes_i_understand:
            ok = _confirm_live_walkthrough(
                strategy_meta=meta, keystore_path=keystore_path,
                env=os.environ,
            )
            if not ok:
                handle.close()
                click.echo(click.style(
                    "  Aborted — confirmation phrase not entered exactly.",
                    fg="yellow",
                ))
                return

        network_for_live = (
            config.get("network") if config.get("network") in ("finney", "test")
            else "finney"
        )

        def signer_factory_inner():  # noqa: D401 - factory closure
            return BittensorSigner(
                handle, network=network_for_live,
                verify=verify_broadcasts,
                coldkey_ss58=reconcile_coldkey,
            )

        signer_factory = signer_factory_inner

    executor = Executor(
        mode=WalletMode.AUTO_TRADING if not paper else WalletMode.WATCH_ONLY,
        kill_switch=kill,
        position_cap=cap,
        daily_loss_limit=loss,
        ledger=ledger,
        signer_factory=signer_factory,
    )

    # 4. Snapshot function.
    chain = ChainReadOnlyCollector(config=config)

    def snapshot_fn():
        return chain.get_subnet_list()

    # 5. Optional cold-start reconciliation. We require a real network
    #    (not the mock pseudo-network) before constructing a
    #    BittensorChainPositionReader because it would just fail
    #    against mock anyway.
    chain_reader = None
    if reconcile_coldkey:
        if config.get("use_mock_data", True):
            raise click.ClickException(
                "--reconcile-from-coldkey requires --live (real network); "
                "the mock chain has no coldkey state to reconcile against"
            )
        net_for_reader = (
            config.get("network") if config.get("network") in ("finney", "test")
            else "finney"
        )
        chain_reader = BittensorChainPositionReader(network=net_for_reader)

    runner = TradingRunner(
        strategy=strat,
        executor=executor,
        snapshot_fn=snapshot_fn,
        paper=paper,
        tick_interval_s=tick_interval_s,
        chain_reader=chain_reader,
        reconcile_coldkey_ss58=reconcile_coldkey,
        status_file=status_file,
    )

    click.echo(click.style(
        f"\n  Starting runner — strategy={strategy_name}, paper={paper}, "
        f"interval={tick_interval_s}s",
        fg="blue", bold=True,
    ))
    click.echo("  Press Ctrl-C to stop. Touch {} to halt at next tick.".format(
        kill_switch_path,
    ))

    try:
        runner.run_forever(max_ticks=max_ticks)
    except KeyboardInterrupt:
        runner.stop()
        click.echo(click.style("\n  Interrupted — stopping cleanly.", fg="yellow"))
    finally:
        if handle is not None:
            handle.close()

    s = runner.status()
    click.echo()
    click.echo(click.style(
        f"  Runner stopped: {s.state} (halted_reason={s.halted_reason!r})",
        fg="green" if s.state != "halted" else "red",
    ))
    click.echo(f"    ticks:     {s.ticks}")
    click.echo(f"    proposals: {s.proposals}")
    click.echo(f"    executed:  {s.executed}")
    click.echo(f"    refused:   {s.refused}")
    click.echo(f"    errors:    {s.errors}")
    click.echo()


@trade.command("status")
@click.option(
    "--ledger-db",
    type=click.Path(dir_okay=False, exists=True, path_type=Path),
    default=Path("data") / "trades.db",
    show_default=True,
)
@click.option(
    "--strategy", "strategy_name", default=None,
    help="Filter by strategy name (default: all).",
)
@click.option(
    "--limit", default=20, type=int, show_default=True,
)
def trade_status(ledger_db, strategy_name, limit):
    """Summarise the trade ledger — recent trades, totals, P&L."""
    from tao_swarm.trading import PaperLedger

    ledger = PaperLedger(str(ledger_db))
    rows = ledger.list_trades(strategy=strategy_name, limit=limit)
    pnl = ledger.realised_pnl(strategy=strategy_name)
    paper_count = sum(1 for r in rows if r.paper)
    live_count = sum(1 for r in rows if not r.paper)
    failed = sum(1 for r in rows if r.action.endswith("_failed"))
    click.echo(click.style(
        f"\n  Ledger: {ledger_db} (strategy={strategy_name or 'ALL'})",
        fg="blue", bold=True,
    ))
    click.echo(f"    total realised P&L: {pnl:+.4f} TAO")
    click.echo(f"    rows shown:         {len(rows)} (paper={paper_count} live={live_count} failed={failed})")
    if not rows:
        click.echo("    (no trades)")
        click.echo()
        return
    click.echo()
    click.echo(f"    {'time':19s}  {'strategy':18s}  {'action':18s}  {'amount':>10s}  {'price':>10s}  {'pnl':>10s}  paper")
    click.echo(f"    {'-'*19}  {'-'*18}  {'-'*18}  {'-'*10}  {'-'*10}  {'-'*10}  -----")
    for r in rows:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r.timestamp))
        click.echo(
            f"    {ts}  {r.strategy[:18]:18s}  {r.action[:18]:18s}  "
            f"{r.amount_tao:>10.4f}  {r.price_tao:>10.4f}  "
            f"{r.realised_pnl_tao:>+10.4f}  {str(r.paper):5s}"
        )
    click.echo()


# ── Entry point ───────────────────────────────────────────────────────────

def main_entry():
    """CLI entry point."""
    cli()


if __name__ == "__main__":
    main_entry()
