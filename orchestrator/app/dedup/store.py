"""Deduplication store — prevents duplicate Devin sessions for the same incident.

Uses Redis with SETNX for atomic check-and-set. Falls back to an in-memory
TTL cache if Redis is unavailable.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from cachetools import TTLCache

if TYPE_CHECKING:
    import redis.asyncio

logger = logging.getLogger(__name__)


class BaseDedupStore(ABC):
    """Abstract interface for dedup stores."""

    @abstractmethod
    async def check_and_set(self, dedup_key: str) -> tuple[bool, Optional[str]]:
        """Check if a dedup key already has an active investigation.

        Returns:
            (is_duplicate, existing_investigation_id)
            - (False, None) if this is the first alert with this key
            - (True, "inv_abc123") if an investigation already exists
        """

    @abstractmethod
    async def register_investigation(self, dedup_key: str, investigation_id: str) -> None:
        """Register a new investigation against a dedup key."""

    @abstractmethod
    async def extend_ttl(self, dedup_key: str) -> None:
        """Extend the TTL when a correlated alert arrives."""

    @abstractmethod
    async def remove(self, dedup_key: str) -> None:
        """Remove a dedup key (e.g., when investigation completes)."""


class RedisDedupStore(BaseDedupStore):
    """Redis-backed dedup store using SETNX for atomic operations."""

    def __init__(self, redis_client: redis.asyncio.Redis, default_ttl_seconds: int = 300):
        self._redis = redis_client
        self._ttl = default_ttl_seconds

    def _key(self, dedup_key: str) -> str:
        return f"dedup:{dedup_key}"

    async def check_and_set(self, dedup_key: str) -> tuple[bool, Optional[str]]:
        key = self._key(dedup_key)
        existing = await self._redis.get(key)
        if existing is not None:
            return (True, existing.decode() if isinstance(existing, bytes) else existing)
        return (False, None)

    async def register_investigation(self, dedup_key: str, investigation_id: str) -> None:
        key = self._key(dedup_key)
        await self._redis.set(key, investigation_id, ex=self._ttl, nx=True)

    async def extend_ttl(self, dedup_key: str) -> None:
        key = self._key(dedup_key)
        await self._redis.expire(key, self._ttl)

    async def remove(self, dedup_key: str) -> None:
        key = self._key(dedup_key)
        await self._redis.delete(key)


class InMemoryDedupStore(BaseDedupStore):
    """In-memory fallback dedup store using TTLCache.

    Suitable for single-instance deployments or when Redis is unavailable.
    Does not persist across restarts.
    """

    def __init__(self, default_ttl_seconds: int = 300, max_size: int = 10000):
        self._ttl = default_ttl_seconds
        self._cache: TTLCache[str, str] = TTLCache(maxsize=max_size, ttl=default_ttl_seconds)

    async def check_and_set(self, dedup_key: str) -> tuple[bool, Optional[str]]:
        existing = self._cache.get(dedup_key)
        if existing is not None:
            return (True, existing)
        return (False, None)

    async def register_investigation(self, dedup_key: str, investigation_id: str) -> None:
        self._cache[dedup_key] = investigation_id

    async def extend_ttl(self, dedup_key: str) -> None:
        # TTLCache doesn't support extending TTL directly.
        # Re-set the value to reset the TTL.
        existing = self._cache.get(dedup_key)
        if existing is not None:
            self._cache[dedup_key] = existing

    async def remove(self, dedup_key: str) -> None:
        self._cache.pop(dedup_key, None)
