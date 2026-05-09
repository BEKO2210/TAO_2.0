"""
Subnet Discovery Agent (Agent 3).

Discovers and catalogs Bittensor subnets, gathering information
about NetUID, name, purpose, repositories, documentation, and
hardware requirements. Provides a preliminary traffic-light rating.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_NAME: str = "subnet_discovery_agent"
AGENT_VERSION: str = "1.0.0"


class SubnetDiscoveryAgent:
    """
    Agent for discovering and cataloging Bittensor subnets.

    Gathers metadata about available subnets including NetUID, name,
    purpose, source repositories, documentation links, and hardware
    requirements. Provides a preliminary traffic-light assessment
    (green/yellow/red) for quick filtering.
    """

    # Known subnet catalog (will be expanded with live discovery)
    _KNOWN_SUBNETS: list[dict[str, Any]] = [
        {
            "netuid": 0,
            "name": "Root",
            "purpose": "Network governance and root weights",
            "category": "governance",
            "repo_url": "https://github.com/opentensor/bittensor",
            "docs_url": "https://docs.bittensor.com",
            "hardware_min": {"cpu_cores": 4, "ram_gb": 16, "gpu": "optional"},
            "active": True,
        },
        {
            "netuid": 1,
            "name": "Text Prompting",
            "purpose": "Text generation and prompt-based AI tasks",
            "category": "nlp",
            "repo_url": "https://github.com/opentensor/prompting",
            "docs_url": "https://docs.bittensor.com/subnets/subnet-1",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 16},
            "active": True,
        },
        {
            "netuid": 2,
            "name": "Machine Translation",
            "purpose": "Translation between languages using AI",
            "category": "nlp",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 4, "ram_gb": 16, "gpu": "optional"},
            "active": True,
        },
        {
            "netuid": 3,
            "name": "Data Scraping",
            "purpose": "Web scraping and data collection",
            "category": "data",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 4, "ram_gb": 16, "gpu": "not_needed"},
            "active": True,
        },
        {
            "netuid": 4,
            "name": "Multi-Modality",
            "purpose": "Multi-modal AI tasks (vision + language)",
            "category": "multimodal",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 24},
            "active": True,
        },
        {
            "netuid": 5,
            "name": "Image Generation",
            "purpose": "Generative AI for images",
            "category": "vision",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 24},
            "active": True,
        },
        {
            "netuid": 6,
            "name": "Storage",
            "purpose": "Decentralized storage solutions",
            "category": "infrastructure",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 4, "ram_gb": 16, "gpu": "not_needed", "disk_tb": 1},
            "active": True,
        },
        {
            "netuid": 7,
            "name": "Audio Generation",
            "purpose": "Text-to-speech and audio generation",
            "category": "audio",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 16},
            "active": True,
        },
        {
            "netuid": 8,
            "name": "Text-to-Speech",
            "purpose": "Speech synthesis from text",
            "category": "audio",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 16},
            "active": True,
        },
        {
            "netuid": 9,
            "name": "Data Universe",
            "purpose": "Large-scale data collection and processing",
            "category": "data",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "optional"},
            "active": True,
        },
        {
            "netuid": 10,
            "name": "Map Reduce",
            "purpose": "Distributed computation framework",
            "category": "compute",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 4, "ram_gb": 16, "gpu": "not_needed"},
            "active": True,
        },
        {
            "netuid": 11,
            "name": "Transcription",
            "purpose": "Speech-to-text transcription",
            "category": "audio",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 16},
            "active": True,
        },
        {
            "netuid": 12,
            "name": "Horde",
            "purpose": "Distributed inference network",
            "category": "inference",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 16},
            "active": True,
        },
        {
            "netuid": 18,
            "name": "Cortex.t",
            "purpose": "LLM inference and API endpoints",
            "category": "inference",
            "repo_url": "https://github.com/corcel-api/cortex.t",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 16, "ram_gb": 64, "gpu": "required", "vram_gb": 48},
            "active": True,
        },
        {
            "netuid": 19,
            "name": "Vision",
            "purpose": "Computer vision and image understanding",
            "category": "vision",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 24},
            "active": True,
        },
        {
            "netuid": 22,
            "name": "Meta Search",
            "purpose": "AI-powered search engine",
            "category": "search",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "optional"},
            "active": True,
        },
        {
            "netuid": 25,
            "name": "Hivemind",
            "purpose": "Decentralized reasoning",
            "category": "reasoning",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 8, "ram_gb": 32, "gpu": "required", "vram_gb": 24},
            "active": True,
        },
        {
            "netuid": 27,
            "name": "Compute",
            "purpose": "General compute marketplace",
            "category": "compute",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 4, "ram_gb": 16, "gpu": "optional"},
            "active": True,
        },
        {
            "netuid": 32,
            "name": "Its-AI",
            "purpose": "AI-generated text detection",
            "category": "nlp",
            "repo_url": "",
            "docs_url": "",
            "hardware_min": {"cpu_cores": 4, "ram_gb": 16, "gpu": "optional"},
            "active": True,
        },
    ]

    def __init__(self, config: dict) -> None:
        """
        Initialize the SubnetDiscoveryAgent.

        Args:
            config: Configuration dictionary with optional:
                - subnets: Pre-defined subnet list
                - filter_active: Only show active subnets
                - categories: Filter by category list
        """
        self.config: dict = config
        self._status: str = "idle"
        self._discovery_log: list[dict] = []
        self._subnets: list[dict] = list(self._KNOWN_SUBNETS)
        self._filter_active: bool = config.get("filter_active", True)
        self._categories: list[str] = config.get("categories", [])
        logger.info(
            "SubnetDiscoveryAgent initialized (known_subnets=%d)",
            len(self._subnets),
        )

    def run(self, task: dict) -> dict:
        """
        Run subnet discovery.

        Args:
            task: Dictionary with optional 'params' containing:
                - filter: Category or name filter string
                - netuid: Specific NetUID to look up
                - include_inactive: Include inactive subnets

        Returns:
            Discovery results with subnet list and assessments
        """
        self._status = "running"
        params = task.get("params", {})
        filter_str = params.get("filter", "")
        netuid_filter = params.get("netuid")
        include_inactive = params.get("include_inactive", False)

        logger.info("SubnetDiscoveryAgent: discovering subnets")

        try:
            # Filter subnets
            filtered_subnets = self._filter_subnets(
                filter_str=filter_str,
                netuid_filter=netuid_filter,
                include_inactive=include_inactive,
            )

            # Add traffic-light rating
            rated_subnets = [self._rate_subnet(s) for s in filtered_subnets]

            # Sort by rating (green first)
            rated_subnets.sort(key=lambda s: {"green": 0, "yellow": 1, "red": 2}.get(s["rating"], 3))

            result = {
                "status": "complete",
                "subnet_count": len(rated_subnets),
                "subnets": rated_subnets,
                "summary": self._generate_summary(rated_subnets),
                "filters_applied": {
                    "filter": filter_str,
                    "netuid": netuid_filter,
                    "include_inactive": include_inactive,
                },
            }

            self._discovery_log.append({
                "timestamp": time.time(),
                "filter": filter_str,
                "results_count": len(rated_subnets),
            })
            self._status = "complete"
            logger.info(
                "SubnetDiscoveryAgent: discovered %d subnets", len(rated_subnets)
            )
            return result

        except Exception as e:
            self._status = "error"
            logger.exception("SubnetDiscoveryAgent: discovery failed: %s", e)
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
            "discovery_count": len(self._discovery_log),
            "known_subnets": len(self._subnets),
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
        netuid = params.get("netuid")
        if netuid is not None and not isinstance(netuid, int):
            return False, "netuid must be an integer"
        return True, ""

    def _filter_subnets(
        self,
        filter_str: str = "",
        netuid_filter: int | None = None,
        include_inactive: bool = False,
    ) -> list[dict]:
        """
        Filter subnets based on criteria.

        Args:
            filter_str: Name or category filter
            netuid_filter: Specific NetUID
            include_inactive: Whether to include inactive subnets

        Returns:
            Filtered list of subnet dictionaries
        """
        result = list(self._subnets)

        # Filter by active status
        if not include_inactive and self._filter_active:
            result = [s for s in result if s.get("active", True)]

        # Filter by NetUID
        if netuid_filter is not None:
            result = [s for s in result if s.get("netuid") == netuid_filter]

        # Filter by categories from config
        if self._categories:
            result = [
                s for s in result
                if s.get("category", "").lower() in [c.lower() for c in self._categories]
            ]

        # Filter by string
        if filter_str:
            filter_lower = filter_str.lower()
            result = [
                s for s in result
                if filter_lower in s.get("name", "").lower()
                or filter_lower in s.get("purpose", "").lower()
                or filter_lower in s.get("category", "").lower()
            ]

        return result

    def _rate_subnet(self, subnet: dict) -> dict:
        """
        Provide a preliminary traffic-light rating for a subnet.

        Green: Good documentation, active, reasonable hardware
        Yellow: Limited documentation, moderate hardware requirements
        Red: No documentation, very high hardware, or other concerns

        Args:
            subnet: Subnet dictionary

        Returns:
            Subnet dictionary with added 'rating' and 'rating_reasons' keys
        """
        rated = dict(subnet)
        reasons: list[str] = []
        score = 0

        # Check documentation
        if rated.get("repo_url"):
            score += 2
            reasons.append("Has repository link")
        else:
            reasons.append("No repository link found")

        if rated.get("docs_url"):
            score += 2
            reasons.append("Has documentation link")
        else:
            reasons.append("No documentation link")

        # Check hardware requirements
        hw = rated.get("hardware_min", {})
        if hw.get("gpu") == "not_needed":
            score += 2
            reasons.append("No GPU required - accessible")
        elif hw.get("gpu") == "optional":
            score += 1
            reasons.append("GPU optional - flexible")
        elif hw.get("gpu") == "required":
            vram = hw.get("vram_gb", 0)
            if vram <= 16:
                score += 1
                reasons.append(f"GPU required but moderate ({vram}GB VRAM)")
            elif vram <= 24:
                score += 0
                reasons.append(f"GPU required, high VRAM ({vram}GB)")
            else:
                score -= 1
                reasons.append(f"GPU required, very high VRAM ({vram}GB)")

        # RAM requirement
        ram = hw.get("ram_gb", 16)
        if ram <= 16:
            score += 2
        elif ram <= 32:
            score += 1
        else:
            score -= 1
            reasons.append(f"High RAM requirement ({ram}GB)")

        # Active status
        if rated.get("active", True):
            score += 2
            reasons.append("Subnet is active")
        else:
            score -= 2
            reasons.append("Subnet is inactive")

        # Determine rating
        if score >= 6:
            rating = "green"
        elif score >= 3:
            rating = "yellow"
        else:
            rating = "red"

        rated["rating"] = rating
        rated["rating_score"] = score
        rated["rating_reasons"] = reasons
        return rated

    def _generate_summary(self, subnets: list[dict]) -> dict:
        """
        Generate summary statistics for discovered subnets.

        Args:
            subnets: List of rated subnet dictionaries

        Returns:
            Summary dictionary
        """
        if not subnets:
            return {"total": 0, "green": 0, "yellow": 0, "red": 0}

        green = sum(1 for s in subnets if s.get("rating") == "green")
        yellow = sum(1 for s in subnets if s.get("rating") == "yellow")
        red = sum(1 for s in subnets if s.get("rating") == "red")

        categories: dict[str, int] = {}
        for s in subnets:
            cat = s.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        gpu_required = sum(
            1 for s in subnets
            if s.get("hardware_min", {}).get("gpu") == "required"
        )
        gpu_optional = sum(
            1 for s in subnets
            if s.get("hardware_min", {}).get("gpu") == "optional"
        )
        no_gpu = sum(
            1 for s in subnets
            if s.get("hardware_min", {}).get("gpu") == "not_needed"
        )

        return {
            "total": len(subnets),
            "green": green,
            "yellow": yellow,
            "red": red,
            "categories": categories,
            "gpu_breakdown": {
                "required": gpu_required,
                "optional": gpu_optional,
                "not_needed": no_gpu,
            },
        }
