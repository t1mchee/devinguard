"""Webhook API endpoints.

Receives alerts from PagerDuty, Sentry, and custom sources.
Normalizes, deduplicates, and dispatches through the pipeline.
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.core.dispatcher import InvestigationDispatcher
from app.models.alert import AlertEvent
from app.webhooks.normalizers import (
    NormalizationError,
    normalize_custom,
    normalize_pagerduty,
    normalize_sentry,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

# Singleton dispatcher — initialized on first use
_dispatcher: Optional[InvestigationDispatcher] = None


def get_dispatcher() -> InvestigationDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = InvestigationDispatcher()
    return _dispatcher


@router.post("/webhooks/pagerduty")
async def pagerduty_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Receive PagerDuty webhook and dispatch through the pipeline."""
    payload = await request.json()
    logger.info("Received PagerDuty webhook")

    try:
        alert = normalize_pagerduty(payload)
    except NormalizationError as e:
        logger.warning(f"PagerDuty normalization failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    return await _process_alert(alert, background_tasks)


@router.post("/webhooks/sentry")
async def sentry_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Receive Sentry webhook and dispatch through the pipeline."""
    payload = await request.json()
    logger.info("Received Sentry webhook")

    try:
        alert = normalize_sentry(payload)
    except NormalizationError as e:
        logger.warning(f"Sentry normalization failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    return await _process_alert(alert, background_tasks)


@router.post("/webhooks/custom")
async def custom_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Receive custom alert webhook and dispatch through the pipeline."""
    payload = await request.json()
    logger.info("Received custom webhook")

    try:
        alert = normalize_custom(payload)
    except NormalizationError as e:
        logger.warning(f"Custom normalization failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    return await _process_alert(alert, background_tasks)


@router.post("/webhooks/test")
async def test_webhook(alert: AlertEvent, background_tasks: BackgroundTasks) -> dict:
    """Test endpoint that accepts a pre-normalized AlertEvent directly.

    Useful for demos and integration testing without real PagerDuty/Sentry.
    """
    logger.info(f"Received test alert: {alert.service_name}/{alert.error_class}")
    return await _process_alert(alert, background_tasks)


async def _process_alert(alert: AlertEvent, background_tasks: BackgroundTasks) -> dict:
    """Process a normalized alert through the pipeline."""
    dispatcher = get_dispatcher()
    result = await dispatcher.handle_alert(alert)

    # If dispatched to Devin, start monitoring in background
    if result.get("action") == "dispatched_to_devin":
        investigation_id = result["investigation_id"]
        background_tasks.add_task(dispatcher.monitor_session, investigation_id)

    return result


@router.get("/investigations")
async def list_investigations() -> list[dict]:
    """List all active and completed investigations."""
    dispatcher = get_dispatcher()
    investigations = dispatcher.list_investigations()
    return [inv.model_dump() for inv in investigations]


@router.get("/investigations/{investigation_id}")
async def get_investigation(investigation_id: str) -> dict:
    """Get details of a specific investigation."""
    dispatcher = get_dispatcher()
    investigation = dispatcher.get_investigation(investigation_id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation.model_dump()
