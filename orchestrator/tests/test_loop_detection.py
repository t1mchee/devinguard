"""Tests for loop detection heuristics."""

from datetime import datetime, timedelta

from app.session.loop_detection import LoopDetector, LoopSignal, SessionSnapshot


def _make_snapshot(
    commands: list[str] | None = None,
    files_read: list[str] | None = None,
    files_modified: list[str] | None = None,
    hypotheses: list[str] | None = None,
    timestamp: datetime | None = None,
) -> SessionSnapshot:
    return SessionSnapshot(
        timestamp=timestamp or datetime.utcnow(),
        commands_executed=commands or [],
        files_read=files_read or [],
        files_modified=files_modified or [],
        hypotheses_stated=hypotheses or [],
    )


def test_normal_session_no_signal():
    """A sequence of varied snapshots should all return NORMAL."""
    detector = LoopDetector()
    now = datetime.utcnow()

    s1 = _make_snapshot(commands=["git clone repo"], timestamp=now)
    s2 = _make_snapshot(
        commands=["cat src/handler.ts"],
        files_read=["src/handler.ts"],
        timestamp=now + timedelta(seconds=15),
    )
    s3 = _make_snapshot(
        commands=["git log --oneline"],
        files_read=["src/service.ts"],
        timestamp=now + timedelta(seconds=30),
    )

    assert detector.analyze(s1) == LoopSignal.NORMAL
    assert detector.analyze(s2) == LoopSignal.NORMAL
    assert detector.analyze(s3) == LoopSignal.NORMAL


def test_command_repetition_triggers_redirect():
    """Same command 3 times in 2 minutes should trigger REDIRECT."""
    detector = LoopDetector(command_repeat_threshold=3, command_repeat_window_seconds=120)
    now = datetime.utcnow()

    for i in range(3):
        snap = _make_snapshot(
            commands=["npm test"],
            timestamp=now + timedelta(seconds=i * 10),
        )
        signal = detector.analyze(snap)

    assert signal == LoopSignal.REDIRECT
    assert detector.redirect_count == 1


def test_file_reread_triggers_redirect():
    """Same file read 3 times without modification should trigger REDIRECT."""
    detector = LoopDetector(file_reread_threshold=3)
    now = datetime.utcnow()

    for i in range(3):
        snap = _make_snapshot(
            files_read=["src/handler.ts"],
            commands=[f"cat src/handler.ts  # attempt {i}"],
            timestamp=now + timedelta(seconds=i * 10),
        )
        signal = detector.analyze(snap)

    assert signal == LoopSignal.REDIRECT


def test_stall_triggers_redirect():
    """5 minutes with no new artifacts should trigger REDIRECT."""
    detector = LoopDetector(stall_threshold_seconds=300)
    now = datetime.utcnow()

    # First snapshot is productive
    s1 = _make_snapshot(commands=["git clone repo"], timestamp=now)
    assert detector.analyze(s1) == LoopSignal.NORMAL

    # Stalled snapshot 6 minutes later
    s2 = _make_snapshot(timestamp=now + timedelta(minutes=6))
    signal = detector.analyze(s2)
    assert signal == LoopSignal.REDIRECT


def test_redirect_then_recovery():
    """After a REDIRECT, a productive snapshot outside the repeat window should return NORMAL."""
    detector = LoopDetector(command_repeat_threshold=3, command_repeat_window_seconds=120)
    now = datetime.utcnow()

    # Trigger redirect
    for i in range(3):
        snap = _make_snapshot(
            commands=["npm test"],
            timestamp=now + timedelta(seconds=i * 10),
        )
        detector.analyze(snap)

    # Recovery — different command, outside the 120s command repeat window
    recovery = _make_snapshot(
        commands=["git diff HEAD~1"],
        files_modified=["src/handler.ts"],
        timestamp=now + timedelta(seconds=150),
    )
    signal = detector.analyze(recovery)
    assert signal == LoopSignal.NORMAL


def test_multiple_redirects_then_terminate():
    """After max_redirects (2), the next trigger should TERMINATE."""
    detector = LoopDetector(
        command_repeat_threshold=3,
        command_repeat_window_seconds=300,
        max_redirects=2,
    )
    now = datetime.utcnow()

    # Trigger redirect #1
    for i in range(3):
        snap = _make_snapshot(commands=["npm test"], timestamp=now + timedelta(seconds=i * 5))
        detector.analyze(snap)

    assert detector.redirect_count == 1

    # Trigger redirect #2
    for i in range(3):
        snap = _make_snapshot(
            commands=["npm test"],
            timestamp=now + timedelta(seconds=30 + i * 5),
        )
        detector.analyze(snap)

    assert detector.redirect_count == 2

    # Trigger #3 should be TERMINATE
    for i in range(3):
        snap = _make_snapshot(
            commands=["npm test"],
            timestamp=now + timedelta(seconds=60 + i * 5),
        )
        signal = detector.analyze(snap)

    assert signal == LoopSignal.TERMINATE


def test_command_normalization():
    """Commands with different PIDs/timestamps should be treated as repeats."""
    detector = LoopDetector(command_repeat_threshold=3, command_repeat_window_seconds=120)
    now = datetime.utcnow()

    commands = [
        "kill 12345 && npm test",
        "kill 67890 && npm test",
        "kill 11111 && npm test",
    ]

    for i, cmd in enumerate(commands):
        snap = _make_snapshot(
            commands=[cmd],
            timestamp=now + timedelta(seconds=i * 10),
        )
        signal = detector.analyze(snap)

    assert signal == LoopSignal.REDIRECT
