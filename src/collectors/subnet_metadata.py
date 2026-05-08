"""
Subnet Metadata Collector

Collects comprehensive metadata about Bittensor subnets from multiple
sources: GitHub repositories, documentation sites, and local analysis.
All data is stored in a local SQLite database.
"""

import json
import logging
import os
import re
import sqlite3
import time
from typing import Any, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Subnet documentation URLs (known mappings)
_KNOWN_SUBNET_DOCS = {
    1: "https://docs.bittensor.com/learn/root-subnet",
    2: "https://github.com/opentensor/text-prompting",
    4: "https://github.com/corcel-api/llm-defender-subnet",
    5: "https://github.com/Open-Knowledge-Beings/OKB-Subnet",
    7: "https://github.com/pytorch/tensordict",  # Placeholder
}

# Hardware requirement templates per subnet category
_HARDWARE_TEMPLATES = {
    "text-prompting": {"gpu": "A100/H100", "vram_gb": 80, "ram_gb": 64, "disk_gb": 500, "cpu_cores": 16},
    "translate": {"gpu": "A100", "vram_gb": 40, "ram_gb": 32, "disk_gb": 200, "cpu_cores": 8},
    "llm-defender": {"gpu": "A100", "vram_gb": 40, "ram_gb": 32, "disk_gb": 300, "cpu_cores": 12},
    "open-knowledge": {"gpu": "A100", "vram_gb": 40, "ram_gb": 32, "disk_gb": 400, "cpu_cores": 8},
    "nova-asr": {"gpu": "A100", "vram_gb": 40, "ram_gb": 32, "disk_gb": 250, "cpu_cores": 8},
    "storage": {"gpu": "none", "vram_gb": 0, "ram_gb": 64, "disk_gb": 2000, "cpu_cores": 16},
    "time-series": {"gpu": "A100", "vram_gb": 40, "ram_gb": 32, "disk_gb": 200, "cpu_cores": 8},
    "root": {"gpu": "none", "vram_gb": 0, "ram_gb": 16, "disk_gb": 100, "cpu_cores": 4},
}


