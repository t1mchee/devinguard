"""Canonical alert schema for DevinGuard.

All webhook sources (PagerDuty, Sentry, custom) are normalized to this schema
before entering the pipeline.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class AlertEvent(BaseModel):
    """Canonical alert event — the common schema all webhooks normalize into."""

    source: Literal["pagerduty", "sentry", "custom"]
    service_name: str = Field(description="e.g. 'payment-service'")
    error_class: str = Field(description="e.g. 'TypeError', 'ConnectionRefused'")
    error_message: str = Field(description="Full error message string")
    stack_trace: Optional[str] = Field(default=None, description="Full stack trace if available")
    stack_trace_fingerprint: Optional[str] = Field(
        default=None, description="Computed in fingerprinting step"
    )
    severity: Literal["P1", "P2", "P3", "P4"] = "P3"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    raw_payload: dict = Field(default_factory=dict, description="Original webhook body")
    dedup_key: Optional[str] = Field(default=None, description="Computed in dedup step")


class Investigation(BaseModel):
    """An active or completed investigation triggered by one or more alerts."""

    investigation_id: str
    service_name: str
    dedup_key: str
    alert_count: int = 1
    triage_classification: Optional[str] = None
    triage_confidence: Optional[float] = None
    session_id: Optional[str] = None
    session_status: Optional[str] = None
    session_outcome: Optional[Literal["fix_pr", "hypothesis", "inconclusive", "false_dispatch"]] = (
        None
    )
    acus_consumed: Optional[float] = None
    pr_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class EnrichedContext(BaseModel):
    """Context gathered by the enrichment engine for an alert."""

    recent_commits: list[dict] = Field(default_factory=list)
    sentry_error_details: Optional[dict] = None
    service_owner: Optional[str] = None
    service_team: Optional[str] = None
    repo_url: Optional[str] = None
    branch: str = "main"
    related_past_incidents: list[dict] = Field(default_factory=list)
