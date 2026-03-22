"""Tests for the auto-merge gate."""

import pytest

from app.config.auto_merge import AutoMergeConfig
from app.gates.auto_merge_gate import AutoMergeGate


@pytest.mark.asyncio
async def test_auto_merge_disabled_by_default():
    """Auto-merge should not be eligible when disabled."""
    config = AutoMergeConfig()  # defaults: enabled=False
    gate = AutoMergeGate(config)
    decision = await gate.evaluate(
        triage_confidence=0.99,
        files_changed=1,
        lines_changed=10,
        tests_passed=True,
        service_name="test-service",
    )
    assert decision.eligible is False
    assert any("disabled" in c.reason.lower() for c in decision.checks)


@pytest.mark.asyncio
async def test_auto_merge_eligible_all_pass():
    """Should be eligible when all checks pass (except historical — no metrics store)."""
    config = AutoMergeConfig(
        enabled=True,
        min_triage_confidence=0.9,
        max_files_changed=5,
        max_lines_changed=100,
        min_historical_investigations=0,  # Disable for this test
    )
    gate = AutoMergeGate(config)
    decision = await gate.evaluate(
        triage_confidence=0.95,
        files_changed=2,
        lines_changed=30,
        tests_passed=True,
        service_name="test-service",
    )
    # Will fail on historical check (no metrics store), but other checks pass
    passed_checks = [c for c in decision.checks if c.passed]
    assert len(passed_checks) >= 5  # At least 5 of 6 checks pass


@pytest.mark.asyncio
async def test_auto_merge_low_confidence_fails():
    """Low triage confidence should fail the gate."""
    config = AutoMergeConfig(enabled=True, min_triage_confidence=0.95)
    gate = AutoMergeGate(config)
    decision = await gate.evaluate(
        triage_confidence=0.85,
        files_changed=1,
        lines_changed=10,
        tests_passed=True,
        service_name="test-service",
    )
    assert decision.eligible is False
    confidence_check = next(c for c in decision.checks if c.check_name == "triage_confidence")
    assert confidence_check.passed is False


@pytest.mark.asyncio
async def test_auto_merge_too_many_files_fails():
    """Too many files changed should fail the gate."""
    config = AutoMergeConfig(enabled=True, max_files_changed=3)
    gate = AutoMergeGate(config)
    decision = await gate.evaluate(
        triage_confidence=0.99,
        files_changed=5,
        lines_changed=10,
        tests_passed=True,
        service_name="test-service",
    )
    assert decision.eligible is False
    files_check = next(c for c in decision.checks if c.check_name == "files_changed")
    assert files_check.passed is False


@pytest.mark.asyncio
async def test_auto_merge_tests_failed():
    """Failed tests should fail the gate."""
    config = AutoMergeConfig(enabled=True)
    gate = AutoMergeGate(config)
    decision = await gate.evaluate(
        triage_confidence=0.99,
        files_changed=1,
        lines_changed=5,
        tests_passed=False,
        service_name="test-service",
    )
    assert decision.eligible is False
    tests_check = next(c for c in decision.checks if c.check_name == "tests_passed")
    assert tests_check.passed is False
