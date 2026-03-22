"""Structured prompt builder for Devin sessions.

Assembles a dynamic prompt from enrichment data that tells Devin WHAT to
investigate, not HOW to investigate. The prompt follows a rigid structure
designed to maximize Devin's investigation success rate.
"""

from app.models.alert import AlertEvent, EnrichedContext


def build_investigation_prompt(
    alert: AlertEvent,
    context: EnrichedContext,
    investigation_id: str,
) -> str:
    """Build a structured investigation prompt for a Devin session.

    The prompt narrows Devin's search space with enriched context while
    leaving the actual diagnosis to Devin's autonomous reasoning.
    """
    # Format recent commits
    commits_section = "No recent deploys found."
    if context.recent_commits:
        lines = []
        for c in context.recent_commits[:5]:
            lines.append(f'- {c["sha"]} "{c["message"]}" ({c.get("date", "?")}, @{c["author"]})')
        commits_section = "\n".join(lines)

    # Format Sentry context
    sentry_section = "No Sentry data available."
    if context.sentry_error_details:
        sd = context.sentry_error_details
        sentry_section = (
            f"- Issue: {sd.get('title', 'N/A')}\n"
            f"- First seen: {sd.get('first_seen', 'N/A')}\n"
            f"- Last seen: {sd.get('last_seen', 'N/A')}\n"
            f"- Occurrences: {sd.get('count', 'N/A')}\n"
            f"- Level: {sd.get('level', 'N/A')}"
        )

    # Format stack trace
    stack_section = "No stack trace available."
    if alert.stack_trace:
        stack_section = alert.stack_trace

    # Build the full prompt
    prompt = f"""INCIDENT INVESTIGATION
============================
INVESTIGATION ID: {investigation_id}
SERVICE: {alert.service_name}
REPO: {context.repo_url or 'unknown'} (branch: {context.branch})
SEVERITY: {alert.severity}

ERROR SUMMARY:
{alert.error_class}: {alert.error_message}

STACK TRACE:
{stack_section}

RECENT DEPLOYS (last 48h):
{commits_section}

SENTRY CONTEXT:
{sentry_section}

INSTRUCTIONS:
1. Clone the repo and check out the {context.branch} branch.
2. Navigate to the files referenced in the stack trace and read the surrounding context.
3. Examine recent commits — prioritize those that correlate with when the error first appeared.
4. Check for interactions between recent changes
   (e.g., caching + retry logic, config changes + code paths).
5. Formulate a root cause hypothesis.
6. If you can identify the bug with confidence, write a fix.
7. Run the existing test suite to verify your fix passes.
8. If tests pass, open a PR with your fix and a detailed root cause description in the PR body.
   Title format: [INCIDENT-{investigation_id}] Fix: <one-line description>
9. If you CANNOT identify the issue confidently, document:
   - What you examined
   - What you ruled out
   - What further investigation you recommend
   DO NOT open a PR if you are uncertain — a wrong fix is worse than no fix.
"""
    return prompt


def build_knowledge_note(service_name: str) -> str:
    """Build a knowledge note with codebase conventions.

    In production, this would be loaded from a per-service config file.
    For the demo, returns the payment-service conventions.
    """
    # This would come from a config file or knowledge API in production
    knowledge_notes: dict[str, str] = {
        "payment-service": (
            "KNOWLEDGE NOTE: payment-service conventions\n"
            "- Error handling: Use AppError class (src/errors.ts).\n"
            "- Null safety: Cache lookups may return null during TTL refresh.\n"
            "- Testing: npm test (unit), npm run test:integration (integration).\n"
            "- PR format: [INCIDENT-{id}] Fix: <description>.\n"
            "- Code style: Strict TS, no-explicit-any, use optional chaining."
        ),
    }

    return knowledge_notes.get(
        service_name,
        f"KNOWLEDGE NOTE: {service_name}\nNo specific conventions documented for this service.",
    )
