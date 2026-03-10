"""Dashboard API endpoints.

Provides metrics and investigation data for the operator dashboard,
including real-time activity feed via SSE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse

from app.events.feed import activity_feed

if TYPE_CHECKING:
    from app.metrics.store import MetricsStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


def _get_metrics_store(request: Request) -> MetricsStore:
    return request.app.state.metrics_store


@router.get("/summary")
async def get_summary(
    request: Request,
    period: Literal["day", "week", "month"] = "week",
    service: Optional[str] = None,
) -> dict:
    """Current period summary metrics."""
    store = _get_metrics_store(request)
    now = datetime.utcnow()

    period_map = {"day": timedelta(days=1), "week": timedelta(weeks=1), "month": timedelta(days=30)}
    period_start = now - period_map[period]

    return await store.get_summary(period_start, now, service)


@router.get("/triage-accuracy")
async def get_triage_accuracy(
    request: Request,
    weeks: int = 12,
    service: Optional[str] = None,
) -> list[dict]:
    """Weekly triage precision/recall trend."""
    store = _get_metrics_store(request)
    return await store.get_triage_accuracy_trend(weeks, service)


@router.get("/acu-spend")
async def get_acu_spend(
    request: Request,
    days: int = 30,
    service: Optional[str] = None,
) -> list[dict]:
    """Daily ACU spend trend."""
    store = _get_metrics_store(request)
    return await store.get_acu_spend_trend(days, service)


@router.get("/outcomes")
async def get_outcome_distribution(
    request: Request,
    period: Literal["day", "week", "month"] = "week",
    service: Optional[str] = None,
) -> dict:
    """Outcome distribution (fix_pr, hypothesis, inconclusive, false_dispatch)."""
    store = _get_metrics_store(request)
    now = datetime.utcnow()

    period_map = {"day": timedelta(days=1), "week": timedelta(weeks=1), "month": timedelta(days=30)}
    period_start = now - period_map[period]

    summary = await store.get_summary(period_start, now, service)
    return summary.get("outcomes", {})


@router.get("/investigations")
async def list_investigations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    service: Optional[str] = None,
    outcome: Optional[str] = None,
) -> list[dict]:
    """Paginated list of individual investigations."""
    store = _get_metrics_store(request)
    return await store.list_investigations(limit, offset, service, outcome)


@router.post("/investigations/{investigation_id}/label")
async def label_investigation(
    request: Request,
    investigation_id: str,
    triage_was_correct: Optional[bool] = None,
    pr_merged: Optional[bool] = None,
    pr_reverted: Optional[bool] = None,
    human_investigation_time_minutes: Optional[float] = None,
) -> dict:
    """Retroactive labeling endpoint for on-call engineers.

    Allows updating investigation records with ground-truth labels
    that feed back into accuracy metrics and classifier training.
    """
    store = _get_metrics_store(request)

    kwargs: dict = {}
    if triage_was_correct is not None:
        kwargs["triage_was_correct"] = triage_was_correct
    if pr_merged is not None:
        kwargs["pr_merged"] = pr_merged
    if pr_reverted is not None:
        kwargs["pr_reverted"] = pr_reverted
    if human_investigation_time_minutes is not None:
        kwargs["human_investigation_time_minutes"] = human_investigation_time_minutes

    if not kwargs:
        return {"status": "no_updates"}

    await store.update_investigation_outcome(investigation_id, **kwargs)
    return {"status": "updated", "investigation_id": investigation_id, "updates": kwargs}


@router.get("/events")
async def get_recent_events(limit: int = 50) -> list[dict]:
    """Return recent activity feed events."""
    events = activity_feed.recent(limit)
    return [e.model_dump() for e in events]


@router.get("/events/stream")
async def event_stream(request: Request) -> StreamingResponse:
    """SSE endpoint — streams real-time pipeline events to the dashboard."""
    queue = activity_feed.subscribe()

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    data = json.dumps(event.model_dump())
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            activity_feed.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/live-investigations")
async def live_investigations(request: Request) -> list[dict]:
    """Return in-memory investigations from the dispatcher (live status)."""
    from app.api.webhooks import get_dispatcher

    dispatcher = get_dispatcher(request)
    investigations = dispatcher.list_investigations()
    result = []
    for inv in investigations:
        d = inv.model_dump()
        # Add session URL for active sessions
        if inv.session_id:
            # Strip "devin-" prefix if present for URL
            sid = inv.session_id
            if sid.startswith("devin-"):
                sid = sid[6:]
            d["session_url"] = f"https://app.devin.ai/sessions/{sid}"
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Demo trigger endpoints
# ---------------------------------------------------------------------------

_DEMO_PAYLOADS = {
    "typeerror": {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "demo-typeerror",
                "title": "TypeError: Cannot read properties of null",
                "urgency": "high",
                "service": {"name": "payment-service"},
                "body": {
                    "details": {
                        "error_class": "TypeError",
                        "error_message": "Cannot read properties of null (reading 'paymentMethodId')",
                        "stack_trace": (
                            "TypeError: Cannot read properties of null (reading 'paymentMethodId')\n"
                            "    at ChargeHandler.handle (charge-handler.ts:25)\n"
                            "    at PaymentService.processCharge (payment-service.ts:98)\n"
                            "    at Router.handle (router.ts:44)"
                        ),
                    }
                },
            },
        }
    },
    "oomkilled": {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "demo-oomkilled",
                "title": "OOMKilled: pod exceeded memory limit",
                "urgency": "high",
                "service": {"name": "api-gateway"},
                "body": {
                    "details": {
                        "error_class": "OOMKilled",
                        "error_message": "Container exceeded memory limit of 512Mi",
                    }
                },
            },
        }
    },
    "latency": {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "demo-latency",
                "title": "High latency: p99 > 5s on /api/checkout",
                "urgency": "high",
                "service": {"name": "checkout-service"},
                "body": {
                    "details": {
                        "error_class": "LatencySpike",
                        "error_message": "p99 latency exceeded 5000ms on /api/checkout endpoint",
                    }
                },
            },
        }
    },
}


@router.post("/demo/trigger")
async def trigger_demo(
    request: Request,
    background_tasks: BackgroundTasks,
    scenario: str = "typeerror",
) -> dict:
    """Fire a demo webhook through the pipeline. No curl needed."""
    from app.api.webhooks import get_dispatcher
    from app.webhooks.normalizers import normalize_pagerduty

    payload = _DEMO_PAYLOADS.get(scenario)
    if not payload:
        return {"error": f"Unknown scenario: {scenario}", "available": list(_DEMO_PAYLOADS.keys())}

    alert = normalize_pagerduty(payload)
    dispatcher = get_dispatcher(request)
    result = await dispatcher.handle_alert(alert)

    if result.get("action") == "dispatched_to_devin":
        investigation_id = result["investigation_id"]
        background_tasks.add_task(dispatcher.monitor_session, investigation_id)

    return result


@router.get("/demo/scenarios")
async def list_demo_scenarios() -> list[dict]:
    """List available demo scenarios."""
    scenarios = []
    for key, payload in _DEMO_PAYLOADS.items():
        data = payload["event"]["data"]
        scenarios.append({
            "id": key,
            "title": data["title"],
            "service": data["service"]["name"],
            "error_class": data["body"]["details"]["error_class"],
        })
    return scenarios


# ---------------------------------------------------------------------------
# Session status polling (for live Devin progress on cards)
# ---------------------------------------------------------------------------

@router.get("/session-status/{session_id}")
async def get_session_status(request: Request, session_id: str) -> dict:
    """Poll Devin API for session progress. Returns status and structured steps."""
    from app.core.devin_client import DevinAPIClient

    client = DevinAPIClient()
    try:
        session = await client.get_session(session_id)
    except Exception as exc:
        return {"error": str(exc), "session_id": session_id}
    finally:
        await client.close()

    status = session.get("status", "unknown")
    status_enum = session.get("status_enum", status)

    # Build progress steps from session data
    steps: list[dict] = []
    steps.append({"label": "Session created", "status": "done", "ts": session.get("created_at")})

    if status_enum in ("running", "blocked", "stopped", "finished"):
        steps.append({"label": "Cloning repository", "status": "done"})

    if status_enum in ("running", "blocked"):
        steps.append({"label": "Analyzing code", "status": "active"})
    elif status_enum in ("stopped", "finished"):
        steps.append({"label": "Analyzing code", "status": "done"})
        steps.append({"label": "Writing fix", "status": "done"})

    prs = session.get("pull_requests", [])
    if prs:
        steps.append({"label": "Running tests", "status": "done"})
        steps.append({
            "label": "PR opened",
            "status": "done",
            "pr_url": prs[0].get("pr_url", ""),
        })
    elif status_enum == "finished":
        steps.append({"label": "Investigation complete", "status": "done"})

    return {
        "session_id": session_id,
        "status": status,
        "status_enum": status_enum,
        "steps": steps,
        "pull_requests": prs,
        "acus_consumed": session.get("acus_consumed", 0),
        "structured_output": session.get("structured_output"),
    }


# ---------------------------------------------------------------------------
# Eval scorecard endpoint
# ---------------------------------------------------------------------------

@router.get("/eval-scorecard")
async def get_eval_scorecard() -> dict:
    """Return cached eval results for the scorecard panel."""
    eval_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "scripts", "eval_results.json"
    )
    eval_path = os.path.normpath(eval_path)
    try:
        with open(eval_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"error": "Eval results not found. Run: PYTHONPATH=. poetry run python scripts/eval_triage.py --cached"}
