"""DevinGuard Demo Workflow — End-to-end pipeline simulation.

This script demonstrates the full DevinGuard pipeline without
requiring real API keys. It simulates:

1. Alert ingestion (PagerDuty webhook)
2. Deduplication (same alert twice → second is deduplicated)
3. Triage (rule-based classification)
4. Context enrichment (mocked GitHub/Sentry data)
5. Devin session dispatch (mocked API call)
6. Loop detection (simulated session snapshots)
7. Output routing (investigation outcomes)
8. Dashboard metrics (SQLite aggregation)

Usage:
    cd orchestrator
    poetry run python scripts/demo_workflow.py
"""

import asyncio
import logging
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.triage import classify_alert
from app.dedup.fingerprint import generate_dedup_key
from app.dedup.store import InMemoryDedupStore
from app.metrics.store import MetricsStore
from app.models.alert import AlertEvent, EnrichedContext, Investigation
from app.session.loop_detection import (
    LoopDetector,
    SessionSnapshot,
)
from app.webhooks.normalizers import normalize_pagerduty

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("demo")


def banner(text: str) -> None:
    """Print a section banner."""
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}\n")


async def demo_alert_ingestion() -> AlertEvent:
    """Step 1: Simulate a PagerDuty webhook payload."""
    banner("STEP 1: Alert Ingestion")

    payload = {
        "event": {
            "id": "P1234567",
            "event_type": "incident.triggered",
            "resource_type": "incident",
            "occurred_at": datetime.utcnow().isoformat(),
            "agent": {"type": "service_reference", "id": "PSERVICE1"},
            "data": {
                "id": "INC001",
                "type": "incident",
                "self": "https://api.pagerduty.com/incidents/INC001",
                "html_url": "https://app.pagerduty.com/incidents/INC001",
                "title": (
                    "TypeError: Cannot read properties of null "
                    "(reading 'paymentMethodId')"
                ),
                "status": "triggered",
                "urgency": "high",
                "service": {
                    "id": "PSVC001",
                    "name": "payment-service",
                },
                "body": {
                    "details": {
                        "error_class": "TypeError",
                        "error_message": (
                            "Cannot read properties of null "
                            "(reading 'paymentMethodId')"
                        ),
                        "stack_trace": (
                            "    at createCharge "
                            "(src/services/payment-service.ts:98:47)\n"
                            "    at handleCreateCharge "
                            "(src/handlers/charge-handler.ts:25:28)\n"
                            "    at Layer.handle "
                            "(node_modules/express/lib/router/layer.js:95:5)"
                        ),
                    },
                },
            },
        },
    }

    print("Received PagerDuty webhook payload:")
    print(f"  Incident: {payload['event']['data']['title'][:60]}...")
    print(f"  Service:  {payload['event']['data']['service']['name']}")
    print(f"  Urgency:  {payload['event']['data']['urgency']}")

    alert = normalize_pagerduty(payload)
    print("\nNormalized to AlertEvent:")
    print(f"  service_name:  {alert.service_name}")
    print(f"  error_class:   {alert.error_class}")
    print(f"  severity:      {alert.severity}")
    print(f"  source:        {alert.source}")

    return alert


async def demo_deduplication(alert: AlertEvent) -> str:
    """Step 2: Demonstrate deduplication."""
    banner("STEP 2: Deduplication")

    store = InMemoryDedupStore(default_ttl_seconds=300)
    dedup_key = generate_dedup_key(alert)
    print(f"Dedup key: {dedup_key}")

    # First alert — should create new investigation
    is_dup, existing = await store.check_and_set(dedup_key)
    print(f"\nFirst alert:  is_duplicate={is_dup} (expected: False)")

    # Register investigation
    await store.register_investigation(dedup_key, "inv_demo_001")

    # Second identical alert — should be deduplicated
    is_dup, existing = await store.check_and_set(dedup_key)
    print(f"Second alert: is_duplicate={is_dup}, "
          f"existing_investigation={existing}")
    print("  -> Attached to existing investigation (no new Devin session)")

    return dedup_key


