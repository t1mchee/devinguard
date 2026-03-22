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
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class TriageResult(BaseModel):
    """Result of triage classification."""

    classification: str  # CODE_LEVEL, INFRASTRUCTURE, AMBIGUOUS
    confidence: float  # 0.0 - 1.0
    reasoning: str
    should_dispatch_to_devin: bool


# Stage 1: Rule-based fast-path patterns
#
# Two tiers:
#   Tier 1 — Explicit error classes (high confidence, narrow match)
#   Tier 2 — Contextual signals from message text (moderate confidence, broader match)

_INFRA_PATTERNS = [
    # Tier 1: Explicit error classes
    (re.compile(r"OOMKilled|out of memory|memory limit|MemoryError|OutOfMemoryError", re.I),
     "INFRASTRUCTURE", 0.95, "Memory/OOM issue — requires scaling, not code changes"),
    (re.compile(r"disk full|no space left|inode exhaustion|ENOSPC", re.I),
     "INFRASTRUCTURE", 0.95, "Disk space issue — storage provisioning needed"),
    (re.compile(r"connection refused|ECONNREFUSED|dns.*fail|ENOTFOUND", re.I),
     "INFRASTRUCTURE", 0.90, "Network/DNS failure — service discovery or connectivity issue"),
    (re.compile(r"certificate.*expired|ssl.*error|tls.*handshake|CertificateError", re.I),
     "INFRASTRUCTURE", 0.85, "TLS/certificate issue — cert renewal needed"),
    # Tier 2: Contextual infra signals
    (re.compile(r"kubelet|kube-proxy|cgroup|node\s+pressure|evict", re.I),
     "INFRASTRUCTURE", 0.85, "Kubernetes node/kubelet infrastructure issue"),
    (re.compile(r"pod.*restart|CrashLoopBackOff|ImagePullBackOff|pod.*status", re.I),
     "INFRASTRUCTURE", 0.85, "Kubernetes pod lifecycle issue"),
    (re.compile(r"resource\s*(?:accounting|quota|limit)|cpu\s*(?:manager|set|throttl)", re.I),
     "INFRASTRUCTURE", 0.80, "Resource management/scheduling issue"),
    (re.compile(r"volume.*mount|persistent.*volume|storage.*class|PVC", re.I),
     "INFRASTRUCTURE", 0.80, "Storage/volume provisioning issue"),
    (re.compile(r"docker|container.*runtime|containerd|runc", re.I),
     "INFRASTRUCTURE", 0.80, "Container runtime infrastructure issue"),
    (re.compile(r"terraform|provisioning|infra.*config|cloud.*config", re.I),
     "INFRASTRUCTURE", 0.80, "Infrastructure-as-code / provisioning issue"),
    (re.compile(r"scaling|autoscal|replica.*set|horizontal.*pod|HPA", re.I),
     "INFRASTRUCTURE", 0.80, "Auto-scaling infrastructure issue"),
    (re.compile(r"network.*polic|ingress.*controller|load\s*balancer|proxy.*error", re.I),
     "INFRASTRUCTURE", 0.80, "Network/ingress infrastructure issue"),
    (re.compile(r"liveness.*probe|readiness.*probe|health.*check.*fail", re.I),
     "INFRASTRUCTURE", 0.80, "Health check / probe infrastructure issue"),
    (re.compile(r"service\s*mesh|sidecar|envoy|istio", re.I),
     "INFRASTRUCTURE", 0.80, "Service mesh infrastructure issue"),
    (re.compile(
        r"deploy.*(?:fail|crash|error|pipeline)"
        r"|rollout.*(?:fail|stuck)|rollback.*fail|canary.*fail",
        re.I,
    ), "INFRASTRUCTURE", 0.75, "Deployment/rollout infrastructure issue"),
    (re.compile(
        r"(?:request|connection|network)\s*(?:timeout|timed?\s*out)"
        r"|deadline exceeded|ETIMEDOUT",
        re.I,
    ), "INFRASTRUCTURE", 0.75, "Timeout — likely network or resource constraint"),
]

