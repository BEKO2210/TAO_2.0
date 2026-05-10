"""
TradingBrain — pull-based aggregator over the 15-agent expert team.

After PR 2S, every agent has a real data lineage and publishes a
typed report to the :class:`tao_swarm.orchestrator.context.AgentContext`
bus. This module reads those published reports and extracts each
agent's *trading-relevant* contribution — its specialty signal —
into a typed :class:`AgentSignal`, then aggregates them into a
single trading view the strategies + executor can consult.

Architectural choice
====================

The brain is a **consumer** of agent outputs, not a modification
of them. That keeps each agent's contract narrow (it just
publishes its report) and lets the brain evolve independently as
new aggregation rules / signals are needed.

Pull-based, never raises
========================

Each extractor function takes the AgentContext and returns either
an ``AgentSignal`` or ``None`` (when the upstream agent hasn't
published, or when its output is missing the field this extractor
cares about). Extractors are pure, defensive, and never raise —
the brain is allowed to operate with partial information.

Aggregation
===========

:meth:`TradingBrain.aggregate` returns a unified decision:

- A **veto** is a special signal direction that halts trading
  immediately. Currently emitted by ``risk_security_agent`` (when
  it detects DANGER text) and by ``qa_test_agent`` (when wallet-
  compliance fails). Veto requires ``confidence >= veto_threshold``
  to fire — a low-confidence veto degrades to a strong-bearish
  weight instead.

- Otherwise the brain computes a ``weighted-average`` over all
  non-veto signals. Weights default to 1.0 per agent but can be
  overridden via the ``weights`` constructor argument or via the
  CLI.

- The aggregate score lives in [0, 1]. Above ``bullish_threshold``
  (default 0.6) → ``"bullish"``; below ``bearish_threshold``
  (default 0.4) → ``"bearish"``; otherwise → ``"neutral"``.

The output dict is JSON-serialisable so the dashboard / CLI / API
can render it without further conversion.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentSignal:
    """One agent's contribution to the trading decision.

    Always emit a signal when you have *any* relevant view; emit
    ``None`` (return from the extractor) when you genuinely have
    no data. Confidence + evidence let the operator audit why the
    brain reached a particular decision.
    """

    name: str                  # e.g. "subnet_scoring_agent"
    score: float               # [0, 1] — 1 = strong positive trading signal
    confidence: float          # [0, 1] — how reliable is the score
    direction: str             # "bullish" | "bearish" | "neutral" | "veto"
    evidence: str              # one-line human-readable explanation
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(
                f"AgentSignal.score must be in [0, 1], got {self.score}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"AgentSignal.confidence must be in [0, 1], got "
                f"{self.confidence}"
            )
        if self.direction not in ("bullish", "bearish", "neutral", "veto"):
            raise ValueError(
                f"AgentSignal.direction must be bullish/bearish/neutral/veto, "
                f"got {self.direction!r}"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BrainDecision:
    """The aggregated output of :meth:`TradingBrain.aggregate`."""

    decision: str              # "bullish" | "bearish" | "neutral" | "halt"
    score: float | None        # None when halted
    reason: str
    signals: tuple[AgentSignal, ...] = ()
    weights: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "score": self.score,
            "reason": self.reason,
            "signals": [s.as_dict() for s in self.signals],
            "weights": dict(self.weights),
        }


# Type alias for the extractor signature.
Extractor = Callable[[Any], "AgentSignal | None"]


# ---------------------------------------------------------------------------
# Default weights — operator can override
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    # Highest weight: agents whose signal IS a trading view.
    "subnet_scoring_agent":         1.5,
    "market_trade_agent":           1.3,
    "wallet_watch_agent":           1.2,
    # Middle weight: chain + protocol context.
    "subnet_discovery_agent":       1.0,
    "protocol_research_agent":      1.0,
    # Risk / safety: weight matters mostly for non-veto cases.
    "risk_security_agent":          1.4,
    "qa_test_agent":                1.0,
    # Operations / fitness signals.
    "system_check_agent":           0.8,
    "miner_engineering_agent":      0.7,
    "validator_engineering_agent":  0.7,
    "training_experiment_agent":    0.4,
    "infra_devops_agent":           0.4,
    "fullstack_dev_agent":          0.3,
    "documentation_agent":          0.2,
    # Honest stub: not a trading-relevant signal.
    "dashboard_design_agent":       0.0,
}


# ---------------------------------------------------------------------------
# Extractor helpers (pure — read context, return Signal | None)
# ---------------------------------------------------------------------------

def _safe_get(ctx: Any, key: str, default: Any = None) -> Any:
    """Defensive context.get — never raises, returns default on any miss."""
    if ctx is None:
        return default
    try:
        return ctx.get(key, default)
    except Exception:
        return default


def _isnum(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and not (isinstance(v, float) and math.isnan(v))


# ---------------------------------------------------------------------------
# Per-agent extractors
# ---------------------------------------------------------------------------

def extract_subnet_scoring(ctx: Any) -> AgentSignal | None:
    """The single-strongest specialty signal in the swarm.

    Reads the top scored subnet's ``final_score`` (0-100) and
    converts it to a [0, 1] score. Confidence comes from how many
    subnets were scored — 1 subnet is a stub, 100 subnets is real.
    """
    out = _safe_get(ctx, "subnet_scoring_agent")
    if not isinstance(out, dict):
        return None
    scored = out.get("scored_subnets") or []
    if not isinstance(scored, list) or not scored:
        return None
    top = scored[0]
    raw = top.get("final_score")
    if not _isnum(raw):
        return None
    score = max(0.0, min(1.0, float(raw) / 100.0))
    n = len(scored)
    confidence = max(0.2, min(1.0, n / 30.0))  # asymptote at ~30 subnets
    direction = "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral"
    return AgentSignal(
        name="subnet_scoring_agent",
        score=round(score, 4),
        confidence=round(confidence, 4),
        direction=direction,
        evidence=(
            f"top subnet '{top.get('name', '?')}' (netuid {top.get('netuid')}) "
            f"scored {raw}/100 over {n} candidates"
        ),
        meta={"top_netuid": top.get("netuid"), "n_scored": n},
    )


def extract_market_trade(ctx: Any) -> AgentSignal | None:
    """Macro TAO trend from the market agent's price-change view."""
    out = _safe_get(ctx, "market_trade_agent")
    if not isinstance(out, dict):
        return None
    # The agent publishes price_change in different shapes; tolerate.
    pc7 = (
        _safe_get(ctx, "market_trade_agent.price_change.7d_pct")
        or _safe_get(ctx, "market_trade_agent.price_change_7d")
    )
    pc24 = (
        _safe_get(ctx, "market_trade_agent.price_change.24h_pct")
        or _safe_get(ctx, "market_trade_agent.price_change_24h")
    )
    if not _isnum(pc7) and not _isnum(pc24):
        return None
    pc7_v = float(pc7) if _isnum(pc7) else 0.0
    pc24_v = float(pc24) if _isnum(pc24) else 0.0
    # Tilt heavily on 7d, lightly on 24h. Clip the score to keep
    # extreme moves from dominating.
    tilt = pc7_v * 0.7 + pc24_v * 0.3
    # Map tilt% → [0, 1] with center at 0% → 0.5 and ±20% as the
    # natural bullish/bearish anchors.
    score = max(0.0, min(1.0, 0.5 + tilt / 40.0))
    direction = "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral"
    return AgentSignal(
        name="market_trade_agent",
        score=round(score, 4),
        confidence=0.7,
        direction=direction,
        evidence=f"TAO 7d {pc7_v:+.1f}%, 24h {pc24_v:+.1f}%",
        meta={"price_change_7d": pc7_v, "price_change_24h": pc24_v},
    )