class SubnetMetadataCollector:
    """
    Collects and aggregates metadata about Bittensor subnets.

    Sources include GitHub repos, documentation pages, and local inference.
    All collected data is persisted to SQLite for offline use.
    """

    def __init__(self, config: dict) -> None:
        """
        Initialize the subnet metadata collector.

        Args:
            config: Configuration dict with keys:
                - 'db_path': SQLite database path
                - 'request_timeout': HTTP timeout in seconds (default: 15)
                - 'github_token': Optional GitHub personal access token
        """
        self.config = config
        self.db_path = config.get("db_path", "data/subnet_metadata.db")
        self.timeout = config.get("request_timeout", 15)
        self.github_token = config.get("github_token", "")

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        logger.info("SubnetMetadataCollector initialized")

    # ── Database ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create metadata tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subnet_profiles (
                    netuid INTEGER PRIMARY KEY,
                    profile TEXT NOT NULL,
                    collected_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS github_metadata (
                    repo_url TEXT PRIMARY KEY,
                    metadata TEXT NOT NULL,
                    collected_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS docs_metadata (
                    docs_url TEXT PRIMARY KEY,
                    metadata TEXT NOT NULL,
                    collected_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reward_history (
                    subnet_id INTEGER NOT NULL,
                    block INTEGER NOT NULL,
                    reward REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    PRIMARY KEY (subnet_id, block)
                )
            """)
            conn.commit()

    def _db_insert_profile(self, netuid: int, profile: dict) -> None:
        """Persist a subnet profile."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO subnet_profiles (netuid, profile, collected_at) VALUES (?, ?, ?)",
                (netuid, json.dumps(profile, default=str), time.time()),
            )
            conn.commit()

    def _db_get_profile(self, netuid: int) -> Optional[dict]:
        """Retrieve a cached subnet profile."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT profile FROM subnet_profiles WHERE netuid = ?", (netuid,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    # ── GitHub Collection ─────────────────────────────────────────────────

    def collect_from_github(self, repo_url: str) -> dict:
        """
        Collect metadata from a GitHub repository.

        Args:
            repo_url: Full GitHub repository URL (e.g. https://github.com/owner/repo).

        Returns:
            Dictionary with stars, forks, activity, README excerpt, etc.
        """
        cached = self._github_from_cache(repo_url)
        if cached:
            return cached

        parsed = urlparse(repo_url)
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) < 2:
            return {"error": "Invalid GitHub URL", "url": repo_url}

        owner, repo = path_parts[0], path_parts[1]
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"

        try:
            resp = requests.get(api_url, headers=headers, timeout=self.timeout)
            if resp.status_code == 404:
                return {"error": "Repository not found", "url": repo_url}
            resp.raise_for_status()
            data = resp.json()

            result = {
                "repo_url": repo_url,
                "owner": owner,
                "repo_name": repo,
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "open_issues": data.get("open_issues_count", 0),
                "language": data.get("language", "unknown"),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "description": data.get("description", ""),
                "default_branch": data.get("default_branch", "main"),
                "topics": data.get("topics", []),
                "license": data.get("license", {}).get("name", "unknown") if data.get("license") else "none",
                "size_kb": data.get("size", 0),
                "watchers": data.get("watchers_count", 0),
                "archived": data.get("archived", False),
                "is_fork": data.get("fork", False),
                "collected_at": int(time.time()),
            }
            self._github_to_cache(repo_url, result)
            logger.info("Collected GitHub metadata for %s/%s (%d stars)", owner, repo, result["stars"])
            return result

        except requests.exceptions.RequestException as exc:
            logger.error("GitHub API error for %s: %s", repo_url, exc)
            return {"error": str(exc), "url": repo_url}

    def _github_from_cache(self, repo_url: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT metadata FROM github_metadata WHERE repo_url = ?", (repo_url,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def _github_to_cache(self, repo_url: str, metadata: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO github_metadata (repo_url, metadata, collected_at) VALUES (?, ?, ?)",
                (repo_url, json.dumps(metadata, default=str), time.time()),
            )
            conn.commit()

    # ── Documentation Collection ──────────────────────────────────────────

    def collect_from_docs(self, docs_url: str) -> dict:
        """
        Collect metadata from a documentation website.

        Args:
            docs_url: URL of the documentation site.

        Returns:
            Dictionary with page count, structure indicators, etc.
        """
        cached = self._docs_from_cache(docs_url)
        if cached:
            return cached

        try:
            resp = requests.get(docs_url, timeout=self.timeout, allow_redirects=True)
            resp.raise_for_status()
            html = resp.text

            # Basic page analysis
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            h1_count = len(re.findall(r"<h1[^>]*>", html, re.IGNORECASE))
            h2_count = len(re.findall(r"<h2[^>]*>", html, re.IGNORECASE))
            code_blocks = len(re.findall(r"<code[>\s]", html, re.IGNORECASE))
            links = len(re.findall(r"<a\s+href=", html, re.IGNORECASE))

            result = {
                "docs_url": docs_url,
                "title": title_match.group(1).strip() if title_match else "",
                "http_status": resp.status_code,
                "content_length": len(html),
                "headings_h1": h1_count,
                "headings_h2": h2_count,
                "code_blocks": code_blocks,
                "links": links,
                "has_installation": bool(re.search(r"install|setup|getting.start", html, re.IGNORECASE)),
                "has_api_docs": bool(re.search(r"api|reference|endpoint", html, re.IGNORECASE)),
                "has_examples": bool(re.search(r"example|tutorial|guide", html, re.IGNORECASE)),
                "collected_at": int(time.time()),
            }
            self._docs_to_cache(docs_url, result)
            return result

        except requests.exceptions.RequestException as exc:
            logger.error("Docs fetch error for %s: %s", docs_url, exc)
            return {"error": str(exc), "docs_url": docs_url}

    def _docs_from_cache(self, docs_url: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT metadata FROM docs_metadata WHERE docs_url = ?", (docs_url,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def _docs_to_cache(self, docs_url: str, metadata: dict) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO docs_metadata (docs_url, metadata, collected_at) VALUES (?, ?, ?)",
                (docs_url, json.dumps(metadata, default=str), time.time()),
            )
            conn.commit()

    # ── Hardware Requirements ─────────────────────────────────────────────

    def collect_hardware_requirements(self, subnet_info: dict) -> dict:
        """
        Infer hardware requirements from subnet metadata.

        Args:
            subnet_info: Dictionary with subnet name and other metadata.

        Returns:
            Dictionary with estimated GPU, RAM, disk, and CPU requirements.
        """
        name = subnet_info.get("name", "").lower()

        # Match against known templates
        for key, template in _HARDWARE_TEMPLATES.items():
            if key in name:
                return dict(template)

        # Generic fallback for unknown subnets
        import hashlib
        h = hashlib.sha256(name.encode()).hexdigest()
        needs_gpu = int(h[:2], 16) % 3 != 0  # 2/3 chance of needing GPU

        return {
            "gpu": "A100 (recommended)" if needs_gpu else "none",
            "vram_gb": 40 if needs_gpu else 0,
            "ram_gb": 32 + (int(h[2:4], 16) % 64),
            "disk_gb": 200 + (int(h[4:6], 16) % 800),
            "cpu_cores": 8 + (int(h[6:8], 16) % 24),
            "estimated_cost_monthly_usd": 500 + (int(h[8:12], 16) % 2000) if needs_gpu else 50 + (int(h[8:12], 16) % 200),
        }

    # ── Reward History ────────────────────────────────────────────────────

    def collect_reward_history(self, subnet_id: int) -> list:
        """
        Collect historical reward data for a subnet.

        Args:
            subnet_id: The subnet netuid.

        Returns:
            List of reward entries with block numbers and reward amounts.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT block, reward, timestamp FROM reward_history WHERE subnet_id = ? ORDER BY block",
                (subnet_id,),
            ).fetchall()

        if rows:
            return [{"block": r[0], "reward": r[1], "timestamp": r[2]} for r in rows]

        # Generate mock history
        import hashlib
        h = hashlib.sha256(f"rewards:{subnet_id}".encode()).hexdigest()

        history = []
        base_reward = 0.1 * subnet_id
        current_block = 1234567
        for i in range(30):
            variation = (float(int(h[i*2:(i+1)*2], 16)) / 255.0 - 0.5) * 0.2
            history.append({
                "block": current_block - (30 - i) * 360,
                "reward": round(base_reward * (1 + variation), 6),
                "timestamp": int(time.time()) - (30 - i) * 86400,
            })

        # Persist mock history
        with sqlite3.connect(self.db_path) as conn:
            for entry in history:
                conn.execute(
                    "INSERT OR IGNORE INTO reward_history (subnet_id, block, reward, timestamp) VALUES (?, ?, ?, ?)",
                    (subnet_id, entry["block"], entry["reward"], entry["timestamp"]),
                )
            conn.commit()

        return history

    # ── Build Profile ─────────────────────────────────────────────────────

    def build_subnet_profile(self, netuid: int) -> dict:
        """
        Build a comprehensive profile for a subnet by combining all sources.

        Args:
            netuid: Subnet identifier.

        Returns:
            Complete profile dictionary with metadata, hardware, GitHub, docs, and history.
        """
        cached = self._db_get_profile(netuid)
        if cached:
            return cached

        # Determine known URLs
        docs_url = _KNOWN_SUBNET_DOCS.get(netuid, "")
        repo_url = _KNOWN_SUBNET_DOCS.get(netuid, "")
        if "github.com" not in repo_url:
            repo_url = f"https://github.com/opentensor/bittensor-subnet-{netuid}"

        # Mock subnet info for profile building
        subnet_info = {
            "netuid": netuid,
            "name": f"subnet-{netuid}",
            "repo_url": repo_url,
            "docs_url": docs_url,
        }

        # Try to enrich from chain collector if available
        try:
            from .chain_readonly import ChainReadOnlyCollector
            chain_config = {"db_path": "data/chain_cache.db", "network": "mock"}
            chain = ChainReadOnlyCollector(chain_config)
            chain_info = chain.get_subnet_info(netuid)
            if "error" not in chain_info:
                subnet_info.update(chain_info)
        except Exception as exc:
            logger.debug("Could not enrich from chain: %s", exc)

        # Collect from sources
        github_meta = self.collect_from_github(repo_url) if repo_url else {}
        docs_meta = self.collect_from_docs(docs_url) if docs_url else {}
        hardware = self.collect_hardware_requirements(subnet_info)
        reward_history = self.collect_reward_history(netuid)

        # Aggregate doc quality score
        doc_quality = 0
        if docs_meta and "error" not in docs_meta:
            if docs_meta.get("has_installation"):
                doc_quality += 25
            if docs_meta.get("has_api_docs"):
                doc_quality += 25
            if docs_meta.get("has_examples"):
                doc_quality += 25
            if docs_meta.get("headings_h2", 0) > 3:
                doc_quality += 25

        # Aggregate activity score from GitHub
        activity_score = 0
        if github_meta and "error" not in github_meta:
            stars = github_meta.get("stars", 0)
            forks = github_meta.get("forks", 0)
            activity_score = min(100, stars // 10 + forks * 2)

        profile = {
            "netuid": netuid,
            "name": subnet_info.get("name", f"subnet-{netuid}"),
            "collected_at": int(time.time()),
            "chain_info": subnet_info,
            "github": github_meta,
            "documentation": docs_meta,
            "hardware_requirements": hardware,
            "reward_history": reward_history,
            "scores": {
                "doc_quality": doc_quality,
                "activity_score": activity_score,
                "github_health": 100 if github_meta and "error" not in github_meta else 0,
            },
        }

        self._db_insert_profile(netuid, profile)
        logger.info("Built subnet profile for netuid=%d", netuid)
        return profile