async def demo_triage(alert: AlertEvent) -> None:
    """Step 3: Demonstrate triage classification."""
    banner("STEP 3: Triage (Rule-Based)")

    result = await classify_alert(alert, context=None, openai_client=None)
    print(f"Classification: {result.classification}")
    print(f"Confidence:     {result.confidence:.2f}")
    print(f"Dispatch:       {result.should_dispatch_to_devin}")
    print(f"Reasoning:      {result.reasoning}")

    # Also demo an infra-level alert
    print("\n--- Comparing with an infrastructure alert ---")
    infra_alert = AlertEvent(
        source="pagerduty",
        source_event_id="PD002",
        service_name="payment-service",
        error_class="OutOfMemoryError",
        error_message="Container killed: OOM (used 4.2GB / 4GB limit)",
        severity="P1",
        timestamp=datetime.utcnow(),
    )
    infra_result = await classify_alert(
        infra_alert, context=None, openai_client=None
    )
    print(f"Classification: {infra_result.classification}")
    print(f"Confidence:     {infra_result.confidence:.2f}")
    print(f"Dispatch:       {infra_result.should_dispatch_to_devin}")
    print(f"Reasoning:      {infra_result.reasoning}")


async def demo_enrichment() -> EnrichedContext:
    """Step 4: Simulate context enrichment."""
    banner("STEP 4: Context Enrichment (Simulated)")

    context = EnrichedContext(
        repo_url="https://github.com/acme/payment-service",
        branch="main",
        recent_commits=[
            {
                "sha": "a1b2c3d",
                "message": "perf: reduce customer cache TTL for fresher data",
                "author": "dev-intern",
                "date": (datetime.utcnow() - timedelta(hours=6)).isoformat(),
            },
            {
                "sha": "e4f5g6h",
                "message": "feat: add retry logic to Stripe charge flow",
                "author": "senior-dev",
                "date": (datetime.utcnow() - timedelta(days=3)).isoformat(),
            },
        ],
        sentry_error_details={
            "title": "TypeError: Cannot read properties of null",
            "first_seen": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
            "last_seen": datetime.utcnow().isoformat(),
            "count": 47,
            "level": "error",
        },
        service_owner="@oncall-payments",
        service_team="#payments-eng",
    )

    print("Enriched context assembled:")
    print(f"  Repo:    {context.repo_url}")
    print(f"  Branch:  {context.branch}")
    print(f"  Commits: {len(context.recent_commits)} recent")
    for c in context.recent_commits:
        print(f"    - {c['sha']} \"{c['message']}\" (@{c['author']})")
    sd = context.sentry_error_details or {}
    print(f"  Sentry:  {sd.get('count', 0)} occurrences")
    print(f"  Owner:   {context.service_owner}")
    print(f"  Team:    {context.service_team}")

    return context


async def demo_loop_detection() -> None:
    """Step 5: Simulate loop detection during a Devin session."""
    banner("STEP 5: Loop Detection (Simulated Session)")

    detector = LoopDetector(
        command_repeat_threshold=3,
        command_repeat_window_seconds=120,
    )
    now = datetime.utcnow()

    # Normal progress
    snap1 = SessionSnapshot(
        timestamp=now,
        commands_executed=["git clone", "cat src/services/payment-service.ts"],
        files_read=["src/services/payment-service.ts"],
        files_modified=[],
        hypotheses_stated=[],
    )
    signal = detector.analyze(snap1)
    print(f"Snapshot 1 (exploring code): signal={signal.value}")

    # More progress
    snap2 = SessionSnapshot(
        timestamp=now + timedelta(seconds=20),
        commands_executed=["git log --oneline -5"],
        files_read=["src/cache/customer-cache.ts"],
        files_modified=[],
        hypotheses_stated=["Cache TTL was reduced causing null returns"],
    )
    signal = detector.analyze(snap2)
    print(f"Snapshot 2 (investigating):  signal={signal.value}")

    # Devin gets stuck — repeating the same command
    for i in range(3):
        snap = SessionSnapshot(
            timestamp=now + timedelta(seconds=40 + i * 10),
            commands_executed=["npm test"],
            files_read=[],
            files_modified=[],
            hypotheses_stated=[],
        )
        signal = detector.analyze(snap)
        print(
            f"Snapshot {3 + i} (npm test #{i + 1}):  "
            f"signal={signal.value}"
        )

    print(f"\nRedirect count: {detector.redirect_count}")
    print(f"Trigger reason: {detector.get_last_trigger_reason()}")

    # Recovery after redirect
    snap_recovery = SessionSnapshot(
        timestamp=now + timedelta(seconds=200),
        commands_executed=["git diff HEAD~1"],
        files_read=["src/services/payment-service.ts"],
        files_modified=["src/services/payment-service.ts"],
        hypotheses_stated=["Found the bug — missing null check in retry"],
    )
    signal = detector.analyze(snap_recovery)
    print(f"Snapshot 6 (recovery):       signal={signal.value}")


