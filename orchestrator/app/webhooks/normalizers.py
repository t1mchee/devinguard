"""Webhook payload normalizers.

Each function converts a source-specific webhook payload into the canonical
AlertEvent schema. Malformed payloads raise NormalizationError.
"""

import logging
from datetime import datetime
from typing import Optional

from app.models.alert import AlertEvent

logger = logging.getLogger(__name__)


class NormalizationError(Exception):
    """Raised when a webhook payload cannot be normalized."""

    def __init__(self, source: str, reason: str, payload: Optional[dict] = None):
        self.source = source
        self.reason = reason
        self.payload = payload
        super().__init__(f"[{source}] {reason}")


def normalize_pagerduty(payload: dict) -> AlertEvent:
    """Normalize a PagerDuty webhook payload to AlertEvent.

    Expected PagerDuty V2 webhook format:
    {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "...",
                "title": "...",
                "urgency": "high" | "low",
                "service": {"name": "payment-service", ...},
                "body": {"details": {"error_class": "...", "error_message": "...", ...}},
                ...
            }
        }
    }
    """
    try:
        event = payload["event"]
        data = event["data"]
        service = data["service"]
        service_name = service["name"]
    except (KeyError, TypeError) as e:
        raise NormalizationError("pagerduty", f"Missing required field: {e}", payload)

    # Extract error details from body if available
    body = data.get("body", {})
    details = body.get("details", {}) if isinstance(body, dict) else {}

    error_class = details.get("error_class", "UnknownError")
    error_message = details.get("error_message", data.get("title", "No message"))
    stack_trace = details.get("stack_trace")

    # Map urgency to severity
    urgency = data.get("urgency", "low")
    severity_map = {"high": "P1", "low": "P3"}
    severity = severity_map.get(urgency, "P3")

    return AlertEvent(
        source="pagerduty",
        service_name=service_name,
        error_class=error_class,
        error_message=error_message,
        stack_trace=stack_trace,
        severity=severity,
        timestamp=datetime.utcnow(),
        raw_payload=payload,
    )


def normalize_sentry(payload: dict) -> AlertEvent:
    """Normalize a Sentry webhook payload to AlertEvent.

    Expected Sentry webhook format (issue alert):
    {
        "project_slug": "payment-service",
        "event": {
            "title": "TypeError: Cannot read properties of null",
            "exception": {
                "values": [{
                    "type": "TypeError",
                    "value": "Cannot read properties of null (reading 'customerId')",
                    "stacktrace": {
                        "frames": [{"filename": "...", "function": "...", "lineno": ...}, ...]
                    }
                }]
            }
        },
        "level": "error",
        "fingerprint": ["..."]
    }
    """
    try:
        project_slug = payload.get("project_slug", payload.get("project", {}).get("slug", ""))
        if not project_slug:
            raise KeyError("project_slug")

        event_data = payload.get("event", {})
    except (KeyError, TypeError) as e:
        raise NormalizationError("sentry", f"Missing required field: {e}", payload)

    # Extract exception info
    error_class = "UnknownError"
    error_message = event_data.get("title", "No message")
    stack_trace = None

    exception_data = event_data.get("exception", {})
    values = exception_data.get("values", [])
    if values:
        first_exception = values[0]
        error_class = first_exception.get("type", "UnknownError")
        error_message = first_exception.get("value", error_message)

        # Build stack trace string from frames
        stacktrace = first_exception.get("stacktrace", {})
        frames = stacktrace.get("frames", [])
        if frames:
            trace_lines = []
            for frame in reversed(frames):  # Sentry frames are bottom-up
                filename = frame.get("filename", "?")
                function = frame.get("function", "?")
                lineno = frame.get("lineno", "?")
                trace_lines.append(f"    at {function} ({filename}:{lineno}:0)")
            stack_trace = "\n".join(trace_lines)

    # Use Sentry's fingerprint if available
    sentry_fingerprint = payload.get("fingerprint")
    stack_trace_fingerprint = None
    if sentry_fingerprint and isinstance(sentry_fingerprint, list):
        stack_trace_fingerprint = "|".join(str(f) for f in sentry_fingerprint)

    # Map level to severity
    level = payload.get("level", "error")
    level_severity_map = {"fatal": "P1", "error": "P2", "warning": "P3", "info": "P4"}
    severity = level_severity_map.get(level, "P3")

    return AlertEvent(
        source="sentry",
        service_name=project_slug,
        error_class=error_class,
        error_message=error_message,
        stack_trace=stack_trace,
        stack_trace_fingerprint=stack_trace_fingerprint,
        severity=severity,
        timestamp=datetime.utcnow(),
        raw_payload=payload,
    )


def normalize_custom(payload: dict) -> AlertEvent:
    """Normalize a custom webhook payload.

    Expects a payload that already conforms to AlertEvent fields.
    """
    required_fields = ["source", "service_name", "error_class", "error_message"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        raise NormalizationError("custom", f"Missing required fields: {missing}", payload)

    # Force source to custom
    payload["source"] = "custom"

    try:
        return AlertEvent(**payload)
    except Exception as e:
        raise NormalizationError("custom", f"Invalid payload: {e}", payload)
