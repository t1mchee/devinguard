"""Session monitor interface — abstracts how Devin sessions are observed.

The orchestrator depends on this interface, not the concrete implementation.
This allows swapping polling for webhooks/SSE later with no orchestration changes.
"""

from abc import ABC, abstractmethod
from typing import Awaitable, Callable


class SessionMonitor(ABC):
    """Abstract base class for monitoring Devin session lifecycle."""

    @abstractmethod
    async def watch(
        self,
        session_id: str,
        on_complete: Callable[[dict], Awaitable[None]],
        on_error: Callable[[dict], Awaitable[None]],
        on_progress: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Begin monitoring a Devin session.

        Calls the appropriate callback when the session state changes.

        Args:
            session_id: The Devin session ID to monitor.
            on_complete: Called when session finishes (status in ["exit"]).
            on_error: Called when session errors or times out.
            on_progress: Called on each poll/event with latest session state.
                         Used by loop detection (see loop_detection.py).
        """

    @abstractmethod
    async def stop(self, session_id: str) -> None:
        """Stop monitoring a session (e.g., on manual cancellation)."""
