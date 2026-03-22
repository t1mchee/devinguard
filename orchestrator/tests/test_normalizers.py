"""Tests for webhook payload normalizers."""

import pytest

from app.webhooks.normalizers import (
    NormalizationError,
    normalize_custom,
    normalize_pagerduty,
    normalize_sentry,
)


def test_normalize_pagerduty_valid():
    """Valid PagerDuty webhook should normalize correctly."""
    payload = {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "P123",
                "title": "Payment service errors",
                "urgency": "high",
                "service": {"name": "payment-service"},
                "body": {
                    "details": {
                        "error_class": "TypeError",
                        "error_message": "Cannot read properties of null",
                        "stack_trace": "    at processPayment (src/handlers/payment.ts:142:15)",
                    }
                },
            },
        }
    }
    alert = normalize_pagerduty(payload)
    assert alert.source == "pagerduty"
    assert alert.service_name == "payment-service"
    assert alert.error_class == "TypeError"
    assert alert.severity == "P1"
    assert alert.stack_trace is not None


def test_normalize_pagerduty_missing_service():
    """PagerDuty webhook without service should raise NormalizationError."""
    payload = {"event": {"data": {"title": "Something broke"}}}
    with pytest.raises(NormalizationError) as exc_info:
        normalize_pagerduty(payload)
    assert "pagerduty" in str(exc_info.value)


def test_normalize_sentry_valid():
    """Valid Sentry webhook should normalize correctly."""
    payload = {
        "project_slug": "payment-service",
        "event": {
            "title": "TypeError: Cannot read properties of null",
            "exception": {
                "values": [
                    {
                        "type": "TypeError",
                        "value": "Cannot read properties of null (reading 'customerId')",
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": "src/router.ts",
                                    "function": "Router.handle",
                                    "lineno": 67,
                                },
                                {
                                    "filename": "src/handlers/payment.ts",
                                    "function": "processPayment",
                                    "lineno": 142,
                                },
                            ]
                        },
                    }
                ]
            },
        },
        "level": "error",
    }
    alert = normalize_sentry(payload)
    assert alert.source == "sentry"
    assert alert.service_name == "payment-service"
    assert alert.error_class == "TypeError"
    assert alert.severity == "P2"
    assert "processPayment" in (alert.stack_trace or "")


def test_normalize_sentry_missing_project():
    """Sentry webhook without project_slug should raise NormalizationError."""
    payload = {"event": {"title": "Error"}}
    with pytest.raises(NormalizationError):
        normalize_sentry(payload)


def test_normalize_custom_valid():
    """Valid custom payload should normalize correctly."""
    payload = {
        "source": "custom",
        "service_name": "test-service",
        "error_class": "RuntimeError",
        "error_message": "Something went wrong",
    }
    alert = normalize_custom(payload)
    assert alert.source == "custom"
    assert alert.service_name == "test-service"


def test_normalize_custom_missing_fields():
    """Custom payload missing required fields should raise NormalizationError."""
    payload = {"source": "custom", "service_name": "test-service"}
    with pytest.raises(NormalizationError):
        normalize_custom(payload)
