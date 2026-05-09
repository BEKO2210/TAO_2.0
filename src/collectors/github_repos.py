"""
GitHub Repository Collector

Collects metadata from GitHub repositories for Bittensor subnet analysis.
Uses the public GitHub API - no authentication required for basic operations.
"""

import json
import logging
import os
import re
import sqlite3
import time
from urllib.parse import urlparse

import requests

from src.collectors._base import BaseCollector

logger = logging.getLogger(__name__)

# Stable fixture for offline / use_mock_data=True. Plausible numbers for
# a healthy public Bittensor-adjacent repository.
_MOCK_REPO: dict = {
    "owner": "opentensor",
    "repo": "bittensor",
    "name": "opentensor/bittensor",
    "full_name": "opentensor/bittensor",
    "description": "Bittensor: a decentralized AI network",
    "stars": 1100,
    "forks": 320,
    "open_issues": 75,
    "default_branch": "main",
    "license": "MIT",
    "is_fork": False,
    "archived": False,
    "language": "Python",
    "updated_at": "2024-06-01T10:00:00Z",
    "created_at": "2021-01-01T00:00:00Z",
}

# Suspicious patterns for risk analysis
_SUSPICIOUS_PATTERNS = [
    (r"private_key|privatekey|privkey", "private_key_reference", "LOW"),
    (r"seed.phrase|mnemonic|seed_words", "seed_phrase_reference", "LOW"),
    (r"api[_-]?key|apikey", "api_key_reference", "LOW"),
    (r"password|passwd|pwd\s*[=:]", "hardcoded_password", "MEDIUM"),
    (r"eval\(|exec\(|subprocess\.call\(.*shell=True", "dangerous_code_execution", "HIGH"),
    (r"requests\.get\(.*verify\s*=\s*False", "ssl_verification_disabled", "MEDIUM"),
    (r"chmod\s+777|os\.chmod\(.*0o777", "permissive_file_permissions", "MEDIUM"),
    (r"\.send\(|\.transfer\(|\.call\{value", "raw_eth_transfer", "LOW"),
    (r"token|api[_-]?secret|access[_-]?token", "secret_reference", "LOW"),
]

# Risk weights
_RISK_WEIGHTS = {"LOW": 5, "MEDIUM": 15, "HIGH": 30, "CRITICAL": 50}


