"""Dashboard API endpoints.

Provides metrics and investigation data for the operator dashboard,
including real-time activity feed via SSE and repository scanning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings
from app.events.feed import FeedEvent, activity_feed

if TYPE_CHECKING:
    from app.metrics.store import MetricsStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


def _get_metrics_store(request: Request) -> MetricsStore:
    return request.app.state.metrics_store


@router.get("/summary")
async def get_summary(
    request: Request,
    period: Literal["day", "week", "month"] = "week",
    service: Optional[str] = None,
) -> dict:
    """Current period summary metrics."""
    store = _get_metrics_store(request)
    now = datetime.utcnow()

    period_map = {"day": timedelta(days=1), "week": timedelta(weeks=1), "month": timedelta(days=30)}
    period_start = now - period_map[period]

    return await store.get_summary(period_start, now, service)


@router.get("/triage-accuracy")
async def get_triage_accuracy(
    request: Request,
    weeks: int = 12,
    service: Optional[str] = None,
) -> list[dict]:
    """Weekly triage precision/recall trend."""
    store = _get_metrics_store(request)
    return await store.get_triage_accuracy_trend(weeks, service)


@router.get("/acu-spend")
async def get_acu_spend(
    request: Request,
    days: int = 30,
    service: Optional[str] = None,
) -> list[dict]:
    """Daily ACU spend trend."""
    store = _get_metrics_store(request)
    return await store.get_acu_spend_trend(days, service)


@router.get("/outcomes")
async def get_outcome_distribution(
    request: Request,
    period: Literal["day", "week", "month"] = "week",
    service: Optional[str] = None,
) -> dict:
    """Outcome distribution (fix_pr, hypothesis, inconclusive, false_dispatch)."""
    store = _get_metrics_store(request)
    now = datetime.utcnow()

    period_map = {"day": timedelta(days=1), "week": timedelta(weeks=1), "month": timedelta(days=30)}
    period_start = now - period_map[period]

    summary = await store.get_summary(period_start, now, service)
    return summary.get("outcomes", {})


@router.get("/investigations")
async def list_investigations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    service: Optional[str] = None,
    outcome: Optional[str] = None,
) -> list[dict]:
    """Paginated list of individual investigations."""
    store = _get_metrics_store(request)
    return await store.list_investigations(limit, offset, service, outcome)


@router.post("/investigations/{investigation_id}/label")
async def label_investigation(
    request: Request,
    investigation_id: str,
    triage_was_correct: Optional[bool] = None,
    pr_merged: Optional[bool] = None,
    pr_reverted: Optional[bool] = None,
    human_investigation_time_minutes: Optional[float] = None,
) -> dict:
    """Retroactive labeling endpoint for on-call engineers.

    Allows updating investigation records with ground-truth labels
    that feed back into accuracy metrics and classifier training.
    """
    store = _get_metrics_store(request)

    kwargs: dict = {}
    if triage_was_correct is not None:
        kwargs["triage_was_correct"] = triage_was_correct
    if pr_merged is not None:
        kwargs["pr_merged"] = pr_merged
    if pr_reverted is not None:
        kwargs["pr_reverted"] = pr_reverted
    if human_investigation_time_minutes is not None:
        kwargs["human_investigation_time_minutes"] = human_investigation_time_minutes

    if not kwargs:
        return {"status": "no_updates"}

    await store.update_investigation_outcome(investigation_id, **kwargs)
    return {"status": "updated", "investigation_id": investigation_id, "updates": kwargs}


@router.get("/events")
async def get_recent_events(limit: int = 50) -> list[dict]:
    """Return recent activity feed events."""
    events = activity_feed.recent(limit)
    return [e.model_dump() for e in events]


@router.get("/events/stream")
async def event_stream(request: Request) -> StreamingResponse:
    """SSE endpoint — streams real-time pipeline events to the dashboard."""
    queue = activity_feed.subscribe()

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    data = json.dumps(event.model_dump())
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            activity_feed.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/live-investigations")
async def live_investigations(request: Request) -> list[dict]:
    """Return in-memory investigations from the dispatcher (live status)."""
    from app.api.webhooks import get_dispatcher

    dispatcher = get_dispatcher(request)
    investigations = dispatcher.list_investigations()
    result = []
    for inv in investigations:
        d = inv.model_dump()
        # Add session URL for active sessions
        if inv.session_id:
            # Strip "devin-" prefix if present for URL
            sid = inv.session_id
            if sid.startswith("devin-"):
                sid = sid[6:]
            d["session_url"] = f"https://app.devin.ai/sessions/{sid}"
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Demo trigger endpoints
# ---------------------------------------------------------------------------

_DEMO_PAYLOADS = {
    "typeerror": {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "demo-typeerror",
                "title": "TypeError: Cannot read properties of null",
                "urgency": "high",
                "service": {"name": "payment-service"},
                "body": {
                    "details": {
                        "error_class": "TypeError",
                        "error_message": "Cannot read properties of null (reading 'paymentMethodId')",
                        "stack_trace": (
                            "TypeError: Cannot read properties of null (reading 'paymentMethodId')\n"
                            "    at ChargeHandler.handle (charge-handler.ts:25)\n"
                            "    at PaymentService.processCharge (payment-service.ts:98)\n"
                            "    at Router.handle (router.ts:44)"
                        ),
                    }
                },
            },
        }
    },
    "oomkilled": {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "demo-oomkilled",
                "title": "OOMKilled: pod exceeded memory limit",
                "urgency": "high",
                "service": {"name": "api-gateway"},
                "body": {
                    "details": {
                        "error_class": "OOMKilled",
                        "error_message": "Container exceeded memory limit of 512Mi",
                    }
                },
            },
        }
    },
    "latency": {
        "event": {
            "event_type": "incident.triggered",
            "data": {
                "id": "demo-latency",
                "title": "High latency: p99 > 5s on /api/checkout",
                "urgency": "high",
                "service": {"name": "checkout-service"},
                "body": {
                    "details": {
                        "error_class": "LatencySpike",
                        "error_message": "p99 latency exceeded 5000ms on /api/checkout endpoint",
                    }
                },
            },
        }
    },
}


@router.post("/demo/trigger")
async def trigger_demo(
    request: Request,
    background_tasks: BackgroundTasks,
    scenario: str = "typeerror",
    simulate: bool = False,
) -> dict:
    """Fire a demo webhook through the pipeline.

    If simulate=true, runs a full simulated pipeline (no real Devin session)
    that walks through all stages including Fix PR Opened.
    """
    from app.api.webhooks import get_dispatcher
    from app.webhooks.normalizers import normalize_pagerduty

    payload = _DEMO_PAYLOADS.get(scenario)
    if not payload:
        return {"error": f"Unknown scenario: {scenario}", "available": list(_DEMO_PAYLOADS.keys())}

    if simulate:
        background_tasks.add_task(_run_simulated_pipeline, request, scenario, payload)
        return {"action": "simulated", "scenario": scenario, "message": "Full pipeline simulation started"}

    alert = normalize_pagerduty(payload)
    dispatcher = get_dispatcher(request)
    result = await dispatcher.handle_alert(alert)

    if result.get("action") == "dispatched_to_devin":
        investigation_id = result["investigation_id"]
        background_tasks.add_task(dispatcher.monitor_session, investigation_id)

    return result


async def _run_simulated_pipeline(
    request: Request, scenario: str, payload: dict
) -> None:
    """Simulate the full pipeline with realistic delays, emitting SSE events at each stage."""
    import uuid

    store = _get_metrics_store(request)
    inv_id = f"inv_{uuid.uuid4().hex[:12]}"
    session_id = f"devin-{uuid.uuid4().hex[:8]}"
    data = payload["event"]["data"]
    service = data["service"]["name"]
    error_class = data["body"]["details"].get("error_class", "Unknown")
    error_msg = data["body"]["details"].get("error_message", data["title"])
    now = datetime.utcnow()

    # Stage 1: Alert received (immediate)
    activity_feed.emit(FeedEvent(
        event_type="alert_received",
        investigation_id=inv_id,
        service_name=service,
        title=f"Alert received: {error_class}",
        detail=f"{error_class}: {error_msg}",
    ))

    await asyncio.sleep(2)

    # Stage 2: Triage complete
    is_code = scenario == "typeerror"
    classification = "CODE_LEVEL" if is_code else "INFRASTRUCTURE"
    confidence = 0.85 if is_code else 0.95
    activity_feed.emit(FeedEvent(
        event_type="triage_complete",
        investigation_id=inv_id,
        service_name=service,
        title=f"Triage: {classification}",
        detail=f"Confidence {confidence:.0%} — {'Classic application bug with clear error type' if is_code else 'Infrastructure issue — requires scaling, not code changes'}",
        metadata={"classification": classification, "confidence": confidence},
    ))

    if not is_code:
        # Escalate to human
        await asyncio.sleep(1)
        activity_feed.emit(FeedEvent(
            event_type="escalated",
            investigation_id=inv_id,
            service_name=service,
            title="Escalated to human",
            detail=f"{classification} — not dispatching to Devin",
        ))
        # Record in metrics store
        from app.models.alert import Investigation
        inv = Investigation(
            investigation_id=inv_id,
            service_name=service,
            dedup_key=f"sim-{inv_id}",
            triage_classification=classification,
            triage_confidence=confidence,
            created_at=now,
        )
        if store:
            await store.record_investigation(inv)
        return

    await asyncio.sleep(2)

    # Stage 3: Dispatched to Devin
    activity_feed.emit(FeedEvent(
        event_type="dispatched",
        investigation_id=inv_id,
        service_name=service,
        title="Dispatched to Devin",
        detail=f"Session {session_id}",
        metadata={"session_id": session_id},
    ))

    # Record investigation
    from app.models.alert import Investigation
    inv = Investigation(
        investigation_id=inv_id,
        service_name=service,
        dedup_key=f"sim-{inv_id}",
        triage_classification=classification,
        triage_confidence=confidence,
        session_id=session_id,
        session_url=f"https://app.devin.ai/sessions/{session_id.replace('devin-', '')}",
        created_at=now,
    )
    if store:
        await store.record_investigation(inv)

    await asyncio.sleep(3)

    # Stage 4: Investigating (session updates)
    for step_msg in [
        "Cloning repository and reading codebase",
        "Identified root cause in source file",
        "Writing fix and running tests",
    ]:
        activity_feed.emit(FeedEvent(
            event_type="session_update",
            investigation_id=inv_id,
            service_name=service,
            title="Devin investigating",
            detail=step_msg,
            metadata={"session_id": session_id},
        ))
        await asyncio.sleep(3)

    # Stage 5: PR opened
    pr_url = f"https://github.com/t1mchee/payment-service/pull/sim-{uuid.uuid4().hex[:6]}"
    activity_feed.emit(FeedEvent(
        event_type="pr_opened",
        investigation_id=inv_id,
        service_name=service,
        title="Fix PR opened",
        detail=f"Devin opened a fix PR for {error_class}",
        metadata={"session_id": session_id, "pr_url": pr_url},
    ))

    # Update investigation with PR
    if store:
        await store.update_investigation_outcome(
            inv_id,
            session_outcome="fix_pr",
            pr_url=pr_url,
            acus_consumed=2.4,
            resolved_at=datetime.utcnow(),
        )


@router.get("/demo/scenarios")
async def list_demo_scenarios() -> list[dict]:
    """List available demo scenarios."""
    scenarios = []
    for key, payload in _DEMO_PAYLOADS.items():
        data = payload["event"]["data"]
        scenarios.append({
            "id": key,
            "title": data["title"],
            "service": data["service"]["name"],
            "error_class": data["body"]["details"]["error_class"],
        })
    return scenarios


# ---------------------------------------------------------------------------
# Scan Repository — discover real bugs from a GitHub repo
# ---------------------------------------------------------------------------


class ScanRepoRequest(BaseModel):
    repo_url: str = "https://github.com/t1mchee/payment-service"
    branch: str = "main"
    max_issues: int = 10
    scan_code: bool = True


async def _fetch_github_issues(owner: str, repo: str, token: str, max_issues: int) -> list[dict]:
    """Fetch open bug-labeled issues from a GitHub repository."""
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token and token != "ghp_xxx":
        headers["Authorization"] = f"token {token}"
    issues: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        # Try bug-labeled issues first
        url = f"https://api.github.com/repos/{owner}/{repo}/issues"
        params = {"state": "open", "labels": "bug", "per_page": max_issues, "sort": "updated"}
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code == 200:
            issues = resp.json()

        # If not enough bug-labeled issues, also fetch recent issues
        if len(issues) < max_issues:
            params_all = {"state": "open", "per_page": max_issues * 2, "sort": "updated"}
            resp2 = await client.get(url, headers=headers, params=params_all)
            if resp2.status_code == 200:
                seen_ids = {i["id"] for i in issues}
                for issue in resp2.json():
                    if issue["id"] not in seen_ids and not issue.get("pull_request"):
                        issues.append(issue)
                        if len(issues) >= max_issues:
                            break
    return issues[:max_issues]


async def _fetch_error_patterns(owner: str, repo: str, token: str, branch: str = "main") -> list[dict]:
    """Scan recent commits for error-related patterns (TypeError, catch blocks, etc.)."""
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token and token != "ghp_xxx":
        headers["Authorization"] = f"token {token}"
    patterns: list[dict] = []
    async with httpx.AsyncClient(timeout=30) as client:
        # Get recent commits
        url = f"https://api.github.com/repos/{owner}/{repo}/commits"
        resp = await client.get(url, headers=headers, params={"per_page": 20, "sha": branch})
        if resp.status_code != 200:
            return patterns

        commits = resp.json()
        error_keywords = ["fix", "bug", "error", "crash", "exception", "null", "undefined", "TypeError", "fail"]

        for commit in commits:
            msg = commit.get("commit", {}).get("message", "")
            msg_lower = msg.lower()
            if any(kw.lower() in msg_lower for kw in error_keywords):
                patterns.append({
                    "sha": commit["sha"][:8],
                    "message": msg.split("\n")[0][:200],
                    "author": commit.get("commit", {}).get("author", {}).get("name", ""),
                    "date": commit.get("commit", {}).get("author", {}).get("date", ""),
                    "url": commit.get("html_url", ""),
                })
    return patterns[:10]


# ---------------------------------------------------------------------------
# Code-level static analysis — scan actual source files for bug patterns
# ---------------------------------------------------------------------------

# Bug pattern definitions: each pattern has a regex, severity, error class, and description
_CODE_BUG_PATTERNS: list[dict] = [
    {
        "id": "null-deref",
        "pattern": r"(\w+)!\.(\w+)",
        "title": "Potential null dereference — non-null assertion on possibly null value",
        "error_class": "TypeError",
        "severity": "high",
        "description": "Non-null assertion operator used on a value that may be null, risking TypeError at runtime.",
    },
    {
        "id": "sql-injection",
        "pattern": r"(SELECT|INSERT|UPDATE|DELETE).*\$\{.*\}|`.*\$\{.*\}.*`.*(?:WHERE|VALUES|SET)",
        "title": "SQL injection — user input interpolated into query string",
        "error_class": "SQLInjection",
        "severity": "critical",
        "description": "User-controlled input is directly interpolated into a SQL query string without parameterization.",
    },
    {
        "id": "sql-injection-concat",
        "pattern": r"(?:SELECT|INSERT|UPDATE|DELETE).*'\s*\+\s*\w+|\+\s*['\"]\s*(?:AND|OR|WHERE)",
        "title": "SQL injection — string concatenation in query",
        "error_class": "SQLInjection",
        "severity": "critical",
        "description": "SQL query is built via string concatenation with variables, vulnerable to injection.",
    },
    {
        "id": "unhandled-promise",
        "pattern": r"setTimeout\s*\(\s*\(\)\s*=>\s*\{?\s*\w+\([^)]*\)(?!\s*\.catch)",
        "title": "Unhandled promise rejection — async call in setTimeout without .catch()",
        "error_class": "UnhandledRejection",
        "severity": "high",
        "description": "Async function called inside setTimeout without error handling. If it throws, the rejection is unhandled and may crash the process.",
    },
    {
        "id": "unbounded-array",
        "pattern": r"(\w+)\.push\([^)]+\)(?!.*(?:shift|splice|slice|length\s*>|MAX_))",
        "title": "Potential memory leak — unbounded array growth",
        "error_class": "OOMKilled",
        "severity": "medium",
        "description": "Array is appended to but never trimmed. Under sustained load this causes unbounded memory growth and eventual OOMKilled.",
    },
    {
        "id": "timing-attack",
        "pattern": r"(?:apiKey|password|secret|token)\s*[!=]==?\s*(?:validKey|expected|stored|process\.env)",
        "title": "Timing attack — non-constant-time secret comparison",
        "error_class": "SecurityVulnerability",
        "severity": "medium",
        "description": "Secret values are compared using standard equality operators instead of constant-time comparison (crypto.timingSafeEqual), leaking information via response timing.",
    },
    {
        "id": "race-condition",
        "pattern": r"(?:get|check|has)\w*\([^)]*\)[\s\S]{0,200}await\s+new\s+Promise[\s\S]{0,200}(?:set|update|mark)\w*\(",
        "title": "Race condition — time-of-check to time-of-use (TOCTOU)",
        "error_class": "RaceCondition",
        "severity": "high",
        "description": "A check-then-act sequence with an async delay between them. Concurrent requests can both pass the check before either completes the action.",
    },
    {
        "id": "missing-null-check",
        "pattern": r"await\s+\w+\([^)]*\)[\s;]*\n[^!]*\.(\w+)",
        "title": "Missing null check after async call",
        "error_class": "TypeError",
        "severity": "medium",
        "description": "Return value from async function is accessed without null checking. If the function returns null/undefined, this will throw.",
    },
]


async def _scan_source_files(
    owner: str, repo: str, token: str, branch: str = "main",
) -> list[dict]:
    """Clone a GitHub repo and scan source files for bug patterns.

    Clones the repo via git (works for both public and private repos that the
    git proxy has access to), then walks source files looking for:
    1. Explicit BUG:/FIXME:/HACK: comment markers
    2. Regex-based pattern matching for known vulnerability classes
    """
    import re
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    source_extensions = {".ts", ".js", ".py", ".go", ".java", ".rs", ".tsx", ".jsx"}
    findings: list[dict] = []

    # Clone repo to temp directory using git (the git proxy handles auth)
    clone_url = f"https://git-manager.devin.ai/proxy/github.com/{owner}/{repo}.git"
    tmp_dir = tempfile.mkdtemp(prefix="devinguard-scan-")

    try:
        proc = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", branch, clone_url, tmp_dir],
                capture_output=True, text=True, timeout=30,
            ),
        )
        if proc.returncode != 0:
            logger.warning(f"Failed to clone {owner}/{repo}@{branch}: {proc.stderr[:200]}")
            return findings

        repo_root = Path(tmp_dir)

        # Walk source files
        source_files: list[Path] = []
        for ext in source_extensions:
            source_files.extend(repo_root.rglob(f"*{ext}"))

        # Filter out node_modules, dist, test files
        source_files = [
            f for f in source_files
            if "node_modules" not in str(f)
            and "/dist/" not in str(f)
            and "test" not in f.name.lower()
            and ".d.ts" not in f.name
        ]

        for src_file in source_files[:30]:
            try:
                content = src_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # Relative path from repo root
            file_path = str(src_file.relative_to(repo_root))
            lines = content.split("\n")

            # Check for BUG: / FIXME: / HACK: comments (explicit markers)
            for line_num, line in enumerate(lines, 1):
                line_stripped = line.strip()
                for marker in ["BUG:", "FIXME:", "HACK:"]:
                    if marker in line_stripped and line_stripped.lstrip("/ *#").startswith(marker):
                        desc = line_stripped.split(marker, 1)[1].strip()
                        if len(desc) < 10:
                            continue
                        context_lines = lines[max(0, line_num - 2):min(len(lines), line_num + 5)]
                        context = "\n".join(context_lines)

                        desc_lower = desc.lower()
                        error_class = "RuntimeError"
                        if "race" in desc_lower or "toctou" in desc_lower or "concurrent" in desc_lower:
                            error_class = "RaceCondition"
                        elif "memory" in desc_lower or "leak" in desc_lower or "oom" in desc_lower or "unbounded" in desc_lower:
                            error_class = "OOMKilled"
                        elif "null" in desc_lower or "typeerror" in desc_lower or "undefined" in desc_lower:
                            error_class = "TypeError"
                        elif "sql" in desc_lower or "injection" in desc_lower:
                            error_class = "SQLInjection"
                        elif "unhandled" in desc_lower or "promise" in desc_lower or "catch" in desc_lower:
                            error_class = "UnhandledRejection"
                        elif "timing" in desc_lower or "security" in desc_lower:
                            error_class = "SecurityVulnerability"
                        elif "off-by-one" in desc_lower or "boundary" in desc_lower:
                            error_class = "LogicError"

                        findings.append({
                            "type": "code_marker",
                            "file": file_path,
                            "line": line_num,
                            "marker": marker.rstrip(":"),
                            "description": desc[:200],
                            "error_class": error_class,
                            "severity": "high" if marker == "BUG:" else "medium",
                            "context": context[:500],
                        })

            # Run regex-based pattern matching
            for pattern_def in _CODE_BUG_PATTERNS:
                try:
                    matches = list(re.finditer(pattern_def["pattern"], content, re.MULTILINE))
                except re.error:
                    continue
                for match in matches[:3]:
                    match_line = content[:match.start()].count("\n") + 1
                    context_start = max(0, match_line - 3)
                    context_end = min(len(lines), match_line + 4)
                    context = "\n".join(lines[context_start:context_end])

                    findings.append({
                        "type": "pattern_match",
                        "file": file_path,
                        "line": match_line,
                        "pattern_id": pattern_def["id"],
                        "title": pattern_def["title"],
                        "error_class": pattern_def["error_class"],
                        "severity": pattern_def["severity"],
                        "description": pattern_def["description"],
                        "matched_text": match.group(0)[:100],
                        "context": context[:500],
                    })

    finally:
        # Clean up temp directory
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Deduplicate findings by (file, error_class) — keep the highest severity one
    seen: dict[str, dict] = {}
    severity_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    for f in findings:
        key = f"{f['file']}:{f['error_class']}"
        existing = seen.get(key)
        if not existing or severity_rank.get(f["severity"], 0) > severity_rank.get(existing["severity"], 0):
            seen[key] = f
    return list(seen.values())


def _code_findings_to_alerts(
    findings: list[dict], owner: str, repo: str,
) -> list[dict]:
    """Convert code analysis findings into PagerDuty-style alert payloads."""
    alerts = []
    for f in findings:
        title = f.get("title") or f.get("description", "Code issue")
        file_path = f["file"]
        line = f.get("line", 0)

        # Build a descriptive title for the dashboard
        display_title = f"{f['error_class']}: {title}"
        if len(display_title) > 120:
            display_title = display_title[:117] + "..."

        alerts.append({
            "event": {
                "event_type": "incident.triggered",
                "data": {
                    "id": f"code-{owner}-{repo}-{file_path}-L{line}-{f['error_class']}",
                    "title": display_title,
                    "urgency": "high" if f.get("severity") in ("critical", "high") else "low",
                    "service": {"name": repo},
                    "body": {
                        "details": {
                            "error_class": f["error_class"],
                            "error_message": f.get("description", title),
                            "file": file_path,
                            "line": line,
                            "severity": f.get("severity", "medium"),
                            "context": f.get("context", ""),
                            "source": f.get("type", "code_analysis"),
                            "github_url": f"https://github.com/{owner}/{repo}/blob/main/{file_path}#L{line}",
                        }
                    },
                },
            }
        })
    return alerts


def _issues_to_alerts(
    issues: list[dict], owner: str, repo: str,
) -> list[dict]:
    """Convert GitHub issues into PagerDuty-style alert payloads."""
    alerts = []
    for issue in issues:
        title = issue.get("title", "Unknown issue")
        body_text = issue.get("body", "") or ""
        labels = [l.get("name", "") for l in issue.get("labels", [])]

        # Infer error class from title/labels
        error_class = "RuntimeError"
        title_lower = title.lower()
        if "typeerror" in title_lower:
            error_class = "TypeError"
        elif "null" in title_lower or "undefined" in title_lower:
            error_class = "TypeError"
        elif "memory" in title_lower or "oom" in title_lower:
            error_class = "OOMKilled"
        elif "timeout" in title_lower or "latency" in title_lower or "slow" in title_lower:
            error_class = "LatencySpike"
        elif "crash" in title_lower or "segfault" in title_lower:
            error_class = "CrashError"
        elif "import" in title_lower or "module" in title_lower:
            error_class = "ImportError"
        elif any(l in ["infrastructure", "infra", "ops", "platform"] for l in labels):
            error_class = "InfrastructureError"

        # Extract stack trace from issue body if present
        stack_trace = None
        if "```" in body_text:
            # Try to extract code blocks as potential stack traces
            parts = body_text.split("```")
            for i in range(1, len(parts), 2):
                block = parts[i].strip()
                if block.startswith(("Traceback", "Error", "at ", "TypeError", "  File")):
                    stack_trace = block[:1000]
                    break
                if len(block) > 50:
                    stack_trace = block[:1000]

        alerts.append({
            "event": {
                "event_type": "incident.triggered",
                "data": {
                    "id": f"gh-{owner}-{repo}-{issue['number']}",
                    "title": title,
                    "urgency": "high",
                    "service": {"name": repo},
                    "body": {
                        "details": {
                            "error_class": error_class,
                            "error_message": title,
                            "stack_trace": stack_trace or f"GitHub Issue #{issue['number']}: {body_text[:500]}",
                            "github_issue_url": issue.get("html_url", ""),
                            "github_issue_number": issue["number"],
                        }
                    },
                },
            }
        })
    return alerts


def _commits_to_alerts(
    patterns: list[dict], owner: str, repo: str,
) -> list[dict]:
    """Convert error-related commits into alert payloads."""
    alerts = []
    for p in patterns:
        msg = p["message"]
        error_class = "RuntimeError"
        msg_lower = msg.lower()
        if "typeerror" in msg_lower or "null" in msg_lower:
            error_class = "TypeError"
        elif "memory" in msg_lower or "oom" in msg_lower:
            error_class = "OOMKilled"
        elif "timeout" in msg_lower or "latency" in msg_lower:
            error_class = "LatencySpike"

        alerts.append({
            "event": {
                "event_type": "incident.triggered",
                "data": {
                    "id": f"gh-commit-{p['sha']}",
                    "title": f"Error pattern in commit {p['sha']}: {msg}",
                    "urgency": "high",
                    "service": {"name": repo},
                    "body": {
                        "details": {
                            "error_class": error_class,
                            "error_message": msg,
                            "commit_sha": p["sha"],
                            "commit_url": p.get("url", ""),
                        }
                    },
                },
            }
        })
    return alerts


@router.post("/scan-repo")
async def scan_repository(
    request: Request,
    background_tasks: BackgroundTasks,
    body: ScanRepoRequest,
) -> dict:
    """Scan a GitHub repository for real bugs and feed them through the pipeline.

    Discovers issues from three sources:
    1. Open GitHub issues labeled 'bug'
    2. Recent commits with error-related messages
    3. Code-level static analysis (BUG markers, regex pattern matching)
    Each discovered issue becomes a real alert flowing through triage -> dispatch -> fix.
    """
    from app.api.webhooks import get_dispatcher
    from app.webhooks.normalizers import normalize_pagerduty

    # Parse repo URL
    repo_url = body.repo_url.rstrip("/")
    parts = repo_url.replace("https://github.com/", "").replace("http://github.com/", "").split("/")
    if len(parts) < 2:
        return {"error": "Invalid repo URL. Expected format: https://github.com/owner/repo"}
    owner, repo = parts[0], parts[1]

    token = settings.github_token or ""
    branch = body.branch or "main"

    # Fetch issues, commit patterns, and scan source code in parallel
    gather_tasks: list = [
        _fetch_github_issues(owner, repo, token, body.max_issues),
        _fetch_error_patterns(owner, repo, token, branch),
    ]
    if body.scan_code:
        gather_tasks.append(_scan_source_files(owner, repo, token, branch))

    results_raw = await asyncio.gather(*gather_tasks, return_exceptions=True)

    issues = results_raw[0] if not isinstance(results_raw[0], Exception) else []
    patterns = results_raw[1] if not isinstance(results_raw[1], Exception) else []
    code_findings = results_raw[2] if len(results_raw) > 2 and not isinstance(results_raw[2], Exception) else []

    if not issues and not patterns and not code_findings:
        return {"error": f"No issues, error patterns, or code bugs found in {owner}/{repo}@{branch}. The repo may be private (set GITHUB_TOKEN in .env)."}

    # Convert all sources to alert payloads
    alert_payloads: list[dict] = []

    # Code findings are the richest source — add them first
    if code_findings:
        alert_payloads.extend(_code_findings_to_alerts(code_findings, owner, repo))

    # Add issue-based alerts
    issue_alerts = _issues_to_alerts(issues, owner, repo)
    alert_payloads.extend(issue_alerts)

    # Add commit-based alerts if we don't have enough yet
    if len(alert_payloads) < body.max_issues:
        commit_alerts = _commits_to_alerts(patterns[:body.max_issues - len(alert_payloads)], owner, repo)
        alert_payloads.extend(commit_alerts)

    # Deduplicate by error_class to ensure diverse alerts
    seen_classes: set[str] = set()
    deduped: list[dict] = []
    for payload in alert_payloads:
        ec = payload["event"]["data"]["body"]["details"].get("error_class", "")
        key = ec
        if key not in seen_classes:
            seen_classes.add(key)
            deduped.append(payload)
        elif len(deduped) < body.max_issues:
            # Allow duplicates if we haven't hit the limit
            deduped.append(payload)
    alert_payloads = deduped[:body.max_issues]

    # Process each alert through the pipeline
    dispatcher = get_dispatcher(request)
    results = []
    for payload in alert_payloads:
        try:
            alert = normalize_pagerduty(payload)
            result = await dispatcher.handle_alert(alert)
            if result.get("action") == "dispatched_to_devin":
                investigation_id = result["investigation_id"]
                background_tasks.add_task(dispatcher.monitor_session, investigation_id)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to process scanned issue: {e}")
            results.append({"error": str(e)})
        # Small delay between alerts for visual effect on dashboard
        await asyncio.sleep(0.5)

    return {
        "repo": f"{owner}/{repo}",
        "branch": branch,
        "issues_found": len(issues),
        "error_commits_found": len(patterns),
        "code_findings_found": len(code_findings),
        "alerts_created": len(alert_payloads),
        "results": results,
    }


@router.get("/scan-repo/preview")
async def preview_scan(
    repo_url: str = "https://github.com/t1mchee/payment-service",
    branch: str = "main",
) -> dict:
    """Preview what a scan would find without triggering the pipeline."""
    repo_url = repo_url.rstrip("/")
    parts = repo_url.replace("https://github.com/", "").replace("http://github.com/", "").split("/")
    if len(parts) < 2:
        return {"error": "Invalid repo URL"}
    owner, repo = parts[0], parts[1]

    token = settings.github_token or ""

    issues, patterns, code_findings = await asyncio.gather(
        _fetch_github_issues(owner, repo, token, 10),
        _fetch_error_patterns(owner, repo, token, branch),
        _scan_source_files(owner, repo, token, branch),
    )

    return {
        "repo": f"{owner}/{repo}",
        "branch": branch,
        "issues": [{"number": i["number"], "title": i["title"], "labels": [l["name"] for l in i.get("labels", [])]} for i in issues],
        "error_commits": patterns,
        "code_findings": [
            {
                "file": f["file"],
                "line": f.get("line"),
                "error_class": f["error_class"],
                "severity": f.get("severity"),
                "title": f.get("title") or f.get("description", ""),
            }
            for f in code_findings
        ],
    }


# ---------------------------------------------------------------------------
# Session status polling (for live Devin progress on cards)
# ---------------------------------------------------------------------------

@router.get("/session-status/{session_id}")
async def get_session_status(request: Request, session_id: str) -> dict:
    """Poll Devin API for session progress. Returns status and structured steps."""
    from app.core.devin_client import DevinAPIClient

    client = DevinAPIClient()
    try:
        session = await client.get_session(session_id)
    except Exception as exc:
        return {"error": str(exc), "session_id": session_id}
    finally:
        await client.close()

    status = session.get("status", "unknown")
    status_enum = session.get("status_enum", status)

    # Build progress steps from session data
    steps: list[dict] = []
    steps.append({"label": "Session created", "status": "done", "ts": session.get("created_at")})

    if status_enum in ("running", "blocked", "stopped", "finished"):
        steps.append({"label": "Cloning repository", "status": "done"})

    if status_enum in ("running", "blocked"):
        steps.append({"label": "Analyzing code", "status": "active"})
    elif status_enum in ("stopped", "finished"):
        steps.append({"label": "Analyzing code", "status": "done"})
        steps.append({"label": "Writing fix", "status": "done"})

    prs = session.get("pull_requests", [])
    if prs:
        steps.append({"label": "Running tests", "status": "done"})
        steps.append({
            "label": "PR opened",
            "status": "done",
            "pr_url": prs[0].get("pr_url", ""),
        })
    elif status_enum == "finished":
        steps.append({"label": "Investigation complete", "status": "done"})

    return {
        "session_id": session_id,
        "status": status,
        "status_enum": status_enum,
        "steps": steps,
        "pull_requests": prs,
        "acus_consumed": session.get("acus_consumed", 0),
        "structured_output": session.get("structured_output"),
    }


# ---------------------------------------------------------------------------
# Escalations — human review panel
# ---------------------------------------------------------------------------


@router.get("/escalations")
async def list_escalations(request: Request) -> list[dict]:
    """Return all escalated investigations with triage reasoning."""
    from app.api.webhooks import get_dispatcher

    dispatcher = get_dispatcher(request)
    investigations = dispatcher.list_investigations()
    escalated = []
    for inv in investigations:
        if inv.triage_classification and inv.triage_classification != "CODE_LEVEL":
            d = inv.model_dump()
            # Attach triage reasoning from activity feed events
            reasoning = ""
            for evt in activity_feed.recent(200):
                if (
                    evt.investigation_id == inv.investigation_id
                    and evt.event_type == "triage_complete"
                ):
                    reasoning = evt.detail or ""
                    break
            d["triage_reasoning"] = reasoning
            # Attach escalation status (default: pending_review)
            d["escalation_status"] = getattr(inv, "_escalation_status", "pending_review")
            d["escalation_action"] = getattr(inv, "_escalation_action", None)
            escalated.append(d)
    return escalated


class EscalationAction(BaseModel):
    action: Literal["acknowledge", "reassign_to_devin", "dismiss"]
    reason: Optional[str] = None


@router.post("/escalations/{investigation_id}/action")
async def escalation_action(
    request: Request,
    background_tasks: BackgroundTasks,
    investigation_id: str,
    body: EscalationAction,
) -> dict:
    """Take action on an escalated investigation."""
    from app.api.webhooks import get_dispatcher

    dispatcher = get_dispatcher(request)
    inv = dispatcher.get_investigation(investigation_id)
    if not inv:
        return {"error": "Investigation not found"}

    if body.action == "acknowledge":
        inv._escalation_status = "acknowledged"  # type: ignore[attr-defined]
        inv._escalation_action = "acknowledge"  # type: ignore[attr-defined]
        activity_feed.emit(FeedEvent(
            event_type="escalated",
            investigation_id=investigation_id,
            service_name=inv.service_name,
            title="Human acknowledged escalation",
            detail=body.reason or "Acknowledged by operator",
        ))
        return {"status": "acknowledged", "investigation_id": investigation_id}

    elif body.action == "reassign_to_devin":
        # Override triage and dispatch to Devin
        inv.triage_classification = "CODE_LEVEL"
        inv._escalation_status = "reassigned"  # type: ignore[attr-defined]
        inv._escalation_action = "reassign_to_devin"  # type: ignore[attr-defined]

        activity_feed.emit(FeedEvent(
            event_type="dispatched",
            investigation_id=investigation_id,
            service_name=inv.service_name,
            title="Reassigned to Devin by human",
            detail=body.reason or "Human override — dispatching to Devin",
        ))

        # Create a Devin session for this investigation
        from app.core.devin_client import DevinAPIClient
        from app.models.devin import CreateSessionRequest

        client = DevinAPIClient()
        try:
            prompt = (
                f"Investigate and fix the issue in {inv.service_name}.\n"
                f"Dedup key: {inv.dedup_key}\n"
                f"Original classification: {inv.triage_classification}\n"
                f"Reason for reassignment: {body.reason or 'Human override'}"
            )
            session_req = CreateSessionRequest(
                prompt=prompt,
                repos=[settings.github_repo] if settings.github_repo else None,
                max_acu_limit=10,
                tags=["devinguard", f"inv:{investigation_id}", "human-override"],
                title=f"[DevinGuard] Human override: {inv.service_name}",
            )
            session_data = await client.create_session(session_req)
            inv.session_id = session_data["session_id"]
            inv.session_status = session_data.get("status", "new")

            background_tasks.add_task(dispatcher.monitor_session, investigation_id)

            return {
                "status": "reassigned",
                "investigation_id": investigation_id,
                "session_id": session_data["session_id"],
            }
        except Exception as e:
            return {"status": "reassign_failed", "error": str(e)}
        finally:
            await client.close()

    elif body.action == "dismiss":
        inv._escalation_status = "dismissed"  # type: ignore[attr-defined]
        inv._escalation_action = "dismiss"  # type: ignore[attr-defined]
        activity_feed.emit(FeedEvent(
            event_type="escalated",
            investigation_id=investigation_id,
            service_name=inv.service_name,
            title="Escalation dismissed",
            detail=body.reason or "Dismissed by operator",
        ))
        return {"status": "dismissed", "investigation_id": investigation_id}

    return {"error": "Unknown action"}


# ---------------------------------------------------------------------------
# Eval scorecard endpoint
# ---------------------------------------------------------------------------

@router.get("/eval-scorecard")
async def get_eval_scorecard() -> dict:
    """Return cached eval results for the scorecard panel."""
    eval_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "scripts", "eval_results.json"
    )
    eval_path = os.path.normpath(eval_path)
    try:
        with open(eval_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"error": "Eval results not found. Run: PYTHONPATH=. poetry run python scripts/eval_triage.py --cached"}
