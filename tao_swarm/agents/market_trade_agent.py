"""
Market & Trade Agent (Agent 6).

TAO market analysis agent. Provides price, volume, volatility, and
liquidity analysis. Trade ideas are analysis-only - NO automatic
orders are ever placed. Paper trading is the default mode.

SAFETY: All trading actions are CAUTION or DANGER. No real trades.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "market_trade_agent"
AGENT_VERSION: str = "1.0.0"


class MarketTradeAgent:
    """
    TAO market analysis and trade research agent.

    Analyzes TAO market data including price, volume, volatility,
    and liquidity. Generates trade analysis reports with ideas and
    risk assessments. Operates in paper trading mode by default -
    never executes real trades.

    All actual trading actions classify as DANGER and require
    explicit manual approval.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the MarketTradeAgent.

        Args:
            config: Configuration with optional:
                - paper_trading: Enable paper trading (default True)
                - use_mock_data: Use mock data (default True)
                - analysis_timeframe: Default timeframe (default "1d")
                - risk_tolerance: Risk level (default "medium")
                - market_collector: Pre-built ``MarketDataCollector``
                  (mainly for tests / dependency injection).
                - market_db_path: SQLite cache path for the collector
                  (default ``data/market_cache.db``).
        """
        self.config: dict = config
        self._status: str = "idle"
        self._paper_trading: bool = config.get("paper_trading", True)
        self._use_mock: bool = config.get("use_mock_data", True)
        self._timeframe: str = config.get("analysis_timeframe", "1d")
        self._risk_tolerance: str = config.get("risk_tolerance", "medium")
        self._trade_log: list[dict] = []
        self._analysis_history: list[dict] = []
        # Lazily-instantiated market collector. Tests can inject one
        # via config["market_collector"]; otherwise we build one with
        # config-derived settings on first use.
        self._market_collector: Any = config.get("market_collector")

        if not self._paper_trading:
            logger.warning(
                "MarketTradeAgent: paper_trading=False detected - "
                "all trade actions will classify as DANGER"
            )

        logger.info(
            "MarketTradeAgent initialized (paper=%s, mock=%s)",
            self._paper_trading, self._use_mock,
        )

    def run(self, task: dict) -> dict:
        """
        Run market analysis or paper trading task.

        Args:
            task: Dictionary with 'params' containing:
                - action: "analyze", "paper_trade", "check_position", "history"
                - symbol: Token symbol (default "TAO")
                - timeframe: Analysis timeframe

        Returns:
            Trade analysis report
        """
        self._status = "running"
        params = task.get("params", {})
        action = params.get("action", "analyze")
        symbol = params.get("symbol", "TAO")

        logger.info("MarketTradeAgent: action=%s, symbol=%s", action, symbol)

        # Pull upstream subnet-scoring output so the market view can
        # explicitly call out the top-scored subnets the operator is
        # already watching, instead of producing a generic "TAO went
        # up" report.
        upstream_seen: list[str] = []
        scoring_top: list[dict] = []
        ctx = getattr(self, "context", None)
        if ctx is not None:
            scoring = ctx.get("subnet_scoring_agent")
            if isinstance(scoring, dict):
                top = scoring.get("scored_subnets") or []
                if isinstance(top, list):
                    scoring_top = top[:5]
                    if scoring_top:
                        upstream_seen.append("subnet_scoring_agent")
        # Stash for sub-handlers to consume.
        params["_upstream_top_subnets"] = scoring_top

        try:
            if action == "analyze":
                result = self._analyze_market(params)
            elif action == "paper_trade":
                result = self._paper_trade(params)
            elif action == "check_position":
                result = self._check_position(params)
            elif action == "history":
                result = self._get_trade_history(params)
            else:
                result = {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                }

            self._analysis_history.append({
                "timestamp": time.time(),
                "action": action,
                "symbol": symbol,
            })
            # Surface the upstream-context-pull result so the
            # operator can tell whether this report was conditioned
            # on subnet scoring or stand-alone.
            meta = result.setdefault("_meta", {})
            meta["upstream_seen"] = list(upstream_seen)
            if scoring_top:
                result.setdefault(
                    "subnet_focus",
                    [
                        {
                            "netuid": s.get("netuid"),
                            "name": s.get("name"),
                            "final_score": s.get("final_score"),
                        }
                        for s in scoring_top
                    ],
                )
            self._status = "complete"
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("MarketTradeAgent: failed: %s", e)
            return {
                "status": "error",
                "reason": str(e),
                "agent_name": AGENT_NAME,
                "task_type": task.get("type"),
            }

    def get_status(self) -> dict:
        """
        Get current agent status.

        Returns:
            Status dictionary
        """
        return {
            "agent_name": AGENT_NAME,
            "version": AGENT_VERSION,
            "status": self._status,
            "paper_trading": self._paper_trading,
            "trades_simulated": len(self._trade_log),
            "analyses": len(self._analysis_history),
            "mode": "PAPER_TRADING" if self._paper_trading else "ANALYSIS_ONLY",
        }

    def validate_input(self, task: dict) -> tuple[bool, str]:
        """
        Validate task input.

        Args:
            task: Task dictionary to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(task, dict):
            return False, "Task must be a dictionary"
        if "type" not in task:
            return False, "task.type is required"

        params = task.get("params", {})
        action = params.get("action", "analyze")
        valid_actions = ["analyze", "paper_trade", "check_position", "history"]

        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"

        # Security: reject any real trading parameters
        task_str = str(task).lower()
        dangerous = [
            "private_key", "api_key", "api_secret", "execute_trade",
            "real_trade", "live_trade", "place_order",
        ]
        for d in dangerous:
            if d in task_str:
                logger.critical(
                    "SECURITY: MarketTradeAgent received dangerous parameter: %s", d
                )
                return False, f"Security violation: dangerous parameter '{d}'"

        return True, ""

    def _analyze_market(self, params: dict) -> dict:
        """
        Perform comprehensive market analysis.

        Args:
            params: Analysis parameters

        Returns:
            Market analysis report
        """
        symbol = params.get("symbol", "TAO")
        timeframe = params.get("timeframe", self._timeframe)

        # Get market data
        price_data = self._get_price_data(symbol, timeframe)
        volume_data = self._get_volume_data(symbol, timeframe)
        volatility = self._calculate_volatility(price_data)
        liquidity = self._analyze_liquidity(symbol)

        # Generate trade ideas
        trade_ideas = self._generate_trade_ideas(
            price_data, volume_data, volatility, liquidity
        )

        return {
            "status": "analyzed",
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": time.time(),
            "analysis": {
                "price": price_data,
                "volume": volume_data,
                "volatility": volatility,
                "liquidity": liquidity,
            },
            "trade_ideas": trade_ideas,
            "risk_assessment": self._assess_trade_risk(
                price_data, volatility, liquidity
            ),
            "disclaimer": (
                "This is analysis only. No trades were executed. "
                "Paper trading mode is active."
            ),
        }

    def _paper_trade(self, params: dict) -> dict:
        """
        Execute a paper (simulated) trade.

        Args:
            params: Trade parameters

        Returns:
            Paper trade result
        """
        symbol = params.get("symbol", "TAO")
        side = params.get("side", "buy")  # buy or sell
        amount = params.get("amount", 1.0)
        price = params.get("price")

        # Get current price if not specified
        if price is None:
            price_data = self._get_price_data(symbol, self._timeframe)
            price = price_data.get("current", 0)

        # Simulate slippage (0.1-0.5%)
        import random
        slippage = round(random.uniform(0.001, 0.005), 4)
        executed_price = (
            price * (1 + slippage) if side == "buy"
            else price * (1 - slippage)
        )

        trade_record = {
            "timestamp": time.time(),
            "symbol": symbol,
            "side": side,
            "requested_amount": amount,
            "requested_price": price,
            "executed_price": round(executed_price, 4),
            "slippage_pct": round(slippage * 100, 2),
            "total_value": round(amount * executed_price, 4),
            "mode": "paper",
            "pnl": None,  # Will be updated on close
        }

        self._trade_log.append(trade_record)

        logger.info(
            "Paper trade: %s %s %s @ %.4f (slippage=%.2f%%)",
            side.upper(), amount, symbol, executed_price, slippage * 100,
        )

        return {
            "status": "paper_executed",
            "trade": trade_record,
            "note": "This was a PAPER (simulated) trade. No real funds were used.",
        }

    def _check_position(self, params: dict) -> dict:
        """
        Check current paper trading positions.

        Args:
            params: Check parameters

        Returns:
            Position report
        """
        symbol = params.get("symbol", "TAO")

        # Filter trades for symbol
        symbol_trades = [t for t in self._trade_log if t["symbol"] == symbol]

        buys = [t for t in symbol_trades if t["side"] == "buy"]
        sells = [t for t in symbol_trades if t["side"] == "sell"]

        total_bought = sum(t["total_value"] for t in buys)
        total_sold = sum(t["total_value"] for t in sells)
        net_position = len(buys) - len(sells)

        return {
            "status": "checked",
            "symbol": symbol,
            "total_trades": len(symbol_trades),
            "buys": len(buys),
            "sells": len(sells),
            "total_bought_value": round(total_bought, 4),
            "total_sold_value": round(total_sold, 4),
            "net_position": net_position,
            "unrealized_pnl": None,  # Would need live price
            "trades": symbol_trades,
        }

    def _get_trade_history(self, params: dict) -> dict:
        """
        Get full paper trade history.

        Args:
            params: History parameters

        Returns:
            Trade history report
        """
        symbol = params.get("symbol")
        limit = params.get("limit", 50)

        trades = self._trade_log
        if symbol:
            trades = [t for t in trades if t["symbol"] == symbol]

        return {
            "status": "history",
            "total_trades": len(self._trade_log),
            "filtered_trades": len(trades),
            "trades": trades[-limit:],
        }

    def _get_market_collector(self) -> Any:
        """
        Lazily build / return the ``MarketDataCollector``.

        Tests can inject one via ``config["market_collector"]``. Defers
        the import so the agent module is still cheap to import without
        the collector's transitive deps (``requests`` + sqlite cache).
        """
        if self._market_collector is None:
            from tao_swarm.collectors.market_data import MarketDataCollector
            self._market_collector = MarketDataCollector({
                "use_mock_data": self._use_mock,
                "db_path": self.config.get(
                    "market_db_path", "data/market_cache.db",
                ),
            })
        return self._market_collector

    def _get_price_data(self, symbol: str, timeframe: str) -> dict:
        """
        Get price data for a symbol via the ``MarketDataCollector``.

        Returns the agent-shaped dict (``current`` / ``change_24h_pct``
        / etc.) that downstream helpers (``_calculate_volatility``,
        ``_generate_trade_ideas``) expect, populated from the
        collector's richer payload. Falls back to deterministic mock
        when the collector errors out so trade-idea generation never
        crashes the agent.

        Args:
            symbol: Token symbol (only TAO is supported live; other
                symbols still produce deterministic mock data).
            timeframe: Time period (carried through for log /
                downstream consumers).

        Returns:
            Price data dictionary with keys ``symbol``, ``current``,
            ``open_24h``, ``high_24h``, ``low_24h``, ``change_24h_pct``,
            ``change_24h_value``, ``source``, ``_meta`` (from collector
            when live).
        """
        if symbol.upper() != "TAO":
            return self._get_mock_price_data(symbol, timeframe)
        try:
            collector = self._get_market_collector()
            payload = collector.get_tao_price()
        except Exception as e:
            logger.warning(
                "MarketDataCollector unavailable (%s); falling back to mock",
                e,
            )
            return self._get_mock_price_data(symbol, timeframe)

        if "error" in payload:
            logger.warning(
                "MarketDataCollector returned error: %s; falling back to mock",
                payload["error"],
            )
            mock = self._get_mock_price_data(symbol, timeframe)
            mock["_meta"] = {
                "mode": "mock",
                "fallback_reason": payload["error"],
            }
            return mock

        current = payload.get("price_usd", 0.0) or 0.0
        change_pct = payload.get("change_24h_pct", 0.0) or 0.0
        # CoinGecko ``simple/price`` doesn't expose intraday high/low,
        # so derive a defensive estimate from the 24 h change. This
        # keeps ``_calculate_volatility`` honest (range_pct ≈
        # |change_pct|) instead of reporting 0 % volatility for live
        # data. Consumers that need exact OHLC should call
        # ``MarketDataCollector.get_historical_data`` directly.
        change_factor = change_pct / 100.0
        open_24h = round(current / (1 + change_factor), 6) if (1 + change_factor) else current
        high_24h = round(max(current, open_24h) * (1 + abs(change_factor) * 0.25), 6)
        low_24h = round(min(current, open_24h) * (1 - abs(change_factor) * 0.25), 6)

        return {
            "symbol": symbol,
            "current": current,
            "open_24h": open_24h,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "change_24h_pct": change_pct,
            "change_24h_value": round(current - open_24h, 6),
            "source": "coingecko",
            "_meta": payload.get("_meta", {}),
        }

    def _get_mock_price_data(self, symbol: str, timeframe: str) -> dict:
        """Generate mock price data."""
        import hashlib
        h = hashlib.sha256(f"{symbol}{timeframe}".encode()).hexdigest()
        base = round(300 + (int(h[:4], 16) % 200), 2)
        change = round(((int(h[4:8], 16) % 100) - 50) / 10, 2)

        return {
            "symbol": symbol,
            "current": base,
            "open_24h": round(base * (1 - change / 100), 2),
            "high_24h": round(base * 1.05, 2),
            "low_24h": round(base * 0.95, 2),
            "change_24h_pct": change,
            "change_24h_value": round(base * change / 100, 4),
            "source": "mock",
        }

    def _get_volume_data(self, symbol: str, timeframe: str) -> dict:
        """
        Get volume data for a symbol via the ``MarketDataCollector``.

        Falls back to deterministic mock when the collector errors out
        or the symbol isn't TAO, so downstream trade-idea generation
        never crashes.

        Args:
            symbol: Token symbol (only TAO is live).
            timeframe: Time period (carried for log context).

        Returns:
            Volume data dictionary with keys ``volume_24h_usd``,
            ``volume_change_pct``, ``avg_daily_volume``, ``source``.
        """

        def _mock() -> dict:
            import hashlib
            h = hashlib.sha256(f"{symbol}vol{timeframe}".encode()).hexdigest()
            volume_24h = round(1000000 + (int(h[:6], 16) % 10000000), 2)
            return {
                "volume_24h_usd": volume_24h,
                "volume_change_pct": round(((int(h[6:10], 16) % 100) - 50) / 2, 2),
                "avg_daily_volume": round(volume_24h * 0.9, 2),
                "source": "mock",
            }

        if symbol.upper() != "TAO":
            return _mock()
        try:
            collector = self._get_market_collector()
            payload = collector.get_volume()
        except Exception as e:
            logger.warning(
                "MarketDataCollector volume unavailable (%s); mock fallback", e,
            )
            return _mock()

        if "error" in payload:
            logger.warning(
                "MarketDataCollector volume error: %s; mock fallback",
                payload["error"],
            )
            return _mock()

        v24 = payload.get("volume_24h_usd", 0.0) or 0.0
        return {
            "volume_24h_usd": v24,
            "volume_change_pct": payload.get("volume_change_24h", 0.0) or 0.0,
            "avg_daily_volume": round(v24 * 0.9, 2),
            "source": "coingecko",
        }

    def _calculate_volatility(self, price_data: dict) -> dict:
        """
        Calculate volatility metrics from price data.

        Args:
            price_data: Price data dictionary

        Returns:
            Volatility metrics
        """
        high = price_data.get("high_24h", 0)
        low = price_data.get("low_24h", 0)
        current = price_data.get("current", 0)

        if current > 0 and high > low:
            range_pct = round((high - low) / current * 100, 2)
        else:
            range_pct = 0

        # Classify volatility
        if range_pct < 3:
            vol_level = "low"
        elif range_pct < 8:
            vol_level = "medium"
        else:
            vol_level = "high"

        return {
            "24h_range_pct": range_pct,
            "volatility_level": vol_level,
            "high_24h": high,
            "low_24h": low,
        }

    def _analyze_liquidity(self, symbol: str) -> dict:
        """
        Analyze liquidity for a symbol.

        Args:
            symbol: Token symbol

        Returns:
            Liquidity analysis dictionary
        """
        # TAO is generally well-liquid on major exchanges
        return {
            "symbol": symbol,
            "liquidity_score": 75,
            "level": "good",
            "exchanges": ["MEXC", "KuCoin", "Gate.io", "Uniswap"],
            "spread_estimate_pct": 0.1,
            "depth_rating": "moderate",
        }

    def _generate_trade_ideas(
        self,
        price_data: dict,
        volume_data: dict,
        volatility: dict,
        liquidity: dict,
    ) -> list[dict]:
        """
        Generate trade analysis ideas.

        Args:
            price_data: Price data
            volume_data: Volume data
            volatility: Volatility metrics
            liquidity: Liquidity analysis

        Returns:
            List of trade idea dictionaries
        """
        ideas: list[dict] = []
        change = price_data.get("change_24h_pct", 0)
        vol_level = volatility.get("volatility_level", "medium")

        # Idea 1: Trend following
        if change > 5:
            ideas.append({
                "type": "trend",
                "direction": "long",
                "confidence": min(abs(change) * 2, 80),
                "reasoning": f"Strong upward momentum (+{change}% in 24h)",
                "suggested_entry": round(price_data.get("current", 0) * 0.98, 4),
                "suggested_stop": round(price_data.get("current", 0) * 0.92, 4),
                "timeframe": "short_term",
            })
        elif change < -5:
            ideas.append({
                "type": "mean_reversion",
                "direction": "long",
                "confidence": min(abs(change) * 1.5, 70),
                "reasoning": f"Oversold condition ({change}% in 24h)",
                "suggested_entry": round(price_data.get("current", 0), 4),
                "suggested_stop": round(price_data.get("current", 0) * 0.90, 4),
                "timeframe": "medium_term",
            })
        else:
            ideas.append({
                "type": "range",
                "direction": "neutral",
                "confidence": 50,
                "reasoning": f"Low momentum ({change}% in 24h) - range-bound likely",
                "suggested_entry": None,
                "suggested_stop": None,
                "timeframe": "short_term",
            })

        # Idea 2: Volatility-based
        if vol_level == "high":
            ideas.append({
                "type": "volatility",
                "direction": "neutral",
                "confidence": 60,
                "reasoning": (
                    "High volatility detected - consider reducing "
                    "position size or waiting for consolidation"
                ),
                "suggested_entry": None,
                "suggested_stop": None,
                "timeframe": "short_term",
            })

        # Idea 3: Long-term accumulation
        ideas.append({
            "type": "accumulation",
            "direction": "long",
            "confidence": 40,
            "reasoning": (
                "DCA (Dollar Cost Average) strategy for long-term "
                "TAO accumulation regardless of short-term price"
            ),
            "suggested_entry": None,
            "suggested_stop": None,
            "timeframe": "long_term",
        })

        return ideas

    def _assess_trade_risk(
        self,
        price_data: dict,
        volatility: dict,
        liquidity: dict,
    ) -> dict:
        """
        Assess trading risks.

        Args:
            price_data: Price data
            volatility: Volatility metrics
            liquidity: Liquidity analysis

        Returns:
            Risk assessment dictionary
        """
        vol_level = volatility.get("volatility_level", "medium")
        change = abs(price_data.get("change_24h_pct", 0))
        liq_score = liquidity.get("liquidity_score", 50)

        # Calculate composite risk score (0-100, higher = riskier)
        risk_score = 30  # Base risk for crypto

        if vol_level == "high":
            risk_score += 20
        elif vol_level == "medium":
            risk_score += 10

        if change > 10:
            risk_score += 15
        elif change > 5:
            risk_score += 5

        if liq_score < 50:
            risk_score += 20
        elif liq_score < 70:
            risk_score += 10

        # Risk classification
        if risk_score >= 70:
            risk_level = "high"
        elif risk_score >= 40:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "factors": {
                "volatility": vol_level,
                "price_change_24h": change,
                "liquidity": liq_score,
            },
            "recommendations": [
                "Position sizing: max 5% of portfolio per trade",
                "Use stop-losses at -8% to -12%",
                "Consider DCA instead of lump-sum entries",
                "Monitor exchange liquidity before trading",
            ],
        }
