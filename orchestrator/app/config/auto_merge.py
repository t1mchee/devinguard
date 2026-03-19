"""Auto-merge configuration and eligibility gate.

Gated auto-merge is a Phase 3+ capability. It is architecturally supported
from day one but gated behind a per-service opt-in flag that defaults to off.

Auto-merge is earned, not assumed — each service graduates to it independently
based on accumulated success data.
"""

from pydantic import BaseModel, Field


class AutoMergeConfig(BaseModel):
    """Per-service auto-merge eligibility configuration.

    All fields have safe defaults. Auto-merge is disabled by default and
    must be explicitly enabled per-service after sufficient track record.
    """

    enabled: bool = Field(
        default=False, description="Must be explicitly opted-in per service"
    )
    min_triage_confidence: float = Field(
        default=0.95, description="Triage classifier must be >= this to auto-merge"
    )
    max_files_changed: int = Field(
        default=3, description="PR must touch <= N files"
    )
    max_lines_changed: int = Field(
        default=50, description="PR must change <= N lines (additions + deletions)"
    )
    require_full_test_suite: bool = Field(
        default=True, description="All tests must pass (unit + integration)"
    )
    require_canary_deploy: bool = Field(
        default=True, description="Canary deployment must pass health checks"
    )
    canary_health_check_duration_minutes: int = Field(
        default=10, description="How long canary must be healthy"
    )
    auto_revert_on_error_rate_increase: bool = Field(
        default=True, description="Automatically revert if post-deploy errors spike"
    )
    error_rate_increase_threshold_percent: float = Field(
        default=5.0, description="Revert if error rate increases by > N%"
    )
    min_historical_success_rate: float = Field(
        default=0.90, description="Service must have >= 90% Devin success rate historically"
    )
    min_historical_investigations: int = Field(
        default=20, description="Must have >= N past investigations to establish track record"
    )