def extract_wallet_watch(ctx: Any) -> AgentSignal | None:
    """Concentration-risk signal.

    If the operator's stake is concentrated in one position, the
    brain shouldn't be encouraging *more* of the same. Returns
    bearish when concentration is high.
    """
    out = _safe_get(ctx, "wallet_watch_agent")
    if not isinstance(out, dict):
        return None
    portfolio = out.get("portfolio") or out.get("portfolio_summary") or {}
    if not isinstance(portfolio, dict):
        return None
    addresses = portfolio.get("addresses") or []
    if not isinstance(addresses, list):
        return None
    balances = [
        float(a.get("balance_tao", 0.0)) for a in addresses
        if _isnum(a.get("balance_tao", 0))
    ]
    total = sum(balances)
    if total <= 0:
        # Empty portfolio — neutral signal. Operator can build from
        # zero without worrying about concentration.
        return AgentSignal(
            name="wallet_watch_agent",
            score=0.5,
            confidence=0.4,
            direction="neutral",
            evidence="empty portfolio — no concentration risk yet",
        )
    top = max(balances)
    concentration = top / total  # 1.0 = fully concentrated
    # Less concentration → more bullish (room to grow). Heavy
    # concentration → bearish (don't pile on).
    score = max(0.0, min(1.0, 1.0 - concentration))
    direction = "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral"
    return AgentSignal(
        name="wallet_watch_agent",
        score=round(score, 4),
        confidence=0.7,
        direction=direction,
        evidence=(
            f"top position is {concentration * 100:.0f}% of "
            f"{total:.2f} TAO across {len(balances)} address(es)"
        ),
        meta={"concentration": round(concentration, 4), "total_tao": round(total, 4)},
    )


