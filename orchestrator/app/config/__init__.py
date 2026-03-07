"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """DevinGuard configuration."""

    # Devin API
    devin_api_key: str = ""
    devin_org_id: str = ""
    devin_api_base_url: str = "https://api.devin.ai"

    # Sentry
    sentry_auth_token: str = ""
    sentry_org_slug: str = ""
    sentry_project_slug: str = ""

    # PagerDuty
    pagerduty_api_key: str = ""
    pagerduty_integration_key: str = ""

    # GitHub
    github_token: str = ""
    github_repo: str = ""

    # Slack
    slack_bot_token: str = ""
    slack_incident_channel: str = ""

    # Anthropic (triage classifier)
    anthropic_api_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Polling
    poll_interval_seconds: int = 10

    # Dedup
    dedup_window_seconds: int = 300

    # Metrics
    metrics_db_path: str = "devinguard_metrics.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
