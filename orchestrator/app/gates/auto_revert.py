"""Auto-revert watcher — monitors deployments after auto-merge.

After an auto-merged PR is deployed, monitors error rates. If errors
spike above threshold, automatically reverts the PR.

This is a Phase 3+ stub — architecturally supported but not active in v1.
The implementation exists so the interface is proven and the activation
is a config change, not a code change.
"""

import asyncio
import logging
from typing import Optional

from app.config.auto_merge import AutoMergeConfig

logger = logging.getLogger(__name__)


class AutoRevertWatcher:
    """Monitors post-deploy error rates and triggers revert if needed.

    Placeholder for when auto-merge is enabled (Phase 3+).
    Not active in v1 — gated behind AutoMergeConfig.enabled = False.
    """

    def __init__(self, config: AutoMergeConfig):
        self._config = config

    async def watch_deployment(
        self,
        service_name: str,
        pr_url: str,
        pr_merge_sha: str,
        sentry_client: Optional[object] = None,
        github_client: Optional[object] = None,
        slack_client: Optional[object] = None,
    ) -> dict:
        """Monitor a deployment and revert if error rate increases.

        Steps:
        1. Record baseline error rate (last 1 hour before merge)
        2. Wait for canary_health_check_duration_minutes
        3. Measure new error rate
        4. If increase > threshold, revert the PR
        5. Post to Slack about the revert

        Returns:
            dict with status ("healthy" or "reverted") and details.
        """
        if not self._config.auto_revert_on_error_rate_increase:
            return {"status": "monitoring_disabled", "service": service_name}

        logger.info(
            f"Watching deployment for {service_name} "
            f"(sha={pr_merge_sha[:7]}, "
            f"duration={self._config.canary_health_check_duration_minutes}min)"
        )

        # Step 1: Record baseline (stub — would query Sentry/monitoring API)
        baseline_error_rate = await self._get_baseline_error_rate(service_name, sentry_client)

        # Step 2: Wait for health check duration
        wait_seconds = self._config.canary_health_check_duration_minutes * 60
        logger.info(f"Waiting {wait_seconds}s for canary health check...")
        await asyncio.sleep(wait_seconds)

        # Step 3: Measure new error rate
        current_error_rate = await self._get_current_error_rate(service_name, sentry_client)

        # Step 4: Compare
        if baseline_error_rate > 0:
            increase_pct = ((current_error_rate - baseline_error_rate) / baseline_error_rate) * 100
        else:
            increase_pct = 0.0 if current_error_rate == 0 else 100.0

        if increase_pct > self._config.error_rate_increase_threshold_percent:
            logger.warning(
                f"Error rate increased by {increase_pct:.1f}% "
                f"(threshold: {self._config.error_rate_increase_threshold_percent}%). "
                f"Reverting {pr_url}."
            )
            await self._revert_pr(pr_url, pr_merge_sha, github_client)
            await self._notify_revert(service_name, pr_url, increase_pct, slack_client)
            return {
                "status": "reverted",
                "service": service_name,
                "error_rate_increase_pct": increase_pct,
                "pr_url": pr_url,
            }

        logger.info(
            f"Deployment healthy for {service_name}: "
            f"error rate change = {increase_pct:+.1f}%"
        )
        return {
            "status": "healthy",
            "service": service_name,
            "error_rate_increase_pct": increase_pct,
        }

    async def _get_baseline_error_rate(
        self, service_name: str, sentry_client: Optional[object]
    ) -> float:
        """Get the baseline error rate before deployment. Stub for v1."""
        # In production: query Sentry stats API for last 1 hour
        logger.debug(f"[STUB] Getting baseline error rate for {service_name}")
        return 0.0

    async def _get_current_error_rate(
        self, service_name: str, sentry_client: Optional[object]
    ) -> float:
        """Get current error rate after deployment. Stub for v1."""
        # In production: query Sentry stats API for current window
        logger.debug(f"[STUB] Getting current error rate for {service_name}")
        return 0.0

    async def _revert_pr(
        self, pr_url: str, merge_sha: str, github_client: Optional[object]
    ) -> None:
        """Revert a PR on GitHub. Stub for v1."""
        # In production: POST /repos/{owner}/{repo}/git/refs with revert commit
        logger.warning(f"[STUB] Would revert PR {pr_url} (sha={merge_sha[:7]})")

    async def _notify_revert(
        self,
        service_name: str,
        pr_url: str,
        increase_pct: float,
        slack_client: Optional[object],
    ) -> None:
        """Notify Slack about an auto-revert. Stub for v1."""
        message = (
            f"Auto-merged PR {pr_url} was automatically reverted. "
            f"Error rate for {service_name} increased by {increase_pct:.1f}% "
            f"after deployment."
        )
        logger.warning(f"[STUB] Would post to Slack: {message}")