class GitHubRepoCollector(BaseCollector):
    """
    Collects and analyzes GitHub repository metadata.

    Public GitHub API is used — no auth needed for basic rate limits
    (60/hr). Optional GitHub token increases rate limit to 5000/hr.
    Honours the swarm-wide ``use_mock_data`` flag for offline/test runs.
    """

    SOURCE_NAME = "github_repos"

    def __init__(self, config: dict | None = None) -> None:
        """
        Initialize the GitHub repository collector.

        Args:
            config: Configuration dict with keys:
                - 'use_mock_data': bool — force fixture data (default True)
                - 'github_token': Optional personal access token
                - 'request_timeout': HTTP timeout in seconds (default 15)
                - 'cache_ttl': Cache TTL in seconds (default 3600)
                - 'db_path': SQLite cache path
        """
        config = config or {}
        config.setdefault("cache_ttl", 3600)
        config.setdefault("timeout", config.get("request_timeout", 15))
        super().__init__(config)
        self.config = config
        self.token = config.get("github_token", "")
        self.db_path = config.get("db_path", "data/github_cache.db")

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        logger.info(
            "GitHubRepoCollector initialized (use_mock_data=%s)",
            self.use_mock_data,
        )

    # ── Database ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Create cache tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repo_cache (
                    repo_key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)
            conn.commit()

    def _cache_get(self, repo_key: str) -> dict | None:
        """Get cached data if not expired."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT data, cached_at FROM repo_cache WHERE repo_key = ?", (repo_key,)
            ).fetchone()
        if row is None:
            return None
        data, cached_at = row
        if time.time() - cached_at > self.cache_ttl:
            return None
        return json.loads(data)

    def _cache_set(self, repo_key: str, data: dict) -> None:
        """Store data in cache."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO repo_cache (repo_key, data, cached_at) VALUES (?, ?, ?)",
                (repo_key, json.dumps(data, default=str), time.time()),
            )
            conn.commit()

    # ── API helpers ───────────────────────────────────────────────────────

    def _api_headers(self) -> dict:
        """Build request headers."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    def _api_request(self, url: str) -> dict:
        """Make a GET request to GitHub API."""
        try:
            resp = requests.get(url, headers=self._api_headers(), timeout=self.timeout)
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                reset_time = int(resp.headers.get("X-RateLimit-Reset", time.time() + 3600))
                wait = max(reset_time - int(time.time()), 60)
                logger.warning("GitHub rate limit hit, waiting %ds", wait)
                time.sleep(min(wait, 60))
                resp = requests.get(url, headers=self._api_headers(), timeout=self.timeout)
            if resp.status_code == 404:
                return {"error": "Not found", "status_code": 404}
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as exc:
            logger.error("GitHub API error for %s: %s", url, exc)
            return {"error": str(exc)}

    def _parse_repo(self, repo_url: str) -> tuple[str, str]:
        """Parse owner and repo from URL."""
        parsed = urlparse(repo_url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2:
            return ("", "")
        return parts[0], parts[1]

    # ── Public API ────────────────────────────────────────────────────────

    def get_repo_info(self, repo_url: str) -> dict:
        """
        Get repository information.

        Args:
            repo_url: Full GitHub repository URL.

        Returns:
            Dict with stars, forks, open issues, language, activity,
            etc., plus a ``_meta`` block tagging mock vs live.
        """
        cached = self._cache_get(f"info:{repo_url}")
        if cached:
            return cached

        owner, repo = self._parse_repo(repo_url)
        if not owner or not repo:
            return {"error": "Invalid GitHub URL", "url": repo_url}

        mode = self._resolve_mode()
        if mode == "mock":
            result = {
                **_MOCK_REPO,
                "repo_url": repo_url,
                "owner": owner,
                "repo_name": repo,
                "_meta": self._meta(mode),
            }
            self._cache_set(f"info:{repo_url}", result)
            return result

        data = self._api_request(f"https://api.github.com/repos/{owner}/{repo}")
        if "error" in data:
            return data

        result = {
            "repo_url": repo_url,
            "owner": owner,
            "repo_name": repo,
            "full_name": data.get("full_name", f"{owner}/{repo}"),
            "description": data.get("description", ""),
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "language": data.get("language", "unknown"),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "pushed_at": data.get("pushed_at", ""),
            "default_branch": data.get("default_branch", "main"),
            "size_kb": data.get("size", 0),
            "watchers": data.get("watchers_count", 0),
            "license": data.get("license", {}).get("name", "none") if data.get("license") else "none",
            "topics": data.get("topics", []),
            "archived": data.get("archived", False),
            "is_fork": data.get("fork", False),
            "has_wiki": data.get("has_wiki", False),
            "has_issues": data.get("has_issues", False),
            "has_discussions": data.get("has_discussions", False),
            "network_count": data.get("network_count", 0),
            "subscribers_count": data.get("subscribers_count", 0),
            "homepage": data.get("homepage", ""),
            "collected_at": int(time.time()),
        }
        self._cache_set(f"info:{repo_url}", result)
        logger.info("Fetched repo info for %s/%s (%d stars)", owner, repo, result["stars"])
        return result

    def get_readme(self, repo_url: str) -> str:
        """
        Get the README content of a repository.

        Args:
            repo_url: Full GitHub repository URL.

        Returns:
            README text content or empty string.
        """
        cached = self._cache_get(f"readme:{repo_url}")
        if cached:
            return cached.get("content", "")

        owner, repo = self._parse_repo(repo_url)
        if not owner or not repo:
            return ""

        # Try to fetch README via API
        readme_data = self._api_request(
            f"https://api.github.com/repos/{owner}/{repo}/readme"
        )
        if "error" in readme_data:
            # Try raw fallback
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md"
            try:
                resp = requests.get(raw_url, timeout=self.timeout)
                if resp.status_code == 404:
                    raw_url = raw_url.replace("/main/", "/master/")
                    resp = requests.get(raw_url, timeout=self.timeout)
                if resp.status_code == 200:
                    content = resp.text
                    self._cache_set(f"readme:{repo_url}", {"content": content})
                    return content
            except requests.exceptions.RequestException:
                pass
            return ""

        import base64
        content = base64.b64decode(readme_data.get("content", "")).decode("utf-8", errors="replace")
        self._cache_set(f"readme:{repo_url}", {"content": content})
        return content

    def get_recent_commits(self, repo_url: str, limit: int = 20) -> list:
        """
        Get recent commits from a repository.

        Args:
            repo_url: Full GitHub repository URL.
            limit: Maximum number of commits to return (max 100).

        Returns:
            List of commit dictionaries.
        """
        cached = self._cache_get(f"commits:{repo_url}:{limit}")
        if cached:
            return cached.get("commits", [])

        owner, repo = self._parse_repo(repo_url)
        if not owner or not repo:
            return []

        data = self._api_request(
            f"https://api.github.com/repos/{owner}/{repo}/commits?per_page={min(limit, 100)}"
        )
        if "error" in data:
            return []

        commits = []
        for item in data if isinstance(data, list) else []:
            commit_info = item.get("commit", {})
            author = commit_info.get("author", {})
            commits.append({
                "sha": item.get("sha", "")[:12],
                "full_sha": item.get("sha", ""),
                "message": commit_info.get("message", "").split("\n")[0],
                "author_name": author.get("name", ""),
                "author_email": author.get("email", ""),
                "date": author.get("date", ""),
                "url": item.get("html_url", ""),
            })

        self._cache_set(f"commits:{repo_url}:{limit}", {"commits": commits})
        return commits

    def get_contributors(self, repo_url: str) -> list:
        """
        Get contributors to a repository.

        Args:
            repo_url: Full GitHub repository URL.

        Returns:
            List of contributor dictionaries.
        """
        cached = self._cache_get(f"contributors:{repo_url}")
        if cached:
            return cached.get("contributors", [])

        owner, repo = self._parse_repo(repo_url)
        if not owner or not repo:
            return []

        data = self._api_request(
            f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=100"
        )
        if "error" in data:
            return []

        contributors = []
        for item in data if isinstance(data, list) else []:
            contributors.append({
                "login": item.get("login", ""),
                "contributions": item.get("contributions", 0),
                "avatar_url": item.get("avatar_url", ""),
                "profile_url": item.get("html_url", ""),
            })

        self._cache_set(f"contributors:{repo_url}", {"contributors": contributors})
        return contributors

    def check_repo_risk(self, repo_url: str) -> dict:
        """
        Analyze a repository for suspicious patterns.

        Args:
            repo_url: Full GitHub repository URL.

        Returns:
            Risk assessment dictionary with findings and overall risk score.
        """
        cached = self._cache_get(f"risk:{repo_url}")
        if cached:
            return cached

        owner, repo = self._parse_repo(repo_url)
        if not owner or not repo:
            return {"error": "Invalid URL", "url": repo_url}

        findings = []
        total_risk = 0

        # Check README for suspicious patterns
        readme = self.get_readme(repo_url)
        for pattern, name, severity in _SUSPICIOUS_PATTERNS:
            if re.search(pattern, readme, re.IGNORECASE):
                weight = _RISK_WEIGHTS.get(severity, 5)
                total_risk += weight
                findings.append({
                    "source": "README",
                    "pattern": name,
                    "severity": severity,
                    "risk_score": weight,
                })

        # Check repo metadata for risk indicators
        repo_info = self.get_repo_info(repo_url)
        if "error" not in repo_info:
            # Very new repo
            created = repo_info.get("created_at", "")
            if created:
                try:
                    from datetime import datetime, timezone
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    age_days = (datetime.now(timezone.utc) - created_dt).days
                    if age_days < 7:
                        total_risk += 10
                        findings.append({
                            "source": "metadata",
                            "pattern": "very_new_repository",
                            "severity": "MEDIUM",
                            "risk_score": 10,
                            "detail": f"Repo is only {age_days} days old",
                        })
                    elif age_days < 30:
                        total_risk += 5
                        findings.append({
                            "source": "metadata",
                            "pattern": "new_repository",
                            "severity": "LOW",
                            "risk_score": 5,
                            "detail": f"Repo is {age_days} days old",
                        })
                except Exception:
                    pass

            # Low activity
            if repo_info.get("stars", 0) < 5 and repo_info.get("forks", 0) < 2:
                total_risk += 5
                findings.append({
                    "source": "metadata",
                    "pattern": "low_community_activity",
                    "severity": "LOW",
                    "risk_score": 5,
                })

            # Archived
            if repo_info.get("archived", False):
                total_risk += 15
                findings.append({
                    "source": "metadata",
                    "pattern": "archived_repository",
                    "severity": "MEDIUM",
                    "risk_score": 15,
                })

            # No license
            if repo_info.get("license", "none") == "none":
                total_risk += 5
                findings.append({
                    "source": "metadata",
                    "pattern": "no_license",
                    "severity": "LOW",
                    "risk_score": 5,
                })

        # Contributor concentration risk
        contributors = self.get_contributors(repo_url)
        if contributors:
            total_contributions = sum(c.get("contributions", 0) for c in contributors)
            if total_contributions > 0 and contributors:
                top_share = contributors[0].get("contributions", 0) / total_contributions
                if top_share > 0.9:
                    total_risk += 15
                    findings.append({
                        "source": "contributors",
                        "pattern": "single_contributor_dominance",
                        "severity": "MEDIUM",
                        "risk_score": 15,
                        "detail": f"Top contributor has {top_share*100:.0f}% of commits",
                    })
                elif top_share > 0.7:
                    total_risk += 8
                    findings.append({
                        "source": "contributors",
                        "pattern": "high_contributor_concentration",
                        "severity": "LOW",
                        "risk_score": 8,
                        "detail": f"Top contributor has {top_share*100:.0f}% of commits",
                    })

        # Cap at 100
        total_risk = min(total_risk, 100)

        result = {
            "repo_url": repo_url,
            "risk_score": total_risk,
            "risk_level": self._risk_level(total_risk),
            "findings": findings,
            "num_findings": len(findings),
            "checked_at": int(time.time()),
        }
        self._cache_set(f"risk:{repo_url}", result)
        return result

    @staticmethod
    def _risk_level(score: int) -> str:
        """Convert numeric risk score to level."""
        if score < 10:
            return "LOW"
        elif score < 25:
            return "MEDIUM"
        elif score < 50:
            return "HIGH"
        return "CRITICAL"

    def search_bittensor_repos(self, query: str = "bittensor") -> list:
        """
        Search for Bittensor-related repositories on GitHub.

        Args:
            query: Search query string.

        Returns:
            List of repository result dictionaries.
        """
        cached = self._cache_get(f"search:{query}")
        if cached:
            return cached.get("results", [])

        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": "30",
        }
        try:
            resp = requests.get(
                "https://api.github.com/search/repositories",
                headers=self._api_headers(),
                params=params,
                timeout=self.timeout,
            )
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                time.sleep(60)
                resp = requests.get(
                    "https://api.github.com/search/repositories",
                    headers=self._api_headers(),
                    params=params,
                    timeout=self.timeout,
                )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            logger.error("GitHub search error: %s", exc)
            return []

        results = []
        for item in data.get("items", []):
            results.append({
                "repo_url": item.get("html_url", ""),
                "full_name": item.get("full_name", ""),
                "description": item.get("description", ""),
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "language": item.get("language", "unknown"),
                "updated_at": item.get("updated_at", ""),
                "license": item.get("license", {}).get("name", "none") if item.get("license") else "none",
            })

        self._cache_set(f"search:{query}", {"results": results})
        logger.info("GitHub search for '%s' returned %d results", query, len(results))
        return results
