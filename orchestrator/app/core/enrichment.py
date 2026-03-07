"""Context enrichment engine.

Gathers additional context for an alert before triage and Devin dispatch:
- Recent commits from GitHub API
- Error details from Sentry API
- Service ownership from config
"""

import logging
from typing import Optional

import httpx

from app.config import settings
from app.models.alert import AlertEvent, EnrichedContext

logger = logging.getLogger(__name__)


class EnrichmentEngine:
    """Pulls contextual data from GitHub, Sentry, and service config."""

    def __init__(
        self,
        github_token: Optional[str] = None,
        sentry_auth_token: Optional[str] = None,
        sentry_org_slug: Optional[str] = None,
    ):
        self._github_token = github_token or settings.github_token
        self._sentry_token = sentry_auth_token or settings.sentry_auth_token
        self._sentry_org = sentry_org_slug or settings.sentry_org_slug
        self._client = httpx.AsyncClient(timeout=15.0)

    async def enrich(self, alert: AlertEvent) -> EnrichedContext:
        """Gather all enrichment data for an alert.

        Runs GitHub and Sentry queries. Failures are logged but don't
        block the pipeline — partial context is better than no context.
        """
        context = EnrichedContext(
            repo_url=f"https://github.com/{settings.github_repo}",
            branch="main",
        )

        # Fetch recent commits
        try:
            context.recent_commits = await self._fetch_recent_commits(alert.service_name)
        except Exception as e:
            logger.warning(f"Failed to fetch recent commits: {e}")

        # Fetch Sentry error details
        try:
            sentry_details = await self._fetch_sentry_details(alert)
            if sentry_details:
                context.sentry_error_details = sentry_details
        except Exception as e:
            logger.warning(f"Failed to fetch Sentry details: {e}")

        # Resolve service ownership
        context.service_owner, context.service_team = self._resolve_ownership(alert.service_name)

        return context

    async def _fetch_recent_commits(
        self, service_name: str, hours: int = 48
    ) -> list[dict]:
        """Fetch recent commits from GitHub for the service's repo."""
        if not self._github_token:
            return []

        repo = settings.github_repo
        headers = {
            "Authorization": f"token {self._github_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        from datetime import datetime, timedelta

        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"

        response = await self._client.get(
            f"https://api.github.com/repos/{repo}/commits",
            headers=headers,
            params={"since": since, "per_page": 10},
        )

        if response.status_code != 200:
            logger.warning(f"GitHub API returned {response.status_code}: {response.text[:200]}")
            return []

        commits = response.json()
        return [
            {
                "sha": c["sha"][:7],
                "message": c["commit"]["message"].split("\n")[0],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"],
            }
            for c in commits
        ]

    async def _fetch_sentry_details(self, alert: AlertEvent) -> Optional[dict]:
        """Fetch error details from Sentry API."""
        if not self._sentry_token:
            return None

        project_slug = settings.sentry_project_slug or alert.service_name
        headers = {"Authorization": f"Bearer {self._sentry_token}"}

        # Search for the issue by error message
        response = await self._client.get(
            f"https://sentry.io/api/0/projects/{self._sentry_org}/{project_slug}/issues/",
            headers=headers,
            params={"query": alert.error_class, "limit": 1},
        )

        if response.status_code != 200:
            logger.warning(f"Sentry API returned {response.status_code}")
            return None

        issues = response.json()
        if not issues:
            return None

        issue = issues[0]
        return {
            "issue_id": issue.get("id"),
            "title": issue.get("title"),
            "first_seen": issue.get("firstSeen"),
            "last_seen": issue.get("lastSeen"),
            "count": issue.get("count"),
            "level": issue.get("level"),
            "status": issue.get("status"),
        }

    def _resolve_ownership(self, service_name: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve service ownership from config.

        In production, this would read from a service catalog (e.g., Backstage,
        OpsLevel, or a simple YAML config). For the demo, returns defaults.
        """
        # Demo service ownership mapping
        ownership_map: dict[str, tuple[str, str]] = {
            "payment-service": ("@oncall-payments", "payments-team"),
        }
        return ownership_map.get(service_name, (None, None))

    async def close(self) -> None:
        await self._client.aclose()
