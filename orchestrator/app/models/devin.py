"""Devin API request/response models.

Based on the Devin v3 API documentation:
https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SessionSecretInput(BaseModel):
    """A secret to inject into a Devin session."""

    key: str
    value: str
    sensitive: bool = True


class CreateSessionRequest(BaseModel):
    """Request body for POST /v3/organizations/{org_id}/sessions."""

    prompt: str
    repos: Optional[list[str]] = None
    knowledge_ids: Optional[list[str]] = None
    playbook_id: Optional[str] = None
    max_acu_limit: Optional[int] = None
    secret_ids: Optional[list[str]] = None
    session_secrets: Optional[list[SessionSecretInput]] = None
    tags: Optional[list[str]] = None
    title: Optional[str] = None


class SessionPullRequest(BaseModel):
    """A pull request associated with a Devin session."""

    pr_url: str
    pr_state: str


class SessionResponse(BaseModel):
    """Response from GET/POST /v3/organizations/{org_id}/sessions/{session_id}."""

    session_id: str
    status: Literal["new", "claimed", "running", "exit", "error", "suspended", "resuming"]
    url: str
    acus_consumed: float = 0.0
    created_at: int
    updated_at: int
    org_id: str = ""
    pull_requests: list[SessionPullRequest] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    title: Optional[str] = None
    child_session_ids: Optional[list[str]] = None
    is_advanced: bool = False
    is_archived: bool = False
    parent_session_id: Optional[str] = None
    user_id: Optional[str] = None
    # Additional fields from structured output (may not always be present)
    structured_output: Optional[dict] = None


class SendMessageRequest(BaseModel):
    """Request body for POST /v3/organizations/{org_id}/sessions/{session_id}/message."""

    message: str