_CODE_PATTERNS = [
    # Tier 1: Explicit error classes
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
    (re.compile(r"AttributeError|KeyError|IndexError|ValueError", re.I),
     "CODE_LEVEL", 0.85, "Python runtime error — code-level bug"),
    (re.compile(r"NameError|UnboundLocalError|RecursionError", re.I),
     "CODE_LEVEL", 0.85, "Python scope/recursion error — code-level bug"),
    (re.compile(r"NoMethodError|ArgumentError|NameError", re.I),
     "CODE_LEVEL", 0.80, "Runtime method/argument error — code-level bug"),
    # Tier 2: Contextual code signals
    (re.compile(
        r"(?:fix|bug|patch)\s+(?:in|for|where)?\s*"
        r"(?:crash|throw|error|exception)\s+(?:in|at|from|when)",
        re.I,
    ), "CODE_LEVEL", 0.75, "Bug-fix context — likely application code issue"),
    (re.compile(
        r"(?:crash|throw|exception)\s+(?:when|if|during|after)"
        r"\s+(?:call|invok|pars|send|receiv|process|handl|rend)",
        re.I,
    ), "CODE_LEVEL", 0.75, "Conditional error — application-level bug pattern"),
    (re.compile(
        r"(?:wrong|incorrect|unexpected|invalid)"
        r"\s+(?:result|output|value|response|behavior)",
        re.I,
    ), "CODE_LEVEL", 0.75, "Incorrect behavior — logic bug in application code"),
    (re.compile(
        r"(?:null|nil|undefined|None)"
        r"\s+(?:check|reference|pointer|dereference|access)",
        re.I,
    ), "CODE_LEVEL", 0.80, "Null reference — code-level bug"),
    (re.compile(r"(?:race\s*condition|deadlock|concurrency)\s*(?:bug|issue|error|fix)", re.I),
     "CODE_LEVEL", 0.80, "Concurrency bug in application code"),
    (re.compile(r"(?:regression|broke|breaking)\s+(?:change|behavior|test|feature)", re.I),
     "CODE_LEVEL", 0.75, "Regression — code change introduced a bug"),
    (re.compile(r"(?:panic|segfault|SIGSEGV|abort|core dump)", re.I),
     "CODE_LEVEL", 0.80, "Process crash — likely code-level bug"),
    (re.compile(r"(?:off.by.one|overflow|underflow|truncat|round)", re.I),
     "CODE_LEVEL", 0.75, "Numeric/boundary error — code-level bug"),
    (re.compile(r"(?:missing|forgot|omitted)\s+(?:null|check|validation|guard|handler)", re.I),
     "CODE_LEVEL", 0.80, "Missing guard/validation — code-level fix needed"),
    (re.compile(r"(?:response|return|output).*(?:wrong|empty|missing|malformed|corrupt)", re.I),
     "CODE_LEVEL", 0.75, "Incorrect output — application logic bug"),
    (re.compile(r"fails?\s+(?:with|when|on|during|after|for|silently)", re.I),
     "CODE_LEVEL", 0.70, "Failure condition — likely application-level bug"),
    (re.compile(
        r"(?:doesn't|does not|don't|do not)"
        r"\s+(?:work|handle|parse|validate|return|send)",
        re.I,
    ), "CODE_LEVEL", 0.70, "Missing functionality — application code issue"),
    (re.compile(r"(?:throw|throws|thrown)\s+(?:an?\s+)?(?:error|exception)", re.I),
     "CODE_LEVEL", 0.75, "Throws error — application code issue"),
    (re.compile(
        r"(?:not\s+(?:working|passing|handling|setting"
        r"|returning|called|triggered|executed))",
        re.I,
    ), "CODE_LEVEL", 0.70, "Broken behavior — application code issue"),
    (re.compile(r"(?:crash|crashes|crashed|crashing)\s", re.I),
     "CODE_LEVEL", 0.75, "Application crash — code-level bug"),
    (re.compile(r"(?:undefined|null|nil|None)\b.*(?:error|exception|crash|fail)", re.I),
     "CODE_LEVEL", 0.80, "Null/undefined causing error — code-level bug"),
    (re.compile(
        r"(?:called|executed|invoked|triggered)"
        r"\s+(?:twice|multiple|again|before|after)",
        re.I,
    ), "CODE_LEVEL", 0.75, "Incorrect execution order — code-level bug"),
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
    openai_client: AsyncOpenAI,
) -> TriageResult:
    """Stage 2: LLM-assisted classification for ambiguous cases."""
    prompt = _build_llm_prompt(alert, context)

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=256,
            messages=[
                {"role": "system", "content": "You are a production alert classifier."},
                {"role": "user", "content": prompt},
            ],
        )
        text = (response.choices[0].message.content or "").strip()

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
    openai_client: Optional[AsyncOpenAI] = None,
) -> TriageResult:
    """Classify an alert through the two-stage triage pipeline.

    Stage 1: Rule-based fast-path (handles ~70% of alerts).
    Stage 2: LLM-assisted classification for ambiguous cases.

    Args:
        alert: The normalized alert to classify.
        context: Optional enriched context for better classification.
        openai_client: Optional OpenAI client for Stage 2. If None, ambiguous
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

    # Stage 2: LLM-assisted (OpenAI)
    if openai_client is not None:
        result = await _llm_classify(alert, context, openai_client)
        logger.info(
            f"Triage (LLM): {alert.service_name} → "
            f"{result.classification} ({result.confidence:.2f}) — {result.reasoning}"
        )
        return result

    # Fallback: no LLM available, route to human
    logger.info(
        f"Triage (fallback): {alert.service_name} → AMBIGUOUS (no LLM available)"
    )
    return TriageResult(
        classification="AMBIGUOUS",
        confidence=0.0,
        reasoning="No LLM available for ambiguous case classification",
        should_dispatch_to_devin=False,
    )
