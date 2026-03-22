"""Metrics data models for the operator dashboard."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class InvestigationRecord(BaseModel):
    """Persisted after every investigation completes."""

    investigation_id: str
    service_name: str
    alert_dedup_key: str
    triage_classification: Optional[str] = None
    triage_confidence: Optional[float] = None
    triage_was_correct: Optional[bool] = None  # Set retroactively
    dispatched_to_devin: bool = False
    session_id: Optional[str] = None
    session_outcome: Optional[
        Literal["fix_pr", "hypothesis", "inconclusive", "false_dispatch"]
    ] = None
    acus_consumed: Optional[float] = None
    pr_url: Optional[str] = None
    pr_merged: Optional[bool] = None  # Set retroactively
    pr_reverted: Optional[bool] = None  # Set retroactively
    human_investigation_time_minutes: Optional[float] = None  # Set retroactively
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class MetricsSummary(BaseModel):
    """Aggregated metrics for a time period."""

    period_start: datetime
    period_end: datetime
    service_name: Optional[str] = None
    total_alerts: int = 0
    total_investigations: int = 0
    alerts_deduplicated: int = 0
    dispatched_to_devin: int = 0
    outcomes: dict[str, int] = Field(default_factory=dict)
    total_acus: float = 0.0
    total_acu_cost_usd: float = 0.0
    precision: Optional[float] = None
    recall: Optional[float] = None
    avg_mttr_with_devin_minutes: Optional[float] = None
    avg_mttr_without_devin_minutes: Optional[float] = None
