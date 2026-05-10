"""
Dashboard Design Agent (Agent 12).

Designs the monitoring dashboard for system status, wallet,
market data, and subnets. Design goals: clear, dark theme, technical.

Provides dashboard design specifications.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "dashboard_design_agent"
AGENT_VERSION: str = "1.0.0"


class DashboardDesignAgent:
    """
    Agent for designing the monitoring dashboard.

    Creates design specifications for a monitoring dashboard covering
    system status, wallet overview, market data, and subnet information.
    Design philosophy: clear, dark theme, technical.
    """

    # Design system
    _DESIGN_SYSTEM: dict[str, Any] = {
        "theme": "dark",
        "name": "TAO Control Center",
        "primary_color": "#00D4AA",  # Teal/cyan - TAO brand
        "secondary_color": "#6366F1",  # Indigo
        "success_color": "#22C55E",  # Green
        "warning_color": "#EAB308",  # Yellow
        "danger_color": "#EF4444",  # Red
        "info_color": "#3B82F6",  # Blue
        "background": {
            "page": "#0F172A",  # Slate 900
            "card": "#1E293B",  # Slate 800
            "card_hover": "#334155",  # Slate 700
            "input": "#0F172A",  # Slate 900
        },
        "text": {
            "primary": "#F1F5F9",  # Slate 100
            "secondary": "#94A3B8",  # Slate 400
            "muted": "#64748B",  # Slate 500
        },
        "border": {
            "default": "#334155",  # Slate 700
            "focus": "#00D4AA",  # Primary
        },
        "typography": {
            "heading_font": "'Inter', 'SF Pro Display', system-ui, sans-serif",
            "body_font": "'Inter', 'SF Pro Text', system-ui, sans-serif",
            "mono_font": "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace",
            "heading_sizes": {
                "h1": "2rem",
                "h2": "1.5rem",
                "h3": "1.25rem",
                "h4": "1rem",
            },
        },
        "spacing": {
            "xs": "0.25rem",
            "sm": "0.5rem",
            "md": "1rem",
            "lg": "1.5rem",
            "xl": "2rem",
        },
        "border_radius": {
            "sm": "0.25rem",
            "md": "0.5rem",
            "lg": "0.75rem",
            "xl": "1rem",
        },
    }

    def __init__(self, config: dict) -> None:
        """
        Initialize the DashboardDesignAgent.

        Args:
            config: Configuration with optional:
                - theme: Override theme
                - panels: List of panels to include
                - refresh_interval: Data refresh interval
        """
        self.config: dict = config
        self._status: str = "idle"
        self._panels: list[str] = config.get(
            "panels",
            ["system", "wallet", "market", "subnets", "agents", "logs"],
        )
        self._refresh_interval: int = config.get("refresh_interval", 30)

        logger.info(
            "DashboardDesignAgent initialized (panels=%d, refresh=%ds)",
            len(self._panels), self._refresh_interval,
        )

    def run(self, task: dict) -> dict:
        """
        Run dashboard design.

        Args:
            task: Dictionary with 'params' containing:
                - action: "spec", "panel", "theme"
                - panel_type: Specific panel to design

        Returns:
            Dashboard design specification
        """
        self._status = "running"
        params = task.get("params", {})
        action = params.get("action", "spec")

        logger.info("DashboardDesignAgent: action=%s", action)

        # Pull subnet-scoring upstream so the dashboard layout
        # references the actual top subnets the swarm has scored —
        # generic 'subnet 1' panels are useless to the operator.
        upstream_seen: list[str] = []
        ctx = getattr(self, "context", None)
        if ctx is not None and "scored_subnets" not in params:
            scoring = ctx.get("subnet_scoring_agent")
            if isinstance(scoring, dict):
                scored = scoring.get("scored_subnets") or []
                if scored:
                    params["scored_subnets"] = scored[:5]
                    upstream_seen.append("subnet_scoring_agent")

        try:
            if action == "spec":
                result = self._generate_full_spec(params)
            elif action == "panel":
                result = self._design_panel(params)
            elif action == "theme":
                result = self._generate_theme_spec(params)
            else:
                result = {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                }

            result.setdefault("_meta", {})["upstream_seen"] = list(upstream_seen)
            self._status = "complete"
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("DashboardDesignAgent: failed: %s", e)
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
            "panels": self._panels,
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
        action = params.get("action", "spec")
        valid_actions = ["spec", "panel", "theme"]
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"
        return True, ""

    def _generate_full_spec(self, params: dict) -> dict:
        """
        Generate the full dashboard design specification.

        Args:
            params: Design parameters

        Returns:
            Full design spec
        """
        panels: list[dict] = []

        if "system" in self._panels:
            panels.append(self._get_system_panel_spec())
        if "wallet" in self._panels:
            panels.append(self._get_wallet_panel_spec())
        if "market" in self._panels:
            panels.append(self._get_market_panel_spec())
        if "subnets" in self._panels:
            panels.append(self._get_subnets_panel_spec())
        if "agents" in self._panels:
            panels.append(self._get_agents_panel_spec())
        if "logs" in self._panels:
            panels.append(self._get_logs_panel_spec())

        # Layout specification
        layout = {
            "type": "grid",
            "columns": 12,
            "gap": "1rem",
            "breakpoints": {
                "mobile": "< 768px (1 column)",
                "tablet": "768-1024px (6 columns)",
                "desktop": "> 1024px (12 columns)",
            },
            "panel_sizes": {
                "small": {"cols": 4, "rows": "auto"},
                "medium": {"cols": 6, "rows": "auto"},
                "large": {"cols": 12, "rows": "auto"},
            },
        }

        return {
            "status": "spec_generated",
            "design_system": self._DESIGN_SYSTEM,
            "dashboard": {
                "name": "TAO Control Center",
                "description": "Central monitoring dashboard for TAO/Bittensor operations",
                "version": "1.0.0",
            },
            "layout": layout,
            "panels": panels,
            "interactions": self._get_interactions_spec(),
            "data_refresh": {
                "interval_seconds": self._refresh_interval,
                "auto_refresh": True,
                "manual_refresh_button": True,
                "last_refresh_display": True,
            },
            "timestamp": time.time(),
        }

    def _design_panel(self, params: dict) -> dict:
        """
        Design a specific panel.

        Args:
            params: Panel parameters

        Returns:
            Panel design spec
        """
        panel_type = params.get("panel_type", "system")

        panel_specs: dict[str, dict] = {
            "system": self._get_system_panel_spec(),
            "wallet": self._get_wallet_panel_spec(),
            "market": self._get_market_panel_spec(),
            "subnets": self._get_subnets_panel_spec(),
            "agents": self._get_agents_panel_spec(),
            "logs": self._get_logs_panel_spec(),
        }

        return {
            "status": "panel_designed",
            "panel": panel_specs.get(panel_type, {}),
            "panel_type": panel_type,
            "timestamp": time.time(),
        }

    def _generate_theme_spec(self, params: dict) -> dict:
        """
        Generate theme specification.

        Args:
            params: Theme parameters

        Returns:
            Theme spec
        """
        return {
            "status": "theme_generated",
            "theme": self._DESIGN_SYSTEM,
            "css_variables": self._generate_css_variables(),
            "timestamp": time.time(),
        }

    def _get_system_panel_spec(self) -> dict:
        """Get system status panel specification."""
        return {
            "id": "panel-system",
            "title": "System Status",
            "icon": "monitor",
            "size": "medium",
            "position": {"col": 0, "row": 0, "colspan": 6},
            "components": [
                {
                    "type": "metric_card",
                    "metrics": [
                        {"label": "CPU Usage", "field": "cpu_percent", "unit": "%", "color_by_value": True},
                        {"label": "RAM Usage", "field": "ram_percent", "unit": "%", "color_by_value": True},
                        {"label": "GPU Usage", "field": "gpu_percent", "unit": "%", "color_by_value": True},
                        {"label": "Disk Free", "field": "disk_free_gb", "unit": "GB"},
                    ],
                },
                {
                    "type": "status_list",
                    "items": [
                        {"label": "Python", "field": "python_ok"},
                        {"label": "Docker", "field": "docker_ok"},
                        {"label": "Git", "field": "git_ok"},
                        {"label": "CUDA", "field": "cuda_ok"},
                    ],
                },
                {
                    "type": "readiness_bar",
                    "items": [
                        {"label": "Testnet", "field": "testnet_ready"},
                        {"label": "Miner", "field": "miner_ready"},
                        {"label": "Validator", "field": "validator_ready"},
                    ],
                },
            ],
            "data_source": "system_check_agent",
            "refresh_interval": 30,
        }

    def _get_wallet_panel_spec(self) -> dict:
        """Get wallet panel specification."""
        return {
            "id": "panel-wallet",
            "title": "Wallet Overview",
            "icon": "wallet",
            "size": "medium",
            "position": {"col": 6, "row": 0, "colspan": 6},
            "components": [
                {
                    "type": "balance_card",
                    "metrics": [
                        {"label": "Total Balance", "field": "total_balance_tao", "unit": "TAO", "highlight": True},
                        {"label": "Total Staked", "field": "total_staked_tao", "unit": "TAO"},
                        {"label": "Portfolio Value", "field": "total_portfolio_tao", "unit": "TAO"},
                    ],
                },
                {
                    "type": "address_list",
                    "columns": [
                        {"label": "Label", "field": "label"},
                        {"label": "Address", "field": "address", "truncate": True},
                        {"label": "Balance", "field": "balance_tao", "unit": "TAO"},
                        {"label": "Staked", "field": "staked_tao", "unit": "TAO"},
                    ],
                },
                {
                    "type": "mini_chart",
                    "chart_type": "bar",
                    "title": "Balance Distribution",
                },
            ],
            "data_source": "wallet_watch_agent",
            "refresh_interval": 60,
            "safety_note": "WATCH-ONLY: No keys stored or accessible",
        }

    def _get_market_panel_spec(self) -> dict:
        """Get market data panel specification."""
        return {
            "id": "panel-market",
            "title": "TAO Market",
            "icon": "trending_up",
            "size": "medium",
            "position": {"col": 0, "row": 1, "colspan": 6},
            "components": [
                {
                    "type": "price_card",
                    "metrics": [
                        {"label": "Price USD", "field": "current_price", "unit": "$", "highlight": True},
                        {"label": "24h Change", "field": "change_24h_pct", "unit": "%", "color_by_sign": True},
                        {"label": "24h High", "field": "high_24h", "unit": "$"},
                        {"label": "24h Low", "field": "low_24h", "unit": "$"},
                    ],
                },
                {
                    "type": "chart",
                    "chart_type": "line",
                    "title": "Price History (24h)",
                    "x_axis": "time",
                    "y_axis": "price",
                },
                {
                    "type": "volume_bar",
                    "title": "24h Volume",
                    "field": "volume_24h",
                    "unit": "USD",
                },
            ],
            "data_source": "market_trade_agent",
            "refresh_interval": 60,
        }

    def _get_subnets_panel_spec(self) -> dict:
        """Get subnets panel specification."""
        return {
            "id": "panel-subnets",
            "title": "Subnets",
            "icon": "grid",
            "size": "large",
            "position": {"col": 0, "row": 2, "colspan": 8},
            "components": [
                {
                    "type": "data_table",
                    "title": "Subnet Overview",
                    "columns": [
                        {"label": "NetUID", "field": "netuid", "sortable": True, "width": "80px"},
                        {"label": "Name", "field": "name", "sortable": True},
                        {"label": "Category", "field": "category", "sortable": True},
                        {"label": "Rating", "field": "rating", "badge": True},
                        {"label": "Score", "field": "rating_score", "sortable": True},
                        {"label": "GPU", "field": "hardware_min.gpu", "sortable": True},
                    ],
                    "filters": [
                        {"field": "rating", "type": "select", "options": ["green", "yellow", "red"]},
                        {"field": "category", "type": "select", "options": "auto"},
                    ],
                    "sort_default": {"field": "rating_score", "direction": "desc"},
                },
                {
                    "type": "summary_cards",
                    "metrics": [
                        {"label": "Total Subnets", "field": "total"},
                        {"label": "Green", "field": "green", "color": "success"},
                        {"label": "Yellow", "field": "yellow", "color": "warning"},
                        {"label": "Red", "field": "red", "color": "danger"},
                    ],
                },
            ],
            "data_sources": ["subnet_discovery_agent", "subnet_scoring_agent"],
            "refresh_interval": 300,
        }

    def _get_agents_panel_spec(self) -> dict:
        """Get agents panel specification."""
        return {
            "id": "panel-agents",
            "title": "Agent Swarm",
            "icon": "users",
            "size": "small",
            "position": {"col": 8, "row": 2, "colspan": 4},
            "components": [
                {
                    "type": "agent_grid",
                    "columns": [
                        {"label": "Agent", "field": "agent_name"},
                        {"label": "Status", "field": "status", "badge": True},
                        {"label": "Version", "field": "version"},
                    ],
                },
                {
                    "type": "health_summary",
                    "metrics": [
                        {"label": "Active", "field": "active_count"},
                        {"label": "Idle", "field": "idle_count"},
                        {"label": "Error", "field": "error_count"},
                    ],
                },
            ],
            "data_source": "orchestrator",
            "refresh_interval": 15,
        }

    def _get_logs_panel_spec(self) -> dict:
        """Get logs panel specification."""
        return {
            "id": "panel-logs",
            "title": "System Logs",
            "icon": "file_text",
            "size": "large",
            "position": {"col": 0, "row": 3, "colspan": 12},
            "components": [
                {
                    "type": "log_viewer",
                    "features": [
                        "search",
                        "filter_by_level",
                        "auto_scroll",
                        "export",
                        "timestamp_formatting",
                    ],
                    "log_levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                    "max_lines": 1000,
                },
            ],
            "data_source": "system_log",
            "refresh_interval": 5,
        }

    def _get_interactions_spec(self) -> dict:
        """Get interaction design specification."""
        return {
            "click_to_drill_down": True,
            "hover_tooltips": True,
            "filter_persistence": True,
            "export_csv": True,
            "export_json": True,
            "keyboard_shortcuts": {
                "r": "Refresh all panels",
                "f": "Focus search",
                "1-6": "Switch to panel N",
                "?": "Show help",
            },
            "notifications": {
                "enabled": True,
                "types": ["error", "warning", "info"],
                "position": "top-right",
                "auto_dismiss": True,
                "dismiss_delay_seconds": 10,
            },
        }

    def _generate_css_variables(self) -> dict:
        """Generate CSS custom properties."""
        ds = self._DESIGN_SYSTEM
        return {
            "--color-primary": ds["primary_color"],
            "--color-secondary": ds["secondary_color"],
            "--color-success": ds["success_color"],
            "--color-warning": ds["warning_color"],
            "--color-danger": ds["danger_color"],
            "--color-info": ds["info_color"],
            "--bg-page": ds["background"]["page"],
            "--bg-card": ds["background"]["card"],
            "--bg-card-hover": ds["background"]["card_hover"],
            "--text-primary": ds["text"]["primary"],
            "--text-secondary": ds["text"]["secondary"],
            "--text-muted": ds["text"]["muted"],
            "--border-default": ds["border"]["default"],
            "--border-focus": ds["border"]["focus"],
            "--font-heading": ds["typography"]["heading_font"],
            "--font-body": ds["typography"]["body_font"],
            "--font-mono": ds["typography"]["mono_font"],
            "--radius-sm": ds["border_radius"]["sm"],
            "--radius-md": ds["border_radius"]["md"],
            "--radius-lg": ds["border_radius"]["lg"],
        }
