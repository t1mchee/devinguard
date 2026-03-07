"""Tests for the triage classifier."""

import pytest

from app.core.triage import classify_alert
from app.models.alert import AlertEvent


@pytest.mark.asyncio
async def test_triage_infra_oom():
    """OOMKilled should be classified as INFRASTRUCTURE."""
    alert = AlertEvent(
        source="custom",
        service_name="test-service",
        error_class="OOMKilled",
        error_message="Container killed: OOMKilled (memory limit exceeded)",
    )
    result = await classify_alert(alert)
    assert result.classification == "INFRASTRUCTURE"
    assert result.confidence >= 0.9
    assert result.should_dispatch_to_devin is False


@pytest.mark.asyncio
async def test_triage_infra_disk():
    """Disk full should be classified as INFRASTRUCTURE."""
    alert = AlertEvent(
        source="custom",
        service_name="test-service",
        error_class="DiskError",
        error_message="No space left on device (disk full)",
    )
    result = await classify_alert(alert)
    assert result.classification == "INFRASTRUCTURE"
    assert result.should_dispatch_to_devin is False


@pytest.mark.asyncio
async def test_triage_infra_connection():
    """Connection refused should be classified as INFRASTRUCTURE."""
    alert = AlertEvent(
        source="custom",
        service_name="test-service",
        error_class="ConnectionError",
        error_message="connect ECONNREFUSED 10.0.0.1:5432",
    )
    result = await classify_alert(alert)
    assert result.classification == "INFRASTRUCTURE"
    assert result.should_dispatch_to_devin is False


@pytest.mark.asyncio
async def test_triage_code_level_typeerror():
    """TypeError should be classified as CODE_LEVEL."""
    alert = AlertEvent(
        source="custom",
        service_name="test-service",
        error_class="TypeError",
        error_message="Cannot read properties of null (reading 'customerId')",
        stack_trace="    at processPayment (src/handlers/payment.ts:142:15)",
    )
    result = await classify_alert(alert)
    assert result.classification == "CODE_LEVEL"
    assert result.confidence >= 0.8
    assert result.should_dispatch_to_devin is True


@pytest.mark.asyncio
async def test_triage_code_level_syntax():
    """SyntaxError should be classified as CODE_LEVEL with high confidence."""
    alert = AlertEvent(
        source="custom",
        service_name="test-service",
        error_class="SyntaxError",
        error_message="SyntaxError: Unexpected token '}' at line 42",
    )
    result = await classify_alert(alert)
    assert result.classification == "CODE_LEVEL"
    assert result.confidence >= 0.85
    assert result.should_dispatch_to_devin is True


@pytest.mark.asyncio
async def test_triage_ambiguous_no_llm():
    """Ambiguous alert with no LLM should fall back to AMBIGUOUS."""
    alert = AlertEvent(
        source="custom",
        service_name="test-service",
        error_class="PerformanceWarning",
        error_message="Latency spike detected (p99 > 2000ms)",
    )
    result = await classify_alert(alert, anthropic_client=None)
    assert result.classification == "AMBIGUOUS"
    assert result.should_dispatch_to_devin is False
