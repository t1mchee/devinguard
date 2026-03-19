"""Tests for alert deduplication — fingerprinting and dedup store."""

import pytest

from app.dedup.fingerprint import (
    compute_stack_trace_fingerprint,
    generate_dedup_key,
)
from app.dedup.store import InMemoryDedupStore
from app.models.alert import AlertEvent

# --- Fingerprint tests ---


def test_fingerprint_same_error_same_fingerprint():
    """Two stack traces from the same bug (same functions, different line numbers)
    should produce the same fingerprint."""
    trace1 = """    at processPayment (src/handlers/payment.ts:142:15)
    at Router.handle (src/router.ts:67:20)
    at Layer.handle (node_modules/express/lib/router/layer.js:95:5)"""

    trace2 = """    at processPayment (src/handlers/payment.ts:155:15)
    at Router.handle (src/router.ts:70:20)
    at Layer.handle (node_modules/express/lib/router/layer.js:95:5)"""

    fp1 = compute_stack_trace_fingerprint(trace1)
    fp2 = compute_stack_trace_fingerprint(trace2)
    assert fp1 == fp2
    assert len(fp1) == 16


def test_fingerprint_different_error_different_fingerprint():
    """Two different bugs should produce different fingerprints."""
    trace1 = """    at processPayment (src/handlers/payment.ts:142:15)
    at Router.handle (src/router.ts:67:20)"""

    trace2 = """    at processRefund (src/handlers/refund.ts:88:10)
    at Router.handle (src/router.ts:67:20)"""

    fp1 = compute_stack_trace_fingerprint(trace1)
    fp2 = compute_stack_trace_fingerprint(trace2)
    assert fp1 != fp2


def test_fingerprint_no_stack_trace():
    """No stack trace should return 'no_trace'."""
    assert compute_stack_trace_fingerprint(None) == "no_trace"
    assert compute_stack_trace_fingerprint("") == "no_trace"
    assert compute_stack_trace_fingerprint("   ") == "no_trace"


def test_fingerprint_python_format():
    """Python-style stack traces should be parsed correctly."""
    trace = """  File "app/handlers/payment.py", line 42, in process_payment
  File "app/services/customer.py", line 18, in get_customer
  File "app/cache/cache.py", line 5, in lookup"""

    fp = compute_stack_trace_fingerprint(trace)
    assert fp != "no_trace"
    assert len(fp) == 16


def test_dedup_key_with_stack_trace():
    """Dedup key should include service, error class, and stack trace fingerprint."""
    alert = AlertEvent(
        source="sentry",
        service_name="payment-service",
        error_class="TypeError",
        error_message="Cannot read properties of null",
        stack_trace="    at processPayment (src/handlers/payment.ts:142:15)",
    )
    key = generate_dedup_key(alert)
    assert key.startswith("payment-service:TypeError:")
    assert alert.dedup_key == key
    assert alert.stack_trace_fingerprint is not None


def test_dedup_key_without_stack_trace():
    """Dedup key should fall back to error message hash when no stack trace."""
    alert = AlertEvent(
        source="pagerduty",
        service_name="payment-service",
        error_class="TimeoutError",
        error_message="Request timed out after 30000ms",
    )
    key = generate_dedup_key(alert)
    assert key.startswith("payment-service:TimeoutError:")
    assert alert.dedup_key == key


# --- Dedup store tests ---


@pytest.mark.asyncio
async def test_dedup_first_alert_creates_investigation():
    """First alert with a key should return (False, None)."""
    store = InMemoryDedupStore(default_ttl_seconds=60)
    is_dup, existing_id = await store.check_and_set("test_key")
    assert is_dup is False
    assert existing_id is None


@pytest.mark.asyncio
async def test_dedup_second_alert_is_duplicate():
    """Second alert with same key within TTL should return (True, investigation_id)."""
    store = InMemoryDedupStore(default_ttl_seconds=60)
    await store.register_investigation("test_key", "inv_001")
    is_dup, existing_id = await store.check_and_set("test_key")
    assert is_dup is True
    assert existing_id == "inv_001"


@pytest.mark.asyncio
async def test_dedup_remove_allows_new_investigation():
    """After removing a key, a new investigation should be created."""
    store = InMemoryDedupStore(default_ttl_seconds=60)
    await store.register_investigation("test_key", "inv_001")
    await store.remove("test_key")
    is_dup, existing_id = await store.check_and_set("test_key")
    assert is_dup is False
    assert existing_id is None