async def demo_metrics() -> None:
    """Step 6: Demonstrate the metrics/dashboard system."""
    banner("STEP 6: Metrics & Dashboard")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = MetricsStore(db_path=db_path)
    await store.initialize()

    # Record some investigations
    now = datetime.utcnow()
    investigations = [
        Investigation(
            investigation_id="inv_001",
            service_name="payment-service",
            dedup_key="payment-service:TypeError:abc123",
            triage_classification="code_level_bug",
            triage_confidence=0.92,
            session_id="ses_001",
            created_at=now - timedelta(hours=2),
        ),
        Investigation(
            investigation_id="inv_002",
            service_name="payment-service",
            dedup_key="payment-service:TimeoutError:def456",
            triage_classification="transient_infra",
            triage_confidence=0.95,
            created_at=now - timedelta(hours=1),
        ),
        Investigation(
            investigation_id="inv_003",
            service_name="auth-service",
            dedup_key="auth-service:SyntaxError:ghi789",
            triage_classification="code_level_bug",
            triage_confidence=0.88,
            session_id="ses_003",
            created_at=now - timedelta(minutes=30),
        ),
    ]

    for inv in investigations:
        await store.record_investigation(inv)

    # Update outcomes
    await store.update_investigation_outcome(
        "inv_001",
        session_outcome="fix_pr",
        acus_consumed=4.2,
        pr_url="https://github.com/acme/payment-service/pull/42",
        resolved_at=now - timedelta(hours=1),
    )
    await store.update_investigation_outcome(
        "inv_003",
        session_outcome="hypothesis",
        acus_consumed=6.1,
        resolved_at=now - timedelta(minutes=10),
    )

    # Get summary
    summary = await store.get_summary(
        period_start=now - timedelta(days=1),
        period_end=now,
    )
    print("Dashboard Summary (last 24h):")
    print(f"  Total investigations: {summary['total_investigations']}")
    print(f"  Dispatched to Devin: {summary['dispatched_to_devin']}")
    print(f"  Total ACUs:          {summary['total_acus']}")
    print(f"  ACU cost (USD):      ${summary['total_acu_cost_usd']}")
    print("  Outcomes:")
    for outcome, count in summary["outcomes"].items():
        print(f"    {outcome}: {count}")

    # Service success rate
    rate = await store.get_service_success_rate("payment-service")
    print("\npayment-service success rate:")
    print(f"  {rate['successful_investigations']}/{rate['total_investigations']}"
          f" = {rate['success_rate']:.0%}")

    await store.close()

    # Clean up temp file
    import os
    os.unlink(db_path)


async def main() -> None:
    """Run the full demo workflow."""
    print("\n" + "=" * 60)
    print("  DevinGuard Demo Workflow")
    print("  Autonomous Incident Response — From Alert to Fix PR")
    print("=" * 60)

    # Step 1: Alert ingestion
    alert = await demo_alert_ingestion()

    # Step 2: Deduplication
    await demo_deduplication(alert)

    # Step 3: Triage
    await demo_triage(alert)

    # Step 4: Enrichment
    await demo_enrichment()

    # Step 5: Loop detection
    await demo_loop_detection()

    # Step 6: Metrics
    await demo_metrics()

    # Summary
    banner("DEMO COMPLETE")
    print("The full DevinGuard pipeline has been demonstrated:")
    print("  1. Alert ingestion from PagerDuty webhook")
    print("  2. Deduplication with composite key + TTL")
    print("  3. Two-stage triage (rule-based shown; LLM available)")
    print("  4. Context enrichment (GitHub commits, Sentry details)")
    print("  5. Loop detection with redirect/terminate actions")
    print("  6. Metrics dashboard with SQLite backend")
    print()
    print("In production, step 4-5 would dispatch a Devin session via")
    print("the Devin API and monitor it with the PollingSessionMonitor.")
    print()
    print("To run the full live demo with real API keys:")
    print("  1. Start the sample service:  cd sample-service && npm run dev")
    print("  2. Start the orchestrator:    cd orchestrator && poetry run fastapi dev app/main.py")
    print("  3. Trigger the bug:           cd sample-service && npm run trigger-bug")
    print("  4. Watch the dashboard:       http://localhost:8000/dashboard")
    print()


if __name__ == "__main__":
    asyncio.run(main())
