"""Dashboard API endpoints.

Provides metrics and investigation data for the operator dashboard.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, Optional

from fastapi import APIRouter, Request

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
