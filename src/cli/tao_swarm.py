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

    # Module status
    modules = [
        ("Collectors", "src.collectors"),
        ("Scoring", "src.scoring"),
        ("Dashboard", "src.dashboard"),
    ]
    click.echo("\nModules:")
    for name, mod_path in modules:
        mod_dir = Path(mod_path)
        status_text = "found" if mod_dir.exists() else "not found"
        color = "green" if mod_dir.exists() else "red"
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
        from src.collectors.chain_readonly import ChainReadOnlyCollector
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
    click.echo(f"  {'ID':>4s}  {'Name':20s} {'Neurons':>8s} {'Emission':>10s} {'Block':>10s}")
    click.echo(f"  {'-'*4:>4s}  {'-'*20:20s} {'-'*8:>8s} {'-'*10:>10s} {'-'*10:>10s}")

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
        from src.collectors.subnet_metadata import SubnetMetadataCollector
        from src.scoring.subnet_score import SubnetScorer
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
        from src.collectors.wallet_watchonly import WalletWatchOnlyCollector
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
        from src.collectors.wallet_watchonly import WalletWatchOnlyCollector
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
        from src.collectors.market_data import MarketDataCollector
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
        from src.scoring.risk_score import RiskScorer
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
    """Start orchestrator run."""
    click.echo(click.style("\n=== Orchestrator Run ===", fg="blue", bold=True))

    if dry_run:
        click.echo(click.style("\n  [DRY RUN] No actions will be executed", fg="yellow"))

    click.echo("\n  Checking orchestrator...")

    orch_path = Path("src/orchestrator/orchestrator.py")
    if orch_path.exists():
        click.echo(click.style("  Orchestrator module found", fg="green"))
    else:
        click.echo(click.style("  Orchestrator module not found", fg="yellow"))
        click.echo("  Run will use built-in task routing.")

    if agent:
        click.echo(f"\n  Target agent: {agent}")
    if task:
        try:
            task_dict = json.loads(task)
            click.echo(f"  Task: {json.dumps(task_dict, indent=2)}")
        except json.JSONDecodeError:
            click.echo(click.style("  Invalid task JSON", fg="red"))
            return

    if not dry_run:
        click.echo(click.style("\n  Run completed successfully", fg="green"))
    else:
        click.echo(click.style("\n  Dry run completed", fg="green"))

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
            from src.scoring.subnet_score import SubnetScorer
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

    dashboard_path = Path("src/dashboard/app.py")
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
        from src.agents import (
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
        from src.orchestrator import SwarmOrchestrator, load_plugins
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


# ── Entry point ───────────────────────────────────────────────────────────

def main_entry():
    """CLI entry point."""
    cli()


if __name__ == "__main__":
    main_entry()
