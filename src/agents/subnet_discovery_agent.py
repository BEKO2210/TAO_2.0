"""
Subnet Discovery Agent (Agent 3).

Discovers and catalogs Bittensor subnets via the chain collector
(``src.collectors.chain_readonly.ChainReadOnlyCollector``) and
enriches each entry with a hand-curated metadata table for the
fields the chain doesn't carry (purpose, category, repo_url,
docs_url, hardware_min). Provides a preliminary traffic-light
rating per subnet.

Discovery sources, in priority order:

1. Live chain via ``ChainReadOnlyCollector.get_subnet_list()`` —
   when ``bittensor`` is installed. Reflects the real netuid space
   (60+ subnets at time of writing).
2. Chain mock list — when the SDK isn't installed; collector falls
   back to its own mock fixtures (8 subnets) and tags
   ``_meta.fallback_reason``.
3. Hand-curated metadata hints — overlaid on every chain entry to
   fill in fields the chain doesn't provide. Subnets present in
   the metadata table but missing from the chain view are
   surfaced separately so the user knows which catalog entries
   are stale.
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

    Calls the chain collector for the canonical subnet list and
    overlays hand-curated metadata (category / purpose /
    hardware_min / repo_url / docs_url) on each entry. Provides a
    preliminary traffic-light assessment (green/yellow/red) for
    quick filtering.

    Config keys:
      - ``use_mock_data`` (bool): forwarded to the chain collector.
        When True (default), the collector won't try to import
        bittensor.
      - ``filter_active`` (bool): default True; only return active
        subnets unless ``include_inactive`` is set per-task.
      - ``categories`` (list[str]): default-narrow filter on the
        ``category`` enrichment field.
      - ``chain_collector``: optional pre-built collector instance
        (mainly for tests / dependency injection).
    """

    # Hand-curated metadata for known subnets. The chain provides
    # netuid, name, owner, block-stats, neuron counts, emission —
    # but not the human-friendly fields below. We overlay these on
    # whatever the chain returns; entries here that the chain
    # doesn't see today are reported separately as "metadata-only".
    _SUBNET_METADATA_HINTS: list[dict[str, Any]] = [
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
            config: Configuration dictionary with optional keys
                listed in the class docstring.
        """
        self.config: dict = config
        self._status: str = "idle"
        self._discovery_log: list[dict] = []
        self._filter_active: bool = config.get("filter_active", True)
        self._categories: list[str] = config.get("categories", [])
        # Build a netuid → metadata-hint dict for fast overlay lookup.
        self._metadata_by_netuid: dict[int, dict] = {
            entry["netuid"]: dict(entry)
            for entry in self._SUBNET_METADATA_HINTS
        }
        # Lazily-instantiated chain collector. Tests can inject one
        # via config["chain_collector"]; otherwise we build one with
        # config-derived settings on first use.
        self._chain_collector: Any = config.get("chain_collector")
        logger.info(
            "SubnetDiscoveryAgent initialized (metadata_hints=%d)",
            len(self._metadata_by_netuid),
        )

    def _get_chain_collector(self) -> Any:
        """Lazy chain-collector init so tests can run without a chain."""
        if self._chain_collector is None:
            from src.collectors.chain_readonly import ChainReadOnlyCollector
            chain_cfg = {
                "use_mock_data": self.config.get("use_mock_data", True),
                "network": self.config.get("network", "mock"),
                "db_path": self.config.get(
                    "chain_db_path", "data/chain_cache.db"
                ),
            }
            self._chain_collector = ChainReadOnlyCollector(chain_cfg)
        return self._chain_collector

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
            # 1) Pull the canonical subnet list from the chain collector.
            #    The collector handles mock fallback internally and tags
            #    the source on each entry via its own meta channel.
            chain_subnets, source = self._collect_subnet_list()

            # 2) Overlay our hand-curated metadata onto each chain entry,
            #    and surface metadata-only entries (known to us but not
            #    to the chain) under a separate key so the user can
            #    spot stale catalog rows.
            merged, metadata_only = self._merge_with_metadata(chain_subnets)

            # 3) Apply user-supplied filters.
            filtered_subnets = self._filter_subnets(
                merged,
                filter_str=filter_str,
                netuid_filter=netuid_filter,
                include_inactive=include_inactive,
            )

            # 4) Traffic-light rating + sort.
            rated_subnets = [self._rate_subnet(s) for s in filtered_subnets]
            rated_subnets.sort(
                key=lambda s: {"green": 0, "yellow": 1, "red": 2}.get(s["rating"], 3)
            )

            result = {
                "status": "complete",
                "subnet_count": len(rated_subnets),
                "subnets": rated_subnets,
                "metadata_only_subnets": metadata_only,
                "summary": self._generate_summary(rated_subnets),
                "source": source,
                "filters_applied": {
                    "filter": filter_str,
                    "netuid": netuid_filter,
                    "include_inactive": include_inactive,
                },
            }

            self._discovery_log.append({
                "timestamp": time.time(),
                "filter": filter_str,
                "source": source,
                "results_count": len(rated_subnets),
            })
            self._status = "complete"
            logger.info(
                "SubnetDiscoveryAgent: discovered %d subnets (source=%s)",
                len(rated_subnets), source,
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
            "metadata_hints": len(self._metadata_by_netuid),
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

    def _collect_subnet_list(self) -> tuple[list[dict], str]:
        """
        Pull the subnet list from the chain collector.

        Returns:
            Tuple of (subnet list, source tag). The source tag is one
            of ``"chain"`` (live), ``"chain_mock"`` (collector
            fell back to mock fixtures), or ``"metadata_hints_only"``
            (chain call failed entirely; we surface the hand-curated
            list as a last resort).
        """
        try:
            collector = self._get_chain_collector()
            subnets = collector.get_subnet_list()
            if not isinstance(subnets, list) or not subnets:
                # Empty / malformed chain response — fall back to hints.
                return [
                    dict(entry) for entry in self._SUBNET_METADATA_HINTS
                ], "metadata_hints_only"
            # Distinguish live vs mock by the collector's own mode flag.
            source = (
                "chain_mock" if getattr(collector, "use_mock_data", True)
                else "chain"
            )
            return list(subnets), source
        except Exception as exc:
            logger.warning(
                "SubnetDiscoveryAgent: chain collector unavailable (%s); "
                "falling back to hand-curated metadata hints",
                exc,
            )
            return [
                dict(entry) for entry in self._SUBNET_METADATA_HINTS
            ], "metadata_hints_only"

    def _merge_with_metadata(
        self, chain_subnets: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """
        Overlay hand-curated metadata onto the chain's subnet list.

        Chain provides the authoritative netuid + name + economic
        fields. Metadata hints provide purpose / category /
        repo_url / docs_url / hardware_min when we know them.

        Returns:
            (merged_list, metadata_only_list). The first is what to
            present as "discovered subnets". The second names entries
            we have curated metadata for that the chain isn't
            reporting today (stale catalog rows or netuids that have
            been deregistered).
        """
        chain_by_netuid = {
            int(s["netuid"]): s for s in chain_subnets
            if isinstance(s, dict) and "netuid" in s
        }
        merged: list[dict] = []
        for netuid, chain_entry in chain_by_netuid.items():
            base = dict(chain_entry)
            hint = self._metadata_by_netuid.get(netuid)
            if hint:
                # Metadata fills in fields the chain doesn't have, but
                # never overrides chain values (chain is authoritative
                # for name / owner / economic stats).
                for key, value in hint.items():
                    if key in ("netuid",):
                        continue
                    base.setdefault(key, value)
            base.setdefault("active", True)
            merged.append(base)
        # Surface metadata entries that the chain isn't reporting.
        metadata_only = [
            dict(hint)
            for netuid, hint in self._metadata_by_netuid.items()
            if netuid not in chain_by_netuid
        ]
        return merged, metadata_only

    def _filter_subnets(
        self,
        subnets: list[dict],
        filter_str: str = "",
        netuid_filter: int | None = None,
        include_inactive: bool = False,
    ) -> list[dict]:
        """
        Filter subnets based on criteria.

        Args:
            subnets: The merged chain+metadata list to filter.
            filter_str: Name or category filter
            netuid_filter: Specific NetUID
            include_inactive: Whether to include inactive subnets

        Returns:
            Filtered list of subnet dictionaries
        """
        result = list(subnets)

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
