"""Loop detection heuristics for Devin sessions.

Monitors session progress for signs of unproductive behavior:
1. Command repetition — same command executed multiple times
2. File re-reading — same file read repeatedly without modifications
3. Stall — no new artifacts (commands, edits, hypotheses) for extended period

Each heuristic has configurable thresholds. On trigger, the system first
redirects Devin (up to max_redirects), then terminates if the loop persists.
"""

import logging
import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SessionSnapshot(BaseModel):
    """A point-in-time view of what Devin is doing, extracted from the session poll response."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    commands_executed: list[str] = Field(default_factory=list)
    files_read: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    hypotheses_stated: list[str] = Field(default_factory=list)
    pr_opened: bool = False
    session_output_tail: str = ""


class LoopSignal(str, Enum):
    NORMAL = "normal"
    REDIRECT = "redirect"
    TERMINATE = "terminate"


# Patterns for extracting hypotheses from Devin's output
_HYPOTHESIS_PATTERNS = [
    re.compile(r"(?i)root cause:(.+?)(?:\n|$)"),
    re.compile(r"(?i)hypothesis:(.+?)(?:\n|$)"),
    re.compile(r"(?i)I believe the issue is(.+?)(?:\n|$)"),
    re.compile(r"(?i)the bug is(.+?)(?:\n|$)"),
]

# Patterns to strip variable parts from commands for comparison
_VARIABLE_PARTS = re.compile(r"\b\d{4,}\b")  # PIDs, timestamps, etc.


def _normalize_command(cmd: str) -> str:
    """Normalize a command for comparison by stripping variable parts."""
    return _VARIABLE_PARTS.sub("NUM", cmd.strip())


def extract_snapshot(
    session_response: dict,
    previous_snapshot: Optional[SessionSnapshot] = None,
) -> SessionSnapshot:
    """Extract a SessionSnapshot from a Devin API session response.

    Parses the session's structured output to determine what Devin has done
    since the last snapshot.
    """
    structured = session_response.get("structured_output", {}) or {}
    # Extract commands from structured output
    commands = []
    steps = structured.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                cmd = step.get("command", step.get("shell_command", ""))
                if cmd:
                    commands.append(cmd)

    # Extract files read/modified
    files_read = []
    files_modified = []
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            action = step.get("action", "")
            filepath = step.get("file", step.get("path", ""))
            if filepath:
                if action in ("read", "open", "view"):
                    files_read.append(filepath)
                elif action in ("edit", "write", "create"):
                    files_modified.append(filepath)

    # Extract hypotheses from output text
    hypotheses = []
    session_output = structured.get("output", "") or ""
    for pattern in _HYPOTHESIS_PATTERNS:
        matches = pattern.findall(session_output)
        hypotheses.extend(m.strip() for m in matches)

    # Check for PR
    pr_opened = bool(session_response.get("pull_requests", []))

    # Get tail of output
    output_tail = session_output[-2000:] if session_output else ""

    # If we have a previous snapshot, compute deltas
    if previous_snapshot:
        prev_cmds = set(previous_snapshot.commands_executed)
        commands = [c for c in commands if c not in prev_cmds]
        # Don't filter reads — we want to track re-reads
        prev_hypotheses = set(previous_snapshot.hypotheses_stated)
        hypotheses = [h for h in hypotheses if h not in prev_hypotheses]

    return SessionSnapshot(
        commands_executed=commands,
        files_read=files_read,
        files_modified=files_modified,
        hypotheses_stated=hypotheses,
        pr_opened=pr_opened,
        session_output_tail=output_tail,
    )


class LoopDetector:
    """Detects unproductive loops in Devin sessions.

    Uses three heuristic signals:
    - Command repetition: same command N+ times within a time window
    - File re-reading: same file read N+ times without modifications
    - Stall: no new artifacts for an extended period

    On trigger, returns REDIRECT (first/second time) or TERMINATE (after max redirects).
    """

    def __init__(
        self,
        command_repeat_threshold: int = 3,
        command_repeat_window_seconds: int = 120,
        file_reread_threshold: int = 3,
        stall_threshold_seconds: int = 300,
        max_redirects: int = 2,
    ):
        self._cmd_threshold = command_repeat_threshold
        self._cmd_window = command_repeat_window_seconds
        self._file_threshold = file_reread_threshold
        self._stall_threshold = stall_threshold_seconds
        self._max_redirects = max_redirects

        self._history: list[SessionSnapshot] = []
        self._redirect_count: int = 0
        self._last_trigger_reason: str = ""
        self._last_productive_time: Optional[datetime] = None

    @property
    def redirect_count(self) -> int:
        return self._redirect_count

    def get_last_trigger_reason(self) -> str:
        return self._last_trigger_reason

    def analyze(self, snapshot: SessionSnapshot) -> LoopSignal:
        """Analyze a snapshot and return the appropriate signal.

        Appends the snapshot to history, runs all three heuristic checks,
        and returns the appropriate signal.
        """
        self._history.append(snapshot)

        # Track productive activity
        is_productive = bool(
            snapshot.commands_executed
            or snapshot.files_modified
            or snapshot.hypotheses_stated
            or snapshot.pr_opened
        )
        if is_productive:
            self._last_productive_time = snapshot.timestamp

        # Initialize productive time on first snapshot
        if self._last_productive_time is None:
            self._last_productive_time = snapshot.timestamp

        # Run checks
        triggered = False
        reasons: list[str] = []

        # Check 1: Command repetition
        cmd_repeated = self._check_command_repetition(snapshot)
        if cmd_repeated:
            triggered = True
            reasons.append(cmd_repeated)

        # Check 2: File re-reading
        file_reread = self._check_file_rereading()
        if file_reread:
            triggered = True
            reasons.append(file_reread)

        # Check 3: Stall
        stall = self._check_stall(snapshot)
        if stall:
            triggered = True
            reasons.append(stall)

        if not triggered:
            return LoopSignal.NORMAL

        self._last_trigger_reason = "; ".join(reasons)

        if self._redirect_count >= self._max_redirects:
            return LoopSignal.TERMINATE

        self._redirect_count += 1
        return LoopSignal.REDIRECT

    def _check_command_repetition(self, snapshot: SessionSnapshot) -> Optional[str]:
        """Check if any command has been repeated too many times recently."""
        now = snapshot.timestamp
        recent_commands: list[str] = []

        for hist_snapshot in self._history:
            delta = (now - hist_snapshot.timestamp).total_seconds()
            if delta <= self._cmd_window:
                recent_commands.extend(
                    _normalize_command(cmd) for cmd in hist_snapshot.commands_executed
                )

        # Count occurrences
        from collections import Counter

        counts = Counter(recent_commands)
        for cmd, count in counts.items():
            if count >= self._cmd_threshold:
                return f"Command repeated {count} times in {self._cmd_window}s: '{cmd}'"
        return None

    def _check_file_rereading(self) -> Optional[str]:
        """Check if any file has been read too many times without modification."""
        # Count reads per file across all history
        read_counts: dict[str, int] = {}
        modified_files: set[str] = set()

        for snap in self._history:
            modified_files.update(snap.files_modified)
            for f in snap.files_read:
                if f not in modified_files:
                    read_counts[f] = read_counts.get(f, 0) + 1

        for filepath, count in read_counts.items():
            if count >= self._file_threshold:
                return f"File read {count} times without modification: '{filepath}'"
        return None

    def _check_stall(self, snapshot: SessionSnapshot) -> Optional[str]:
        """Check if there has been no productive activity for too long."""
        if self._last_productive_time is None:
            return None

        delta = (snapshot.timestamp - self._last_productive_time).total_seconds()
        if delta >= self._stall_threshold:
            return f"No new artifacts for {delta:.0f}s (threshold: {self._stall_threshold}s)"
        return None
