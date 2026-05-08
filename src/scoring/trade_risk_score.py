"""
Trade Risk Scoring Algorithm

Paper-trading specific risk assessment for TAO market operations.
Assesses entry risk, exit risk, volatility risk, and liquidity risk.
Calculates position sizes based on risk score.

No real trades are executed - this is for paper trading simulation only.
"""

import logging
import math
from typing import List, Optional

logger = logging.getLogger(__name__)


class TradeRiskScorer:
    """
    Paper-trading risk scorer for TAO market operations.

    All calculations are for simulation purposes only.
    No actual trades are executed.
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        """
        Initialize the trade risk scorer.

        Args:
            config: Optional configuration with:
                - 'max_position_pct': Max position size as % of capital (default: 20)
                - 'risk_per_trade_pct': Max risk per trade % (default: 2)
                - 'volatility_threshold': Volatility threshold for warnings (default: 15)
        """
        self.config = config or {}
        self.max_position_pct = self.config.get("max_position_pct", 20.0)
        self.risk_per_trade_pct = self.config.get("risk_per_trade_pct", 2.0)
        self.volatility_threshold = self.config.get("volatility_threshold", 15.0)

    # ── Entry Risk ──────────────────────────────────────────────────────────

    def assess_entry_risk(self, market_data: dict) -> float:
        """
        Assess risk of entering a position.

        Args:
            market_data: Dictionary with price, volume, trend data.

        Returns:
            Risk score 0-100 (higher = more risky entry).
        """
        score = 30.0  # Base entry risk

        # Price trend risk
        change_24h = market_data.get("change_24h_pct", 0)
        if change_24h > 10:
            score += 15  # Entering after big pump = risky (FOMO)
        elif change_24h < -10:
            score += 10  # Entering after big dump = risky (catching knife)
        elif abs(change_24h) < 2:
            score -= 5  # Low volatility = safer entry

        # Volume confirmation
        volume_change = market_data.get("volume_change_24h", 0)
        if volume_change > 50:
            score -= 10  # High volume = more confirmation
        elif volume_change < -50:
            score += 10  # Low volume = less reliable

        # Market cap stability
        mcap = market_data.get("market_cap_usd", 0)
        if mcap > 1_000_000_000:
            score -= 10  # Large cap = more stable
        elif mcap < 100_000_000:
            score += 10  # Small cap = more volatile

        # Trend direction
        trend_7d = market_data.get("change_7d_pct", 0)
        trend_30d = market_data.get("change_30d_pct", 0)
        if trend_7d > 0 and trend_30d > 0:
            score -= 5  # Uptrend = better entry timing
        elif trend_7d < 0 and trend_30d < 0:
            score += 10  # Downtrend = riskier entry

        logger.debug("Entry risk score: %.1f", score)
        return max(0.0, min(100.0, score))

    # ── Exit Risk ───────────────────────────────────────────────────────────

    def assess_exit_risk(self, market_data: dict) -> float:
        """
        Assess risk of exiting a position.

        Args:
            market_data: Dictionary with price, volume, trend data.

        Returns:
            Risk score 0-100 (higher = more risky exit / opportunity cost).
        """
        score = 20.0  # Base exit risk

        # Exiting during extreme moves = opportunity cost
        change_24h = market_data.get("change_24h_pct", 0)
        if change_24h > 15:
            score += 20  # Exiting during pump = missing gains
        elif change_24h < -15:
            score += 5  # Exiting during dump = panic selling

        # Volume liquidity for exit
        vol = market_data.get("volume_24h_usd", 0)
        if vol < 1_000_000:
            score += 15  # Low liquidity = harder to exit
        elif vol > 50_000_000:
            score -= 10  # High liquidity = easy exit

        # Time-based risk (mock position age)
        position_age_hours = market_data.get("position_age_hours", 0)
        if position_age_hours < 1:
            score += 10  # Exiting too quickly
        elif position_age_hours > 24 * 7:
            score -= 5  # Held for a week, reasonable to exit

        logger.debug("Exit risk score: %.1f", score)
        return max(0.0, min(100.0, score))

    # ── Volatility Risk ─────────────────────────────────────────────────────

    def assess_volatility_risk(self, price_data: list) -> float:
        """
        Assess volatility risk from historical price data.

        Args:
            price_data: List of price dictionaries with 'price_usd' key,
                       or list of float prices.

        Returns:
            Risk score 0-100 based on historical volatility.
        """
        if len(price_data) < 5:
            return 50.0  # Insufficient data = medium risk

        # Extract prices
        prices = []
        for p in price_data:
            if isinstance(p, dict):
                prices.append(p.get("price_usd", 0))
            elif isinstance(p, (int, float)):
                prices.append(float(p))

        prices = [p for p in prices if p > 0]
        if len(prices) < 5:
            return 50.0

        # Calculate standard deviation of returns
        returns = []
        for i in range(1, len(prices)):
            ret = (prices[i] - prices[i - 1]) / prices[i - 1] * 100
            returns.append(ret)

        if not returns:
            return 50.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance)

        # Annualized volatility approximation
        periods_per_year = 365
        annualized_vol = std_dev * math.sqrt(periods_per_year)

        # Convert to 0-100 score
        if annualized_vol < 20:
            score = 10.0
        elif annualized_vol < 50:
            score = 25.0
        elif annualized_vol < 100:
            score = 45.0
        elif annualized_vol < 200:
            score = 65.0
        elif annualized_vol < 300:
            score = 80.0
        else:
            score = 95.0

        logger.debug("Volatility risk: annualized=%.1f%%, score=%.1f", annualized_vol, score)
        return score

    # ── Liquidity Risk ──────────────────────────────────────────────────────

    def assess_liquidity_risk(self, volume_data: dict) -> float:
        """
        Assess liquidity risk from volume data.

        Args:
            volume_data: Dictionary with volume metrics.

        Returns:
            Risk score 0-100 (higher = less liquid = riskier).
        """
        score = 30.0

        vol_24h = volume_data.get("volume_24h_usd", 0)
        vol_change = volume_data.get("volume_change_24h", 0)
        market_cap = volume_data.get("market_cap_usd", 0)

        # Volume-based scoring
        if vol_24h < 500_000:
            score += 40  # Very low volume
        elif vol_24h < 2_000_000:
            score += 20
        elif vol_24h < 10_000_000:
            score += 5
        elif vol_24h > 50_000_000:
            score -= 15  # High liquidity
        elif vol_24h > 100_000_000:
            score -= 25

        # Volume trend
        if vol_change < -70:
            score += 15  # Sharp volume decline
        elif vol_change > 100:
            score -= 5  # Volume surging

        # Volume to market cap ratio (turnover)
        if market_cap > 0:
            turnover = (vol_24h / market_cap) * 100
            if turnover < 0.5:
                score += 10  # Low turnover
            elif turnover > 10:
                score -= 10  # High turnover = liquid

        # Bid-ask spread proxy (if available)
        spread = volume_data.get("bid_ask_spread_pct", 0)
        if spread > 1.0:
            score += 20  # Wide spread = illiquid
        elif spread < 0.1:
            score -= 10  # Tight spread = liquid

        logger.debug("Liquidity risk score: %.1f", score)
        return max(0.0, min(100.0, score))

    # ── Position Sizing ─────────────────────────────────────────────────────

    def calculate_position_size(self, risk_score: float, capital: float) -> float:
        """
        Calculate paper trade position size based on risk.

        Uses the Kelly Criterion-inspired approach:
        Position size = (Capital * Max_Position%) * (1 - Risk_Score/100)

        Args:
            risk_score: Overall risk score (0-100).
            capital: Available capital in USD.

        Returns:
            Recommended position size in USD.
        """
        if capital <= 0:
            return 0.0

        # Base position as % of capital
        base_position = capital * (self.max_position_pct / 100)

        # Risk adjustment factor
        risk_factor = max(0.05, 1 - (risk_score / 100))

        # Kelly fraction adjustment
        kelly_fraction = max(0.05, min(0.5, (50 - risk_score) / 100))

        position_size = base_position * risk_factor * (1 + kelly_fraction)

        # Cap at max position
        position_size = min(position_size, base_position)

        # Minimum position
        position_size = max(position_size, capital * 0.005)

        result = round(position_size, 2)
        logger.info(
            "Position size: capital=$%.2f, risk=%.1f, position=$%.2f",
            capital, risk_score, result,
        )
        return result

    # ── Composite Trade Risk ────────────────────────────────────────────────

    def calculate_trade_risk(
        self,
        market_data: dict,
        price_data: list,
        volume_data: dict,
    ) -> dict:
        """
        Calculate comprehensive trade risk assessment.

        Args:
            market_data: Current market snapshot.
            price_data: Historical price list.
            volume_data: Volume metrics.

        Returns:
            Full trade risk assessment with all components.
        """
        entry_risk = self.assess_entry_risk(market_data)
        exit_risk = self.assess_exit_risk(market_data)
        volatility_risk = self.assess_volatility_risk(price_data)
        liquidity_risk = self.assess_liquidity_risk(volume_data)

        # Weighted composite
        weights = {"entry": 0.25, "exit": 0.15, "volatility": 0.35, "liquidity": 0.25}
        composite = (
            entry_risk * weights["entry"]
            + exit_risk * weights["exit"]
            + volatility_risk * weights["volatility"]
            + liquidity_risk * weights["liquidity"]
        )

        # Risk level
        if composite < 25:
            level = "LOW"
        elif composite < 50:
            level = "MEDIUM"
        elif composite < 75:
            level = "HIGH"
        else:
            level = "CRITICAL"

        return {
            "composite_score": round(composite, 2),
            "level": level,
            "components": {
                "entry_risk": round(entry_risk, 2),
                "exit_risk": round(exit_risk, 2),
                "volatility_risk": round(volatility_risk, 2),
                "liquidity_risk": round(liquidity_risk, 2),
            },
            "weights": weights,
            "recommendation": self._get_trade_recommendation(composite),
        }

    def _get_trade_recommendation(self, score: float) -> str:
        """Get trade recommendation based on composite score."""
        if score < 20:
            return "FAVORABLE: Low risk entry opportunity for paper trade"
        elif score < 40:
            return "MODERATE: Manageable risk, consider small paper position"
        elif score < 60:
            return "CAUTIOUS: Elevated risk, reduce paper position size"
        elif score < 80:
            return "HIGH RISK: Significant risk, avoid paper trade or very small position"
        return "EXTREME RISK: Do not paper trade under these conditions"
