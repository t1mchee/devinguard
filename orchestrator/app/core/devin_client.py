"""Devin API client.

Supports both v1 (personal API keys) and v3 (service user keys) endpoints.
https://docs.devin.ai/api-reference/overview
"""

import logging
from typing import Optional

import httpx

from app.config import settings
from app.models.devin import CreateSessionRequest, SendMessageRequest

logger = logging.getLogger(__name__)


class DevinAPIError(Exception):
    """Raised when a Devin API call fails."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Devin API error ({status_code}): {message}")


class DevinAPIClient:
    """Client for the Devin API.

    Handles authentication, session creation, polling, messaging, and termination.
    Automatically selects v1 or v3 endpoints based on the API key format:
      - Personal keys (apk_user_*): use /v1/sessions
      - Service user keys (cog_*): use /v3/organizations/sessions
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        org_id: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self._api_key = api_key or settings.devin_api_key
        self._org_id = org_id or settings.devin_org_id
        self._base_url = (base_url or settings.devin_api_base_url).rstrip("/")
        self._is_personal_key = self._api_key.startswith("apk_")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    @property
    def _sessions_url(self) -> str:
        if self._is_personal_key:
            return "/v1/sessions"
        return "/v3/organizations/sessions"

    async def create_session(self, request: CreateSessionRequest) -> dict:
        """Create a new Devin session."""
        response = await self._client.post(
            self._sessions_url,
            json=request.model_dump(exclude_none=True),
        )
        self._check_response(response)
        data = response.json()
        logger.info(f"Created Devin session: {data.get('session_id')} — {data.get('url')}")
        return data

    async def get_session(self, session_id: str) -> dict:
        """Get session details."""
        response = await self._client.get(f"{self._sessions_url}/{session_id}")
        self._check_response(response)
        return response.json()

    async def send_message(self, session_id: str, message: str) -> dict:
        """Send a message to an active session."""
        request = SendMessageRequest(message=message)
        response = await self._client.post(
            f"{self._sessions_url}/{session_id}/message",
            json=request.model_dump(),
        )
        self._check_response(response)
        return response.json()

    async def terminate_session(self, session_id: str) -> dict:
        """Terminate an active session."""
        response = await self._client.delete(f"{self._sessions_url}/{session_id}")
        self._check_response(response)
        return response.json()

    async def list_sessions(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """List sessions with optional filters."""
        params: dict = {"limit": limit}
        if status:
            params["status"] = status
        if tags:
            params["tags"] = tags
        response = await self._client.get(self._sessions_url, params=params)
        self._check_response(response)
        return response.json()

    def _check_response(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise DevinAPIError(response.status_code, str(detail))

    async def close(self) -> None:
        await self._client.aclose()
