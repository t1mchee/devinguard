"""Tests for the metrics store."""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from app.metrics.store import MetricsStore
from app.models.alert import Investigation


@pytest.fixture
async def metrics_store():
    """Create a temporary metrics store for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = MetricsStore(db_path=path)
    await store.initialize()
    yield store
    await store.close()
    os.unlink(path)


@pytest.mark.asyncio
async def test_record_and_retrieve_investigation(metrics_store: MetricsStore):
    """Should record an investigation and retrieve it."""
    inv = Investigation(
        investigation_id="inv_test001",
        service_name="payment-service",
        dedup_key="payment-service:TypeError:abc123",
        triage_classification="CODE_LEVEL",
        triage_confidence=0.87,
        session_id="sess_001",
    )
    await metrics_store.record_investigation(inv)

    investigations = await metrics_store.list_investigations(limit=10)
    assert len(investigations) == 1
    assert investigations[0]["investigation_id"] == "inv_test001"


@pytest.mark.asyncio
async def test_update_investigation_outcome(metrics_store: MetricsStore):
    """Should update retroactive fields."""
    inv = Investigation(
        investigation_id="inv_test002",
        service_name="payment-service",
        dedup_key="payment-service:TypeError:def456",
    )
    await metrics_store.record_investigation(inv)

    await metrics_store.update_investigation_outcome(
        "inv_test002",
        session_outcome="fix_pr",
        acus_consumed=4.2,
        pr_url="https://github.com/test/repo/pull/1",
    )

    investigations = await metrics_store.list_investigations(limit=10)
    assert investigations[0]["session_outcome"] == "fix_pr"
    assert investigations[0]["acus_consumed"] == 4.2


@pytest.mark.asyncio
async def test_summary_aggregation(metrics_store: MetricsStore):
    """Should aggregate metrics correctly."""
    now = datetime.utcnow()

    for i in range(5):
        inv = Investigation(
            investigation_id=f"inv_agg_{i}",
            service_name="payment-service",
            dedup_key=f"key_{i}",
            triage_classification="CODE_LEVEL",
            triage_confidence=0.85,
            session_id=f"sess_{i}",
            created_at=now - timedelta(hours=i),
        )
        await metrics_store.record_investigation(inv)

    # Update some outcomes
    await metrics_store.update_investigation_outcome(
        "inv_agg_0", session_outcome="fix_pr", acus_consumed=3.0,
    )
    await metrics_store.update_investigation_outcome(
        "inv_agg_1", session_outcome="hypothesis", acus_consumed=4.0,
    )
    await metrics_store.update_investigation_outcome(
        "inv_agg_2", session_outcome="inconclusive", acus_consumed=8.0,
    )

    summary = await metrics_store.get_summary(now - timedelta(days=1), now + timedelta(hours=1))
    assert summary["total_investigations"] == 5
    assert summary["outcomes"]["fix_pr"] == 1
    assert summary["outcomes"]["hypothesis"] == 1
    assert summary["outcomes"]["inconclusive"] == 1
    assert summary["total_acus"] == 15.0


@pytest.mark.asyncio
async def test_service_success_rate(metrics_store: MetricsStore):
    """Should calculate service success rate correctly."""
    now = datetime.utcnow()

    outcomes = ["fix_pr", "fix_pr", "hypothesis", "inconclusive", "false_dispatch"]
    for i, outcome in enumerate(outcomes):
        inv = Investigation(
            investigation_id=f"inv_rate_{i}",
            service_name="payment-service",
            dedup_key=f"rate_key_{i}",
            created_at=now,
        )
        await metrics_store.record_investigation(inv)
        await metrics_store.update_investigation_outcome(f"inv_rate_{i}", session_outcome=outcome)

    result = await metrics_store.get_service_success_rate("payment-service")
    assert result["total_investigations"] == 5
    assert result["successful_investigations"] == 3  # fix_pr + fix_pr + hypothesis
    assert result["success_rate"] == 0.6
