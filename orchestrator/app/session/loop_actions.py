"""Actions to take when loop detection triggers.

Redirect: send a structured message to the Devin session to get it back on track.
Terminate: instruct Devin to produce final output, then end the session.
"""

import asyncio
import logging

from app.core.devin_client import DevinAPIClient

logger = logging.getLogger(__name__)


async def redirect_session(client: DevinAPIClient, session_id: str, reason: str) -> None:
    """Send a redirect message to a Devin session that appears stuck.

    The message instructs Devin to either converge on a hypothesis,
    attempt a fix, or conclude the investigation.
    """
    message = (
        f"REDIRECT: You appear to be stuck. Reason: {reason}. "
        "Please take one of the following actions:\n"
        "1. If you have a hypothesis, state it clearly and attempt a fix.\n"
        "2. If you cannot identify the root cause, summarize what you've investigated "
        "and what you've ruled out, then conclude the investigation.\n"
        "3. Do NOT re-read the same files or re-run the same commands."
    )
    try:
        await client.send_message(session_id, message)
        logger.warning(f"Sent redirect to session {session_id}: {reason}")
    except Exception as e:
        logger.error(f"Failed to send redirect to session {session_id}: {e}")


async def terminate_session(
    client: DevinAPIClient, session_id: str, reason: str
) -> dict:
    """Terminate a Devin session that has not responded to redirects.

    Sends a final message asking for output, waits briefly, then retrieves
    the final session state for escalation handling.
    """
    message = (
        f"TERMINATE: Investigation is being concluded. Reason: {reason}. "
        "Please immediately output your best hypothesis and any findings, "
        "then stop working."
    )
    try:
        await client.send_message(session_id, message)
        logger.warning(f"Sent terminate to session {session_id}: {reason}")
    except Exception as e:
        logger.error(f"Failed to send terminate message to session {session_id}: {e}")

    # Wait for Devin to produce final output
    await asyncio.sleep(30)

    # Retrieve final session state
    try:
        final_state = await client.get_session(session_id)
    except Exception as e:
        logger.error(f"Failed to get final state for session {session_id}: {e}")
        final_state = {"session_id": session_id, "reason": "terminate", "error": str(e)}

    # Terminate the session
    try:
        await client.terminate_session(session_id)
    except Exception as e:
        logger.error(f"Failed to terminate session {session_id}: {e}")

    return final_state
