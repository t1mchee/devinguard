"""Polling-based session monitor.

Polls the Devin API at a configurable interval (default 10s) to track
session progress. This is the v1 implementation — designed to be swapped
for event-driven notification when the Devin API supports it.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable

from app.core.devin_client import DevinAPIClient
from app.session.monitor import SessionMonitor

logger = logging.getLogger(__name__)

# Session statuses that indicate completion
_COMPLETE_STATUSES = {"exit"}
_ERROR_STATUSES = {"error"}
_TERMINAL_STATUSES = _COMPLETE_STATUSES | _ERROR_STATUSES


class PollingSessionMonitor(SessionMonitor):
    """Monitors Devin sessions by polling the API at regular intervals.

    The polling interval is configurable and defaults to 10 seconds.
    The monitor layer is abstracted behind SessionMonitor so it can be
    swapped for event-driven notification (webhooks or SSE) when the
    Devin API supports it, with no changes to the orchestration logic.
    """

    def __init__(
        self,
        devin_client: DevinAPIClient,
        poll_interval_seconds: int = 10,
        max_poll_duration_seconds: int = 9000,  # ~150 min ≈ 10 ACUs hard cap
    ):
        self._client = devin_client
        self._poll_interval = poll_interval_seconds
        self._max_duration = max_poll_duration_seconds
        self._active_watches: dict[str, bool] = {}

    async def watch(
        self,
        session_id: str,
        on_complete: Callable[[dict], Awaitable[None]],
        on_error: Callable[[dict], Awaitable[None]],
        on_progress: Callable[[dict], Awaitable[None]],
    ) -> None:
        self._active_watches[session_id] = True
        start_time = time.monotonic()

        logger.info(
            f"Started monitoring session {session_id} "
            f"(interval={self._poll_interval}s, max={self._max_duration}s)"
        )

        try:
            while self._active_watches.get(session_id, False):
                elapsed = time.monotonic() - start_time

                # Check timeout
                if elapsed > self._max_duration:
                    logger.warning(
                        f"Session {session_id} exceeded max poll duration "
                        f"({self._max_duration}s). Triggering timeout."
                    )
                    await on_error({
                        "reason": "timeout",
                        "session_id": session_id,
                        "elapsed_seconds": elapsed,
                    })
                    return

                # Poll session status
                try:
                    response = await self._client.get_session(session_id)
                except Exception as e:
                    logger.error(f"Failed to poll session {session_id}: {e}")
                    await asyncio.sleep(self._poll_interval)
                    continue

                status = response.get("status", "unknown")

                if status in _COMPLETE_STATUSES:
                    logger.info(f"Session {session_id} completed with status: {status}")
                    await on_complete(response)
                    return

                if status in _ERROR_STATUSES:
                    logger.warning(f"Session {session_id} errored with status: {status}")
                    await on_error(response)
                    return

                # Session still running — report progress
                await on_progress(response)

                await asyncio.sleep(self._poll_interval)

        finally:
            self._active_watches.pop(session_id, None)

    async def stop(self, session_id: str) -> None:
        logger.info(f"Stopping monitor for session {session_id}")
        self._active_watches[session_id] = False


class WebhookSessionMonitor(SessionMonitor):
    """Placeholder for when the Devin API supports completion webhooks.

    Not used in v1. The interface is proven so the swap is trivial later.
    When available, this registers a callback for each session ID and
    exposes a FastAPI endpoint that the Devin API calls on state change.
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, dict] = {}

    async def watch(
        self,
        session_id: str,
        on_complete: Callable[[dict], Awaitable[None]],
        on_error: Callable[[dict], Awaitable[None]],
        on_progress: Callable[[dict], Awaitable[None]],
    ) -> None:
        # Register callbacks — the webhook endpoint will invoke them
        self._callbacks[session_id] = {
            "on_complete": on_complete,
            "on_error": on_error,
            "on_progress": on_progress,
        }
        logger.info(f"Registered webhook callbacks for session {session_id}")
        # NOTE: This method returns immediately. The webhook endpoint
        # (POST /callbacks/session/{session_id}) handles the actual events.

    async def stop(self, session_id: str) -> None:
        self._callbacks.pop(session_id, None)

    async def handle_webhook(self, session_id: str, payload: dict) -> None:
        """Called by the webhook endpoint when Devin sends a session update."""
        callbacks = self._callbacks.get(session_id)
        if not callbacks:
            logger.warning(f"Received webhook for unknown session {session_id}")
            return

        status = payload.get("status", "unknown")
        if status in _COMPLETE_STATUSES:
            await callbacks["on_complete"](payload)
            self._callbacks.pop(session_id, None)
        elif status in _ERROR_STATUSES:
            await callbacks["on_error"](payload)
            self._callbacks.pop(session_id, None)
        else:
            await callbacks["on_progress"](payload)
