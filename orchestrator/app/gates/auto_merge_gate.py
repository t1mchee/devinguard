"""Auto-merge eligibility gate.

Evaluates whether a Devin-generated PR is eligible for auto-merge.
All conditions must pass. If any fails, the PR goes through normal human review.

Every decision (eligible or not) is logged with the full list of checks and
their results for audit transparency.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from app.config.auto_merge import AutoMergeConfig

if TYPE_CHECKING:
    from app.metrics.store import MetricsStore

logger = logging.getLogger(__name__)


class CheckResult(BaseModel):
    """Result of a single auto-merge check."""

    check_name: str
    passed: bool
    reason: str


class AutoMergeDecision(BaseModel):
    """Final auto-merge decision with full audit trail."""

    eligible: bool
    checks: list[CheckResult]
    reasons: list[str]


class AutoMergeGate:
    """Evaluates whether a Devin-generated PR is eligible for auto-merge.

    All conditions must pass. If any fails, the PR goes through normal
    human review. The gate is transparent — every decision is logged.
    """

    def __init__(self, config: AutoMergeConfig, metrics_store: Optional[MetricsStore] = None):
        self._config = config
        self._metrics = metrics_store

    async def evaluate(
        self,
        triage_confidence: float,
        files_changed: int,
        lines_changed: int,
        tests_passed: bool,
        service_name: str,
    ) -> AutoMergeDecision:
        """Evaluate all auto-merge conditions.

        Returns an AutoMergeDecision with the full list of checks for audit.
        """
        checks: list[CheckResult] = []

        # Check 1: Feature enabled
        checks.append(CheckResult(
            check_name="auto_merge_enabled",
            passed=self._config.enabled,
            reason="Auto-merge is enabled" if self._config.enabled else "Auto-merge is disabled",
        ))

        # Check 2: Triage confidence
        conf_ok = triage_confidence >= self._config.min_triage_confidence
        checks.append(CheckResult(
            check_name="triage_confidence",
            passed=conf_ok,
            reason=(
                f"Confidence {triage_confidence:.2f} >= {self._config.min_triage_confidence}"
                if conf_ok
                else f"Confidence {triage_confidence:.2f} < {self._config.min_triage_confidence}"
            ),
        ))

        # Check 3: PR scope — files
        files_ok = files_changed <= self._config.max_files_changed
        checks.append(CheckResult(
            check_name="files_changed",
            passed=files_ok,
            reason=(
                f"Files changed: {files_changed} <= {self._config.max_files_changed}"
                if files_ok
                else f"Files changed: {files_changed} > {self._config.max_files_changed}"
            ),
        ))

        # Check 4: PR scope — lines
        lines_ok = lines_changed <= self._config.max_lines_changed
        checks.append(CheckResult(
            check_name="lines_changed",
            passed=lines_ok,
            reason=(
                f"Lines changed: {lines_changed} <= {self._config.max_lines_changed}"
                if lines_ok
                else f"Lines changed: {lines_changed} > {self._config.max_lines_changed}"
            ),
        ))

        # Check 5: Tests passed
        checks.append(CheckResult(
            check_name="tests_passed",
            passed=tests_passed,
            reason="All tests passed" if tests_passed else "Tests failed or not run",
        ))

        # Check 6: Historical success rate
        historical_check = await self._check_historical_success_rate(service_name)
        checks.append(historical_check)

        # Determine eligibility
        eligible = all(c.passed for c in checks)
        reasons = [c.reason for c in checks]

        decision = AutoMergeDecision(eligible=eligible, checks=checks, reasons=reasons)

        # Log decision
        status = "ELIGIBLE" if eligible else "NOT ELIGIBLE"
        failed = [c.check_name for c in checks if not c.passed]
        logger.info(
            f"Auto-merge decision for {service_name}: {status}. "
            f"Failed checks: {failed if failed else 'none'}"
        )

        return decision

    async def _check_historical_success_rate(self, service_name: str) -> CheckResult:
        """Check if the service has sufficient historical success rate."""
        if not self._metrics:
            return CheckResult(
                check_name="historical_success_rate",
                passed=False,
                reason="No metrics store available — cannot verify historical success rate",
            )

        try:
            summary = await self._metrics.get_service_success_rate(service_name)
            total = summary.get("total_investigations", 0)
            success_rate = summary.get("success_rate", 0.0)

            if total < self._config.min_historical_investigations:
                return CheckResult(
                    check_name="historical_success_rate",
                    passed=False,
                    reason=(
                        f"Insufficient history: {total} investigations "
                        f"< {self._config.min_historical_investigations} required"
                    ),
                )

            rate_ok = success_rate >= self._config.min_historical_success_rate
            return CheckResult(
                check_name="historical_success_rate",
                passed=rate_ok,
                reason=(
                    f"Success rate: {success_rate:.1%} "
                    f"({'>=', '<'}[not rate_ok] {self._config.min_historical_success_rate:.1%}, "
                    f"based on {total} investigations)"
                ),
            )
        except Exception as e:
            return CheckResult(
                check_name="historical_success_rate",
                passed=False,
                reason=f"Failed to fetch historical data: {e}",
            )
