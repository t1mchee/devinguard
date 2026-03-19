"""Stack trace fingerprinting and dedup key generation.

Fingerprints are computed from the top frames of a stack trace, stripping
line numbers so that the same bug triggered from slightly different code
paths produces the same fingerprint.
"""

import hashlib
import re
from typing import Optional

from app.models.alert import AlertEvent

# Patterns for extracting file:function from common stack trace formats
# JavaScript/TypeScript: "    at functionName (file.ts:123:45)"
_JS_FRAME_RE = re.compile(r"at\s+(\S+)\s+\(([^:]+):\d+:\d+\)")
# Python: '  File "file.py", line 123, in function_name'
_PY_FRAME_RE = re.compile(r'File\s+"([^"]+)",\s+line\s+\d+,\s+in\s+(\S+)')
# Generic fallback: "file.ext:123" or "file.ext:123:45"
_GENERIC_FRAME_RE = re.compile(r"([a-zA-Z0-9_./\\-]+\.\w+):\d+")

MAX_FRAMES = 5


def _parse_frames(stack_trace: str) -> list[str]:
    """Extract (file, function) pairs from a stack trace string.

    Returns normalized frame strings like "file.ts:functionName".
    Tries JS/TS format first, then Python, then generic.
    """
    frames: list[str] = []

    # Try JS/TS format
    js_matches = _JS_FRAME_RE.findall(stack_trace)
    if js_matches:
        for func, filepath in js_matches:
            frames.append(f"{filepath}:{func}")
        return frames[:MAX_FRAMES]

    # Try Python format
    py_matches = _PY_FRAME_RE.findall(stack_trace)
    if py_matches:
        for filepath, func in py_matches:
            frames.append(f"{filepath}:{func}")
        return frames[:MAX_FRAMES]

    # Generic fallback — just extract file references
    generic_matches = _GENERIC_FRAME_RE.findall(stack_trace)
    if generic_matches:
        for filepath in generic_matches:
            frames.append(filepath)
        return frames[:MAX_FRAMES]

    return frames


def compute_stack_trace_fingerprint(stack_trace: Optional[str]) -> str:
    """Compute a deterministic fingerprint from a stack trace.

    The fingerprint is based on the top 5 frames (file + function name),
    with line numbers stripped. This means the same bug triggered from
    different request paths but hitting the same code produces the same
    fingerprint.

    Returns:
        A 16-character hex string, or "no_trace" if no stack trace.
    """
    if not stack_trace or not stack_trace.strip():
        return "no_trace"

    frames = _parse_frames(stack_trace)
    if not frames:
        return "no_trace"

    combined = "|".join(frames)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def _normalize_error_message(message: str) -> str:
    """Normalize an error message for use as a fallback fingerprint component."""
    normalized = message.lower().strip()
    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized)
    # Truncate to 100 chars
    return normalized[:100]


def generate_dedup_key(alert: AlertEvent) -> str:
    """Generate a deduplication key for an alert.

    Composite key: (service_name, error_class, stack_trace_fingerprint).
    If no stack trace, falls back to normalized error message.

    Side effect: sets alert.dedup_key and alert.stack_trace_fingerprint.
    """
    if alert.stack_trace:
        fingerprint = compute_stack_trace_fingerprint(alert.stack_trace)
    else:
        fingerprint = hashlib.sha256(
            _normalize_error_message(alert.error_message).encode()
        ).hexdigest()[:16]

    alert.stack_trace_fingerprint = fingerprint
    dedup_key = f"{alert.service_name}:{alert.error_class}:{fingerprint}"
    alert.dedup_key = dedup_key
    return dedup_key
