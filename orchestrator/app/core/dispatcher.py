"""Investigation dispatcher — the core orchestration pipeline.

Coordinates the full flow from alert to investigation:
1. Normalize the incoming webhook
2. Deduplicate
3. Enrich with context
4. Triage (rule-based + LLM)
5. Dispatch to Devin (if code-level)
6. Monitor session with loop detection
7. Route output (Slack, PR, escalation)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from app.config import settings

if TYPE_CHECKING:
    import anthropic
from app.core.devin_client import DevinAPIClient
from app.core.enrichment import EnrichmentEngine
from app.core.prompt_builder import build_investigation_prompt
from app.core.triage import TriageResult, classify_alert
from app.dedup.fingerprint import generate_dedup_key
from app.dedup.store import BaseDedupStore, InMemoryDedupStore
from app.metrics.store import MetricsStore
from app.models.alert import AlertEvent, EnrichedContext, Investigation
from app.models.devin import CreateSessionRequest
from app.session.loop_actions import redirect_session, terminate_session
from app.session.loop_detection import LoopDetector, LoopSignal, extract_snapshot
from app.session.polling_monitor import PollingSessionMonitor

logger = logging.getLogger(__name__)


class InvestigationDispatcher:
    """Orchestrates the full alert-to-resolution pipeline."""

    def __init__(
        self,
        dedup_store: Optional[BaseDedupStore] = None,
        devin_client: Optional[DevinAPIClient] = None,
        enrichment_engine: Optional[EnrichmentEngine] = None,
        metrics_store: Optional[MetricsStore] = None,
        anthropic_client: Optional[anthropic.AsyncAnthropic] = None,
    ):
        self._dedup = dedup_store or InMemoryDedupStore(
            default_ttl_seconds=settings.dedup_window_seconds
        )
        self._devin = devin_client or DevinAPIClient()
        self._enrichment = enrichment_engine or EnrichmentEngine()
        self._metrics = metrics_store
        self._anthropic = anthropic_client

        # Active investigations
        self._investigations: dict[str, Investigation] = {}
        self._loop_detectors: dict[str, LoopDetector] = {}

    async def handle_alert(self, alert: AlertEvent) -> dict:
        """Process an incoming alert through the full pipeline.

        Returns a dict with the investigation status and any actions taken.
        """
        # Step 1: Generate dedup key
        dedup_key = generate_dedup_key(alert)
        logger.info(f"Alert received: {alert.service_name}/{alert.error_class} → dedup={dedup_key}")

        # Step 2: Check dedup
        is_duplicate, existing_inv_id = await self._dedup.check_and_set(dedup_key)
        if is_duplicate and existing_inv_id:
            logger.info(f"Alert deduplicated — attaching to investigation {existing_inv_id}")
            investigation = self._investigations.get(existing_inv_id)
            if investigation:
                investigation.alert_count += 1
            await self._dedup.extend_ttl(dedup_key)
            return {
                "action": "deduplicated",
                "investigation_id": existing_inv_id,
                "alert_count": investigation.alert_count if investigation else 0,
            }

        # Step 3: Create new investigation
        investigation_id = f"inv_{uuid.uuid4().hex[:12]}"
        investigation = Investigation(
            investigation_id=investigation_id,
            service_name=alert.service_name,
            dedup_key=dedup_key,
        )
        self._investigations[investigation_id] = investigation
        await self._dedup.register_investigation(dedup_key, investigation_id)

        # Step 4: Enrich context
        context = await self._enrichment.enrich(alert)

        # Step 5: Triage
        triage_result = await classify_alert(alert, context, self._anthropic)
        investigation.triage_classification = triage_result.classification
        investigation.triage_confidence = triage_result.confidence

        logger.info(
            f"Triage: {triage_result.classification} "
            f"(confidence={triage_result.confidence:.2f}, "
            f"dispatch={triage_result.should_dispatch_to_devin})"
        )

        # Record metrics
        if self._metrics:
            await self._metrics.record_investigation(investigation)

        # Step 6: Dispatch or escalate
        if triage_result.should_dispatch_to_devin:
            return await self._dispatch_to_devin(alert, context, investigation, triage_result)

        # Route to human
        return {
            "action": "escalated_to_human",
            "investigation_id": investigation_id,
            "triage": triage_result.model_dump(),
            "enriched_context": context.model_dump(),
        }

    async def _dispatch_to_devin(
        self,
        alert: AlertEvent,
        context: EnrichedContext,
        investigation: Investigation,
        triage_result: TriageResult,
    ) -> dict:
        """Create a Devin session for the investigation."""
        # Build prompt
        prompt = build_investigation_prompt(alert, context, investigation.investigation_id)

        # Create session
        request = CreateSessionRequest(
            prompt=prompt,
            repos=[settings.github_repo] if settings.github_repo else None,
            max_acu_limit=10,
            tags=["devinguard", f"inv:{investigation.investigation_id}"],
            title=f"[DevinGuard] Investigate {alert.error_class} in {alert.service_name}",
        )

        try:
            session_data = await self._devin.create_session(request)
            investigation.session_id = session_data["session_id"]
            investigation.session_status = session_data.get("status", "new")

            logger.info(
                f"Devin session created: {session_data['session_id']} — {session_data.get('url')}"
            )

            return {
                "action": "dispatched_to_devin",
                "investigation_id": investigation.investigation_id,
                "session_id": session_data["session_id"],
                "session_url": session_data.get("url"),
                "triage": triage_result.model_dump(),
            }

        except Exception as e:
            logger.error(f"Failed to create Devin session: {e}")
            return {
                "action": "dispatch_failed",
                "investigation_id": investigation.investigation_id,
                "error": str(e),
                "triage": triage_result.model_dump(),
            }

    async def monitor_session(self, investigation_id: str) -> None:
        """Start monitoring a Devin session with loop detection.

        This is called as a background task after dispatch.
        """
        investigation = self._investigations.get(investigation_id)
        if not investigation or not investigation.session_id:
            return

        session_id = investigation.session_id
        loop_detector = LoopDetector()
        self._loop_detectors[session_id] = loop_detector

        monitor = PollingSessionMonitor(
            self._devin,
            poll_interval_seconds=settings.poll_interval_seconds,
        )

        previous_snapshot = None

        async def on_complete(response: dict) -> None:
            investigation.session_status = "exit"
            investigation.resolved_at = datetime.utcnow()
            investigation.acus_consumed = response.get("acus_consumed", 0)

            prs = response.get("pull_requests", [])
            if prs:
                investigation.session_outcome = "fix_pr"
                investigation.pr_url = prs[0].get("pr_url")
            else:
                investigation.session_outcome = "hypothesis"

            logger.info(
                f"Investigation {investigation_id} complete: "
                f"outcome={investigation.session_outcome}, "
                f"ACUs={investigation.acus_consumed}"
            )

            if self._metrics:
                await self._metrics.update_investigation_outcome(
                    investigation_id,
                    session_outcome=investigation.session_outcome,
                    acus_consumed=investigation.acus_consumed,
                    pr_url=investigation.pr_url,
                    resolved_at=investigation.resolved_at,
                )

        async def on_error(response: dict) -> None:
            investigation.session_status = "error"
            investigation.session_outcome = "inconclusive"
            investigation.resolved_at = datetime.utcnow()
            investigation.acus_consumed = response.get("acus_consumed", 0)

            logger.warning(
                f"Investigation {investigation_id} errored: {response.get('reason', 'unknown')}"
            )

            if self._metrics:
                await self._metrics.update_investigation_outcome(
                    investigation_id,
                    session_outcome="inconclusive",
                    acus_consumed=investigation.acus_consumed,
                    resolved_at=investigation.resolved_at,
                )

        async def on_progress(response: dict) -> None:
            nonlocal previous_snapshot
            snapshot = extract_snapshot(response, previous_snapshot)
            signal = loop_detector.analyze(snapshot)
            previous_snapshot = snapshot

            if signal == LoopSignal.REDIRECT:
                reason = loop_detector.get_last_trigger_reason()
                await redirect_session(self._devin, session_id, reason)

            elif signal == LoopSignal.TERMINATE:
                reason = loop_detector.get_last_trigger_reason()
                final_state = await terminate_session(self._devin, session_id, reason)
                await on_error({
                    "reason": "loop_terminated",
                    "final_state": final_state,
                    "acus_consumed": final_state.get("acus_consumed", 0),
                })

        await monitor.watch(session_id, on_complete, on_error, on_progress)

    def get_investigation(self, investigation_id: str) -> Optional[Investigation]:
        return self._investigations.get(investigation_id)

    def list_investigations(self) -> list[Investigation]:
        return list(self._investigations.values())
