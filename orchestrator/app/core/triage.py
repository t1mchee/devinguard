"""Triage classifier — decides whether an alert should go to Devin or a human SRE.

Two-stage classification:
1. Rule-based fast-path: deterministic rules handle ~70% of alerts with high confidence.
2. LLM-assisted ambiguous resolution: Claude Haiku evaluates enriched context for unclear cases.

Routing thresholds:
- CODE_LEVEL with confidence >= 0.8 → dispatch to Devin
- INFRASTRUCTURE at any confidence → route to human SRE
- AMBIGUOUS or CODE_LEVEL below 0.8 → route to human with enriched context
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from app.models.alert import AlertEvent, EnrichedContext

if TYPE_CHECKING:
    import anthropic

logger = logging.getLogger(__name__)


class TriageResult(BaseModel):
    """Result of triage classification."""

    classification: str  # CODE_LEVEL, INFRASTRUCTURE, AMBIGUOUS
    confidence: float  # 0.0 - 1.0
    reasoning: str
    should_dispatch_to_devin: bool


# Stage 1: Rule-based fast-path patterns
_INFRA_PATTERNS = [
    (re.compile(r"OOMKilled|out of memory|memory limit", re.I), "INFRASTRUCTURE", 0.95,
     "Memory/OOM issue — requires scaling, not code changes"),
    (re.compile(r"disk full|no space left|inode exhaustion", re.I), "INFRASTRUCTURE", 0.95,
     "Disk space issue — storage provisioning needed"),
    (re.compile(r"connection refused|ECONNREFUSED|dns.*fail", re.I), "INFRASTRUCTURE", 0.90,
     "Network/DNS failure — service discovery or connectivity issue"),
    (re.compile(r"certificate.*expired|ssl.*error|tls.*handshake", re.I), "INFRASTRUCTURE", 0.85,
     "TLS/certificate issue — cert renewal needed"),
]

_CODE_PATTERNS = [
    (re.compile(r"TypeError|ReferenceError|null pointer|NullPointerException", re.I),
     "CODE_LEVEL", 0.85, "Classic application bug with clear error type"),
    (re.compile(r"AssertionError|assertion.*fail|validation.*fail", re.I),
     "CODE_LEVEL", 0.80, "Logic error likely traceable in source"),
    (re.compile(r"HTTP\s*500.*stack\s*trace|Internal Server Error.*at\s+", re.I),
     "CODE_LEVEL", 0.80, "Server-side application error with stack trace"),
    (re.compile(r"SyntaxError|IndentationError|ParseError", re.I),
     "CODE_LEVEL", 0.90, "Syntax-level code error"),
    (re.compile(r"ImportError|ModuleNotFoundError|Cannot find module", re.I),
     "CODE_LEVEL", 0.85, "Missing import/module — likely code or dependency issue"),
]


def _rule_based_classify(alert: AlertEvent) -> Optional[TriageResult]:
    """Stage 1: Attempt rule-based classification.

    Returns a TriageResult if a rule matches, None if the alert is ambiguous.
    """
    text_to_check = f"{alert.error_class} {alert.error_message} {alert.stack_trace or ''}"

    # Check infrastructure patterns first (higher priority — we don't want to waste ACUs)
    for pattern, classification, confidence, reasoning in _INFRA_PATTERNS:
        if pattern.search(text_to_check):
            return TriageResult(
                classification=classification,
                confidence=confidence,
                reasoning=reasoning,
                should_dispatch_to_devin=False,
            )

    # Check code-level patterns
    for pattern, classification, confidence, reasoning in _CODE_PATTERNS:
        if pattern.search(text_to_check):
            should_dispatch = confidence >= 0.8
            return TriageResult(
                classification=classification,
                confidence=confidence,
                reasoning=reasoning,
                should_dispatch_to_devin=should_dispatch,
            )

    return None


def _build_llm_prompt(alert: AlertEvent, context: Optional[EnrichedContext]) -> str:
    """Build the triage prompt for Claude Haiku."""
    has_stack_trace = "yes" if alert.stack_trace else "no"
    deploy_count = len(context.recent_commits) if context else 0
    # Simple heuristic for deploy correlation
    deploy_correlated = "yes" if deploy_count > 0 else "unknown"

    return f"""You are classifying a production alert for routing.
Alert: {alert.error_message}
Error class: {alert.error_class}
Stack trace present: {has_stack_trace}
Recent deploys (last 48h): {deploy_count} commits
Error correlates with deploy timing: {deploy_correlated}
Service: {alert.service_name}

Classify as one of:
- CODE_LEVEL (application bug, likely fixable by reading source code)
- INFRASTRUCTURE (scaling, resources, network, config)
- AMBIGUOUS (insufficient signal to classify)

Respond with JSON only: {{"classification": "...", "confidence": 0.0-1.0, "reasoning": "..."}}"""


async def _llm_classify(
    alert: AlertEvent,
    context: Optional[EnrichedContext],
    anthropic_client: anthropic.AsyncAnthropic,
) -> TriageResult:
    """Stage 2: LLM-assisted classification for ambiguous cases."""
    prompt = _build_llm_prompt(alert, context)

    try:
        response = await anthropic_client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Parse JSON response
        # Handle potential markdown code blocks
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        classification = result.get("classification", "AMBIGUOUS")
        confidence = float(result.get("confidence", 0.5))
        reasoning = result.get("reasoning", "LLM classification")

        should_dispatch = classification == "CODE_LEVEL" and confidence >= 0.8

        return TriageResult(
            classification=classification,
            confidence=confidence,
            reasoning=reasoning,
            should_dispatch_to_devin=should_dispatch,
        )

    except Exception as e:
        logger.error(f"LLM triage failed: {e}")
        # On LLM failure, default to AMBIGUOUS — route to human
        return TriageResult(
            classification="AMBIGUOUS",
            confidence=0.0,
            reasoning=f"LLM classification failed: {e}",
            should_dispatch_to_devin=False,
        )


async def classify_alert(
    alert: AlertEvent,
    context: Optional[EnrichedContext] = None,
    anthropic_client: Optional[anthropic.AsyncAnthropic] = None,
) -> TriageResult:
    """Classify an alert through the two-stage triage pipeline.

    Stage 1: Rule-based fast-path (handles ~70% of alerts).
    Stage 2: LLM-assisted classification for ambiguous cases.

    Args:
        alert: The normalized alert to classify.
        context: Optional enriched context for better classification.
        anthropic_client: Optional Anthropic client for Stage 2. If None, ambiguous
                         alerts are routed to human by default.

    Returns:
        TriageResult with classification, confidence, and dispatch decision.
    """
    # Stage 1: Rule-based
    result = _rule_based_classify(alert)
    if result is not None:
        logger.info(
            f"Triage (rule-based): {alert.service_name} → "
            f"{result.classification} ({result.confidence:.2f}) — {result.reasoning}"
        )
        return result

    # Stage 2: LLM-assisted
    if anthropic_client is not None:
        result = await _llm_classify(alert, context, anthropic_client)
        logger.info(
            f"Triage (LLM): {alert.service_name} → "
            f"{result.classification} ({result.confidence:.2f}) — {result.reasoning}"
        )
        return result

    # Fallback: no LLM available, route to human
    logger.info(f"Triage (fallback): {alert.service_name} → AMBIGUOUS (no LLM available)")
    return TriageResult(
        classification="AMBIGUOUS",
        confidence=0.0,
        reasoning="No LLM available for ambiguous case classification",
        should_dispatch_to_devin=False,
    )
