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

    # Detect if we have file location data (from code scanner)
    has_file_location = stack_section != "No stack trace available." and "at " in stack_section

    # Build the full prompt
    prompt = f"""INCIDENT INVESTIGATION
============================
INVESTIGATION ID: {investigation_id}
SERVICE: {alert.service_name}
REPO: {context.repo_url or 'unknown'} (branch: {context.branch})
SEVERITY: {alert.severity}

ERROR SUMMARY:
{alert.error_class}: {alert.error_message}

STACK TRACE / CODE LOCATION:
{stack_section}

RECENT DEPLOYS (last 48h):
{commits_section}

SENTRY CONTEXT:
{sentry_section}

INSTRUCTIONS:
1. Clone the repo and check out the {context.branch} branch.
2. Navigate to the EXACT file and line referenced above and read the surrounding context.
3. The code location above was identified by static analysis — the bug IS in that file.
   Read the file carefully and understand what the bug is.
4. Write a fix for the identified bug. The fix should be minimal and targeted.
5. If the repo has tests, run them. If not, verify the fix is syntactically correct.
6. Open a PR with your fix. Use this title format:
   [INCIDENT-{investigation_id}] Fix: <one-line description>
   Include a root cause description in the PR body.
"""
    if has_file_location:
        prompt += """
IMPORTANT: The file location and code context above come from our scanner.
The bug has been confirmed to exist at that location. You MUST open a fix PR.
Do not just document findings — write and submit the actual code fix.
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
