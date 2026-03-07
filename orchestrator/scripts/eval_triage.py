"""Triage classifier evaluation harness.

Fetches real bug/infrastructure issues from popular GitHub repos,
converts them to AlertEvent payloads, runs them through the triage
classifier, and produces a precision/recall scorecard.

Usage:
    poetry run python scripts/eval_triage.py [--fetch] [--cached]

    --fetch   Force re-fetch from GitHub API (default on first run)
    --cached  Use cached dataset only (skip fetch)
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

from app.core.triage import TriageResult, classify_alert
from app.models.alert import AlertEvent

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ─── Data sources ────────────────────────────────────────────────────────────
# Each entry: (repo, search_query, ground_truth_label, label_filter)
# ground_truth_label is what we expect the classifier to output.

GITHUB_SOURCES = [
    # CODE_LEVEL bugs — repos with clear application-level bug labels
    {
        "repo": "expressjs/express",
        "query": "label:bug state:closed",
        "ground_truth": "CODE_LEVEL",
        "per_page": 30,
    },
    {
        "repo": "fastify/fastify",
        "query": "label:bug state:closed",
        "ground_truth": "CODE_LEVEL",
        "per_page": 30,
    },
    {
        "repo": "pallets/flask",
        "query": "label:bug state:closed",
        "ground_truth": "CODE_LEVEL",
        "per_page": 20,
    },
    {
        "repo": "tiangolo/fastapi",
        "query": "label:bug state:closed",
        "ground_truth": "CODE_LEVEL",
        "per_page": 20,
    },
    # INFRASTRUCTURE issues — repos with infra/ops labels
    {
        "repo": "kubernetes/kubernetes",
        "query": "label:kind/bug label:sig/node state:closed",
        "ground_truth": "INFRASTRUCTURE",
        "per_page": 25,
    },
    {
        "repo": "docker/compose",
        "query": "label:kind/bug state:closed",
        "ground_truth": "INFRASTRUCTURE",
        "per_page": 25,
    },
    {
        "repo": "hashicorp/terraform",
        "query": "label:bug state:closed",
        "ground_truth": "INFRASTRUCTURE",
        "per_page": 25,
    },
]

CACHE_PATH = Path(__file__).parent / "eval_dataset.json"


# ─── Fetcher ─────────────────────────────────────────────────────────────────

async def fetch_issues_from_github() -> list[dict]:
    """Fetch labeled issues from GitHub and convert to eval dataset entries."""
    dataset: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for source in GITHUB_SOURCES:
            repo = source["repo"]
            query = f"{source['query']} repo:{repo}"
            per_page = source["per_page"]
            ground_truth = source["ground_truth"]

            print(f"  Fetching from {repo} ({ground_truth})...", end=" ")

            try:
                resp = await client.get(
                    "https://api.github.com/search/issues",
                    params={"q": query, "per_page": per_page, "sort": "updated"},
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                print(f"got {len(items)} issues")

                for item in items:
                    title = item.get("title", "")
                    body = item.get("body", "") or ""
                    labels = [
                        lbl["name"] for lbl in item.get("labels", [])
                    ]

                    # Extract error class from title heuristically
                    error_class = _extract_error_class(title, body)
                    # Extract stack trace from body if present
                    stack_trace = _extract_stack_trace(body)

                    dataset.append({
                        "source_repo": repo,
                        "issue_number": item["number"],
                        "title": title,
                        "body_preview": body[:500],
                        "labels": labels,
                        "error_class": error_class,
                        "error_message": title,
                        "stack_trace": stack_trace,
                        "ground_truth": ground_truth,
                    })

            except Exception as e:
                print(f"FAILED: {e}")

            # Rate limit politeness
            await asyncio.sleep(1.0)

    return dataset


def _extract_error_class(title: str, body: str) -> str:
    """Extract the error class from issue title/body."""
    import re

    # Common error patterns
    patterns = [
        r"(TypeError|ReferenceError|SyntaxError|RangeError|URIError)",
        r"(NullPointerException|ClassNotFoundException|IOException)",
        r"(KeyError|ValueError|AttributeError|ImportError|ModuleNotFoundError)",
        r"(IndentationError|ParseError|AssertionError)",
        r"(OOMKilled|OutOfMemoryError|MemoryError)",
        r"(ConnectionRefused|ECONNREFUSED|ECONNRESET|ETIMEDOUT)",
        r"(ENOSPC|disk full|no space left)",
        r"(SSLError|CertificateError|TLSError)",
        r"(DNS.*fail|ENOTFOUND)",
        r"(PermissionError|EACCES|forbidden)",
        r"(TimeoutError|ETIMEOUT|deadline exceeded)",
        r"(HTTP\s*[45]\d\d)",
    ]

    text = f"{title} {body[:1000]}"
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)

    # Fallback: use first word of title if it looks like an error class
    first_word = title.split(":")[0].strip() if ":" in title else title.split()[0] if title else ""
    if first_word.endswith("Error") or first_word.endswith("Exception"):
        return first_word

    return "UnknownError"


def _extract_stack_trace(body: str) -> Optional[str]:
    """Extract stack trace from issue body."""
    import re

    # Look for common stack trace patterns in code blocks
    code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", body, re.DOTALL)
    for block in code_blocks:
        # Check if it looks like a stack trace
        if any(indicator in block for indicator in [
            "at ", "Traceback", "File \"", "  at ", "Error:", "Exception:",
            "    at ", "node_modules", "site-packages",
        ]):
            return block[:2000]  # Truncate very long traces

    # Also check for indented stack traces outside code blocks
    lines = body.split("\n")
    trace_lines: list[str] = []
    in_trace = False
    for line in lines:
        stripped = line.strip()
        if any(stripped.startswith(s) for s in ["at ", "File \"", "Traceback"]):
            in_trace = True
        if in_trace:
            trace_lines.append(line)
            if len(trace_lines) > 20:
                break
        elif trace_lines:
            break

    if len(trace_lines) >= 2:
        return "\n".join(trace_lines)

    return None


# ─── Evaluator ───────────────────────────────────────────────────────────────

async def evaluate_dataset(dataset: list[dict]) -> dict:
    """Run the triage classifier on each entry and compute metrics."""
    results: list[dict] = []

    print(f"\nEvaluating {len(dataset)} issues through triage classifier...\n")

    for i, entry in enumerate(dataset):
        # Convert to AlertEvent
        alert = AlertEvent(
            source="custom",
            service_name=entry["source_repo"].split("/")[1],
            error_class=entry["error_class"],
            error_message=entry["error_message"],
            stack_trace=entry.get("stack_trace"),
            severity="P2",
            timestamp=datetime.utcnow(),
        )

        # Run through classifier (rule-based only, no LLM)
        triage_result: TriageResult = await classify_alert(alert)

        predicted = triage_result.classification
        ground_truth = entry["ground_truth"]

        results.append({
            "repo": entry["source_repo"],
            "issue": entry["issue_number"],
            "title": entry["title"][:60],
            "error_class": entry["error_class"],
            "has_stack_trace": entry.get("stack_trace") is not None,
            "ground_truth": ground_truth,
            "predicted": predicted,
            "confidence": triage_result.confidence,
            "reasoning": triage_result.reasoning,
            "correct": predicted == ground_truth,
            "would_dispatch": triage_result.should_dispatch_to_devin,
        })

        if (i + 1) % 25 == 0:
            print(f"  Processed {i + 1}/{len(dataset)}...")

    return _compute_scorecard(results)


def _compute_scorecard(results: list[dict]) -> dict:
    """Compute precision, recall, F1, and confusion matrix."""
    total = len(results)
    correct = sum(1 for r in results if r["correct"])

    # Per-class metrics
    classes = ["CODE_LEVEL", "INFRASTRUCTURE", "AMBIGUOUS"]
    class_metrics: dict = {}

    for cls in classes:
        true_positives = sum(
            1 for r in results
            if r["predicted"] == cls and r["ground_truth"] == cls
        )
        false_positives = sum(
            1 for r in results
            if r["predicted"] == cls and r["ground_truth"] != cls
        )
        false_negatives = sum(
            1 for r in results
            if r["predicted"] != cls and r["ground_truth"] == cls
        )

        tp_fp = true_positives + false_positives
        tp_fn = true_positives + false_negatives
        precision = true_positives / tp_fp if tp_fp > 0 else 0.0
        recall = true_positives / tp_fn if tp_fn > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        class_metrics[cls] = {
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
        }

    # Dispatch metrics (for CODE_LEVEL alerts — did we correctly dispatch to Devin?)
    code_level_results = [r for r in results if r["ground_truth"] == "CODE_LEVEL"]
    dispatched_correctly = sum(
        1 for r in code_level_results
        if r["would_dispatch"] and r["correct"]
    )
    total_dispatched = sum(
        1 for r in results if r["would_dispatch"]
    )

    dispatch_precision = dispatched_correctly / total_dispatched if total_dispatched > 0 else 0.0

    # Breakdown by repo
    repo_breakdown: dict = {}
    for r in results:
        repo = r["repo"]
        if repo not in repo_breakdown:
            repo_breakdown[repo] = {"total": 0, "correct": 0, "ambiguous": 0}
        repo_breakdown[repo]["total"] += 1
        if r["correct"]:
            repo_breakdown[repo]["correct"] += 1
        if r["predicted"] == "AMBIGUOUS":
            repo_breakdown[repo]["ambiguous"] += 1

    # Misclassified examples
    misclassified = [
        {
            "repo": r["repo"],
            "issue": r["issue"],
            "title": r["title"],
            "error_class": r["error_class"],
            "ground_truth": r["ground_truth"],
            "predicted": r["predicted"],
            "confidence": r["confidence"],
            "reasoning": r["reasoning"],
        }
        for r in results
        if not r["correct"] and r["predicted"] != "AMBIGUOUS"
    ]

    # Decision accuracy: how well does the classifier do when it actually makes a call?
    non_ambiguous = [r for r in results if r["predicted"] != "AMBIGUOUS"]
    non_ambiguous_correct = sum(1 for r in non_ambiguous if r["correct"])
    decision_accuracy = non_ambiguous_correct / len(non_ambiguous) if non_ambiguous else 0.0
    coverage = len(non_ambiguous) / total if total > 0 else 0.0

    scorecard = {
        "summary": {
            "total_evaluated": total,
            "correct": correct,
            "accuracy": round(correct / total, 3) if total > 0 else 0.0,
            "non_ambiguous_count": len(non_ambiguous),
            "decision_accuracy": round(decision_accuracy, 3),
            "coverage": round(coverage, 3),
            "total_dispatched_to_devin": total_dispatched,
            "dispatch_precision": round(dispatch_precision, 3),
        },
        "per_class": class_metrics,
        "repo_breakdown": repo_breakdown,
        "misclassified_examples": misclassified[:20],  # Top 20
        "all_results": results,
    }

    return scorecard


def print_scorecard(scorecard: dict) -> None:
    """Pretty-print the evaluation scorecard."""
    s = scorecard["summary"]
    print("\n" + "=" * 70)
    print("  DevinGuard Triage Classifier — Evaluation Scorecard")
    print("=" * 70)

    print(f"\n  Dataset size:          {s['total_evaluated']} issues")
    print(f"  Overall accuracy:      {s['accuracy']:.1%}")
    print(f"  Decision accuracy:     {s['decision_accuracy']:.1%}  (when not AMBIGUOUS)")
    na = s['non_ambiguous_count']
    te = s['total_evaluated']
    print(f"  Coverage:              {s['coverage']:.1%}  ({na}/{te} classified)")
    print(f"  Dispatched to Devin:   {s['total_dispatched_to_devin']}")
    print(f"  Dispatch precision:    {s['dispatch_precision']:.1%}")

    print(f"\n{'─' * 70}")
    hdr = f"  {'Class':<18} {'Precision':>10} {'Recall':>10}"
    hdr += f" {'F1':>10}  {'TP':>5} {'FP':>5} {'FN':>5}"
    print(hdr)
    print(f"{'─' * 70}")
    for cls, m in scorecard["per_class"].items():
        tp = m['true_positives']
        fp = m['false_positives']
        fn = m['false_negatives']
        row = f"  {cls:<18} {m['precision']:>10.1%}"
        row += f" {m['recall']:>10.1%} {m['f1']:>10.1%}"
        row += f"  {tp:>5} {fp:>5} {fn:>5}"
        print(row)

    print(f"\n{'─' * 70}")
    print(f"  {'Repository':<35} {'Total':>6} {'Correct':>8} {'Acc':>8} {'Ambig':>7}")
    print(f"{'─' * 70}")
    for repo, m in scorecard["repo_breakdown"].items():
        acc = m["correct"] / m["total"] if m["total"] > 0 else 0
        print(f"  {repo:<35} {m['total']:>6} {m['correct']:>8} {acc:>8.1%} {m['ambiguous']:>7}")

    misclassified = scorecard["misclassified_examples"]
    if misclassified:
        print(f"\n{'─' * 70}")
        print("  Misclassified Examples (excluding AMBIGUOUS fallback):")
        print(f"{'─' * 70}")
        for ex in misclassified[:10]:
            print(f"  [{ex['repo']}#{ex['issue']}] \"{ex['title']}\"")
            ec = ex['error_class']
            gt = ex['ground_truth']
            pred = ex['predicted']
            conf = ex['confidence']
            print(
                f"    error_class={ec}  expected={gt}"
                f"  got={pred} ({conf:.2f})"
            )
            print(f"    reason: {ex['reasoning']}")
            print()

    print("=" * 70)


# ─── Main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    use_cache = "--cached" in sys.argv
    force_fetch = "--fetch" in sys.argv

    # Step 1: Get dataset
    if use_cache and CACHE_PATH.exists():
        print(f"Loading cached dataset from {CACHE_PATH}")
        dataset = json.loads(CACHE_PATH.read_text())
    elif CACHE_PATH.exists() and not force_fetch:
        print(f"Loading cached dataset from {CACHE_PATH}")
        dataset = json.loads(CACHE_PATH.read_text())
    else:
        print("Fetching issues from GitHub API...")
        dataset = await fetch_issues_from_github()
        # Cache for future runs
        CACHE_PATH.write_text(json.dumps(dataset, indent=2, default=str))
        print(f"Cached {len(dataset)} issues to {CACHE_PATH}")

    print(f"\nDataset: {len(dataset)} issues")
    gt_counts = {}
    for entry in dataset:
        gt = entry["ground_truth"]
        gt_counts[gt] = gt_counts.get(gt, 0) + 1
    for gt, count in sorted(gt_counts.items()):
        print(f"  {gt}: {count}")

    # Step 2: Evaluate
    scorecard = await evaluate_dataset(dataset)

    # Step 3: Print results
    print_scorecard(scorecard)

    # Step 4: Save full results
    results_path = Path(__file__).parent / "eval_results.json"
    scorecard_export = {k: v for k, v in scorecard.items() if k != "all_results"}
    results_path.write_text(json.dumps(scorecard_export, indent=2, default=str))
    print(f"\nFull results saved to {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