def extract_subnet_discovery(ctx: Any) -> AgentSignal | None:
    """Subnet-activity barometer — high tao_in volume → bullish."""
    out = _safe_get(ctx, "subnet_discovery_agent")
    if not isinstance(out, dict):
        return None
    subnets = out.get("subnets") or []
    if not isinstance(subnets, list) or not subnets:
        return None
    tao_ins = [
        float(s.get("tao_in", 0.0)) for s in subnets
        if _isnum(s.get("tao_in", 0))
    ]
    if not tao_ins:
        return None
    total_tao_in = sum(tao_ins)
    median_tao_in = sorted(tao_ins)[len(tao_ins) // 2]
    # Heuristic: > 5_000_000 total TAO_in indicates a healthy
    # network with real liquidity. Below 1_000_000 looks dormant.
    if total_tao_in <= 0:
        return None
    score = max(0.0, min(1.0, math.log10(max(1.0, total_tao_in / 100_000.0)) / 3.0))
    direction = "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral"
    return AgentSignal(
        name="subnet_discovery_agent",
        score=round(score, 4),
        confidence=0.6,
        direction=direction,
        evidence=(
            f"{len(subnets)} subnets, total TAO_in {total_tao_in:,.0f}, "
            f"median {median_tao_in:,.0f}"
        ),
        meta={
            "n_subnets": len(subnets),
            "total_tao_in": round(total_tao_in, 2),
        },
    )


def extract_protocol_research(ctx: Any) -> AgentSignal | None:
    """Network-health signal from the protocol-research agent."""
    out = _safe_get(ctx, "protocol_research_agent")
    if not isinstance(out, dict):
        return None
    health = out.get("network_health") or out.get("status_summary") or {}
    if not isinstance(health, dict):
        # Fall back to a presence-based weak signal — at least
        # confirms the chain is reachable.
        return AgentSignal(
            name="protocol_research_agent",
            score=0.55,
            confidence=0.3,
            direction="neutral",
            evidence="chain reachable; no detailed health summary",
        )
    n_subnets = health.get("subnet_count") or health.get("subnets")
    n_validators = health.get("validator_count") or health.get("validators")
    parts = []
    if _isnum(n_subnets):
        parts.append(f"subnets={int(n_subnets)}")
    if _isnum(n_validators):
        parts.append(f"validators={int(n_validators)}")
    score = 0.6  # presence + non-trivial counts → mildly bullish
    if not parts:
        score = 0.5
    direction = "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral"
    return AgentSignal(
        name="protocol_research_agent",
        score=round(score, 4),
        confidence=0.5,
        direction=direction,
        evidence="chain healthy: " + (", ".join(parts) if parts else "minimal data"),
        meta=dict(health),
    )


def extract_risk_security(ctx: Any) -> AgentSignal | None:
    """**VETO**: any DANGER classification halts trading."""
    out = _safe_get(ctx, "risk_security_agent")
    if not isinstance(out, dict):
        return None
    # The agent publishes `classification` ("SAFE" | "CAUTION" | "DANGER")
    # plus a list of detected patterns.
    cls = (out.get("classification") or "").upper()
    findings = out.get("findings") or out.get("detected") or []
    if cls == "DANGER":
        return AgentSignal(
            name="risk_security_agent",
            score=0.0,
            confidence=0.95,
            direction="veto",
            evidence=(
                "DANGER classification — "
                + (", ".join(str(f) for f in findings[:3]) if findings else "no detail")
            ),
            meta={"classification": cls, "findings": list(findings)[:5]},
        )
    if cls == "CAUTION":
        return AgentSignal(
            name="risk_security_agent",
            score=0.35,
            confidence=0.8,
            direction="bearish",
            evidence="CAUTION classification — proceed defensively",
            meta={"classification": cls, "findings": list(findings)[:5]},
        )
    if cls == "SAFE":
        return AgentSignal(
            name="risk_security_agent",
            score=0.7,
            confidence=0.85,
            direction="bullish",
            evidence="SAFE classification — no risk patterns detected",
            meta={"classification": cls},
        )
    return None


def extract_qa_test(ctx: Any) -> AgentSignal | None:
    """**VETO** if a wallet-compliance issue is detected — those are
    things like 'seed phrase committed in source'. Otherwise a
    weak code-hygiene signal."""
    out = _safe_get(ctx, "qa_test_agent")
    if not isinstance(out, dict):
        return None
    findings = int(out.get("findings_count") or 0)
    severities = out.get("severities") or {}
    critical = int(severities.get("critical", 0)) if isinstance(severities, dict) else 0
    if critical > 0:
        return AgentSignal(
            name="qa_test_agent",
            score=0.0,
            confidence=0.9,
            direction="veto",
            evidence=f"{critical} critical compliance issue(s) detected",
            meta={"critical": critical, "total_findings": findings},
        )
    # No critical findings — slightly bullish on code hygiene.
    score = 0.65 if findings == 0 else 0.5
    direction = "bullish" if score > 0.6 else "neutral"
    return AgentSignal(
        name="qa_test_agent",
        score=score,
        confidence=0.5,
        direction=direction,
        evidence=f"{findings} non-critical findings",
        meta={"total_findings": findings},
    )


def extract_system_check(ctx: Any) -> AgentSignal | None:
    """Hardware-fitness signal — operator's machine ready to trade?"""
    hw = _safe_get(ctx, "system_check_agent.hardware_report")
    if not isinstance(hw, dict):
        return None
    ram = hw.get("ram_total_gb") or hw.get("ram_gb")
    cpu = hw.get("cpu_count") or hw.get("cpus")
    parts = []
    score_components = []
    if _isnum(ram):
        # 4 GB → 0.4, 8 GB → 0.6, 16 GB → 0.8, 32+ GB → 1.0
        ram_score = max(0.4, min(1.0, math.log2(max(2.0, float(ram))) / 5.0))
        score_components.append(ram_score)
        parts.append(f"{ram:.0f} GB RAM")
    if _isnum(cpu):
        cpu_score = max(0.4, min(1.0, 0.4 + 0.1 * float(cpu)))
        score_components.append(cpu_score)
        parts.append(f"{int(cpu)} CPU(s)")
    if not score_components:
        return None
    score = sum(score_components) / len(score_components)
    direction = "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral"
    return AgentSignal(
        name="system_check_agent",
        score=round(score, 4),
        confidence=0.7,
        direction=direction,
        evidence="hardware: " + ", ".join(parts),
        meta={"ram_gb": ram, "cpu_count": cpu},
    )


def extract_miner_engineering(ctx: Any) -> AgentSignal | None:
    """Mining-viability score: low complexity + matching hardware → bullish."""
    out = _safe_get(ctx, "miner_engineering_agent")
    if not isinstance(out, dict):
        return None
    complexity = out.get("complexity")
    hw_compatible = out.get("hardware_compatible")
    score = 0.5
    parts = []
    if isinstance(complexity, str):
        cmap = {"low": 0.75, "medium": 0.55, "high": 0.35}
        if complexity in cmap:
            score = cmap[complexity]
            parts.append(f"complexity={complexity}")
    if isinstance(hw_compatible, bool):
        score = score * (1.0 if hw_compatible else 0.6)
        parts.append(f"hw-compatible={hw_compatible}")
    if not parts:
        return None
    direction = "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral"
    return AgentSignal(
        name="miner_engineering_agent",
        score=round(score, 4),
        confidence=0.5,
        direction=direction,
        evidence="mining viability: " + ", ".join(parts),
        meta={"complexity": complexity, "hardware_compatible": hw_compatible},
    )


def extract_validator_engineering(ctx: Any) -> AgentSignal | None:
    """Validator-slot opportunity — low validator count → opening."""
    out = _safe_get(ctx, "validator_engineering_agent")
    if not isinstance(out, dict):
        return None
    feasibility = out.get("feasibility") or out.get("status")
    score = 0.5
    if isinstance(feasibility, str):
        fmap = {"feasible": 0.75, "marginal": 0.5, "infeasible": 0.3}
        if feasibility in fmap:
            score = fmap[feasibility]
        else:
            return None
    else:
        return None
    direction = "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral"
    return AgentSignal(
        name="validator_engineering_agent",
        score=round(score, 4),
        confidence=0.5,
        direction=direction,
        evidence=f"validator feasibility: {feasibility}",
        meta={"feasibility": feasibility},
    )


def extract_training_experiment(ctx: Any) -> AgentSignal | None:
    """Operator-as-participant signal — does the operator themselves
    intend to mine/train? Being IN the network = info edge."""
    out = _safe_get(ctx, "training_experiment_agent")
    if not isinstance(out, dict):
        return None
    has_plan = bool(out.get("training_plan") or out.get("poc_plan"))
    if not has_plan:
        return None
    return AgentSignal(
        name="training_experiment_agent",
        score=0.62,
        confidence=0.4,
        direction="bullish",
        evidence="operator has training/PoC plan — info edge from being a participant",
        meta={"has_plan": has_plan},
    )


def extract_infra_devops(ctx: Any) -> AgentSignal | None:
    """Infrastructure-readiness — Docker / compose plan present."""
    out = _safe_get(ctx, "infra_devops_agent")
    if not isinstance(out, dict):
        return None
    if not (out.get("dockerfile") or out.get("structure") or out.get("compose")):
        return None
    return AgentSignal(
        name="infra_devops_agent",
        score=0.6,
        confidence=0.4,
        direction="bullish",
        evidence="infra plan generated — operator has deployment artefacts",
    )


def extract_fullstack_dev(ctx: Any) -> AgentSignal | None:
    """UX-maturity proxy: focus subnet has dev plan = it's worth the
    swarm's attention."""
    out = _safe_get(ctx, "fullstack_dev_agent")
    if not isinstance(out, dict):
        return None
    if not out.get("focus_subnet") and not out.get("plan"):
        return None
    return AgentSignal(
        name="fullstack_dev_agent",
        score=0.55,
        confidence=0.3,
        direction="neutral",
        evidence="focus subnet has dev plan",
    )


def extract_documentation(ctx: Any) -> AgentSignal | None:
    """Swarm self-coverage health: how well-documented is the swarm
    itself? Uses ``coverage`` if published; mild signal."""
    out = _safe_get(ctx, "documentation_agent")
    if not isinstance(out, dict):
        return None
    coverage = out.get("coverage") or out.get("agent_coverage_pct")
    if not _isnum(coverage):
        return None
    score = max(0.4, min(1.0, float(coverage) / 100.0 + 0.1))
    return AgentSignal(
        name="documentation_agent",
        score=round(score, 4),
        confidence=0.3,
        direction="neutral",
        evidence=f"swarm doc coverage: {coverage:.0f}%",
        meta={"coverage": coverage},
    )


def extract_dashboard_design(ctx: Any) -> AgentSignal | None:
    """Honest stub — UI work, not a trading signal."""
    return None


# Registry of extractors used by the brain. Order doesn't matter
# (the brain treats them as a set), but keeping it stable helps
# the dashboard render deterministically.
_EXTRACTORS: list[tuple[str, Extractor]] = [
    ("subnet_scoring_agent",       extract_subnet_scoring),
    ("market_trade_agent",         extract_market_trade),
    ("wallet_watch_agent",         extract_wallet_watch),
    ("subnet_discovery_agent",     extract_subnet_discovery),
    ("protocol_research_agent",    extract_protocol_research),
    ("risk_security_agent",        extract_risk_security),
    ("qa_test_agent",              extract_qa_test),
    ("system_check_agent",         extract_system_check),
    ("miner_engineering_agent",    extract_miner_engineering),
    ("validator_engineering_agent", extract_validator_engineering),
    ("training_experiment_agent",  extract_training_experiment),
    ("infra_devops_agent",         extract_infra_devops),
    ("fullstack_dev_agent",        extract_fullstack_dev),
    ("documentation_agent",        extract_documentation),
    ("dashboard_design_agent",     extract_dashboard_design),
]


# ---------------------------------------------------------------------------
# TradingBrain
# ---------------------------------------------------------------------------

class TradingBrain:
    """Aggregates the 15 expert signals into one trading decision.

    Construct with an :class:`AgentContext` (the bus from the
    orchestrator) and optionally a custom weight map. Call
    :meth:`collect` for the per-agent signal list, or
    :meth:`aggregate` for the unified decision.

    The brain is read-only — it never modifies the context or any
    agent state. Multiple instances can coexist (e.g. one per
    different weight scheme).
    """

    DEFAULT_BULLISH_THRESHOLD: float = 0.6
    DEFAULT_BEARISH_THRESHOLD: float = 0.4
    DEFAULT_VETO_CONFIDENCE: float = 0.8

    def __init__(
        self,
        context: Any,
        *,
        weights: dict[str, float] | None = None,
        bullish_threshold: float = DEFAULT_BULLISH_THRESHOLD,
        bearish_threshold: float = DEFAULT_BEARISH_THRESHOLD,
        veto_confidence: float = DEFAULT_VETO_CONFIDENCE,
    ) -> None:
        if not 0.5 <= bullish_threshold <= 1.0:
            raise ValueError("bullish_threshold must be in [0.5, 1.0]")
        if not 0.0 <= bearish_threshold <= 0.5:
            raise ValueError("bearish_threshold must be in [0.0, 0.5]")
        if not 0.0 <= veto_confidence <= 1.0:
            raise ValueError("veto_confidence must be in [0.0, 1.0]")
        self._context = context
        self._weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self._weights.update(weights)
        self._bullish = bullish_threshold
        self._bearish = bearish_threshold
        self._veto_conf = veto_confidence

    # ---- public ----

    def collect(self) -> list[AgentSignal]:
        """Pull a signal from each known agent. Skips agents that
        haven't published or have no relevant view yet."""
        signals: list[AgentSignal] = []
        for name, extractor in _EXTRACTORS:
            try:
                sig = extractor(self._context)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("extractor %s raised: %s", name, exc)
                continue
            if sig is None:
                continue
            signals.append(sig)
        return signals

    def aggregate(self) -> BrainDecision:
        """Combine signals into a single decision.

        Algorithm:
        1. Collect all signals.
        2. If any signal has direction='veto' AND confidence ≥
           ``veto_confidence``, the brain returns 'halt' immediately.
        3. Otherwise, compute a confidence-weighted weighted-average
           score across all non-veto signals. (A degraded veto with
           low confidence becomes a strong-bearish weight.)
        4. Map the aggregate to bullish / bearish / neutral by the
           configured thresholds.
        """
        signals = self.collect()
        if not signals:
            return BrainDecision(
                decision="neutral",
                score=0.5,
                reason="no agents have published yet",
                signals=(),
                weights=dict(self._weights),
            )

        # Step 1: hard veto check.
        for sig in signals:
            if sig.direction == "veto" and sig.confidence >= self._veto_conf:
                return BrainDecision(
                    decision="halt",
                    score=None,
                    reason=f"VETO from {sig.name}: {sig.evidence}",
                    signals=tuple(signals),
                    weights=dict(self._weights),
                )

        # Step 2: weighted average.
        total_weight = 0.0
        weighted_sum = 0.0
        for sig in signals:
            w = float(self._weights.get(sig.name, 1.0))
            if w <= 0:
                continue
            # Confidence multiplies into the effective weight so
            # low-confidence signals have a smaller pull.
            eff_w = w * sig.confidence
            total_weight += eff_w
            weighted_sum += eff_w * sig.score

        if total_weight <= 0:
            return BrainDecision(
                decision="neutral",
                score=0.5,
                reason="all signals zero-weighted (operator-configured)",
                signals=tuple(signals),
                weights=dict(self._weights),
            )

        score = weighted_sum / total_weight
        if score >= self._bullish:
            decision = "bullish"
        elif score <= self._bearish:
            decision = "bearish"
        else:
            decision = "neutral"

        return BrainDecision(
            decision=decision,
            score=round(score, 4),
            reason=f"aggregate of {len(signals)} signal(s)",
            signals=tuple(signals),
            weights=dict(self._weights),
        )
