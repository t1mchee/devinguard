"""Activity feed — in-memory event store for real-time dashboard updates.

Tracks every pipeline stage so the dashboard can show events as they happen:
  Alert Received → Dedup Check → Triage → Dispatch → Investigating → Fix PR
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from typing import Optional

from pydantic import BaseModel, Field


class FeedEvent(BaseModel):
    """A single event in the activity feed."""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = Field(default_factory=time.time)
    event_type: str  # alert_received, dedup_hit, triage_complete, dispatched, session_update, pr_opened, escalated
    investigation_id: Optional[str] = None
    service_name: Optional[str] = None
    title: str = ""
    detail: str = ""
    metadata: dict = Field(default_factory=dict)


class ActivityFeed:
    """In-memory ring buffer of pipeline events with SSE broadcast."""

    def __init__(self, max_events: int = 500) -> None:
        self._events: deque[FeedEvent] = deque(maxlen=max_events)
        self._subscribers: list[asyncio.Queue[FeedEvent]] = []

    def emit(self, event: FeedEvent) -> None:
        """Add an event and broadcast to all SSE subscribers."""
        self._events.append(event)
        dead: list[asyncio.Queue[FeedEvent]] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    def recent(self, limit: int = 50) -> list[FeedEvent]:
        """Return the most recent events (newest first)."""
        items = list(self._events)
        items.reverse()
        return items[:limit]

    def subscribe(self) -> asyncio.Queue[FeedEvent]:
        """Create an SSE subscription queue."""
        q: asyncio.Queue[FeedEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[FeedEvent]) -> None:
        """Remove an SSE subscription."""
        if q in self._subscribers:
            self._subscribers.remove(q)


# Global singleton — imported by dispatcher and API
activity_feed = ActivityFeed()
