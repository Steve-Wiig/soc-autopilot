#!/usr/bin/env python3
"""
Read-only audit: verify every assertion behind the proposed TDD-prompt change.

SAFETY DISCIPLINE
  * Path.read_text() only.
  * No writes, no subprocess, no network, no env mutation.
  * stdout only.

PURPOSE
  Every claim behind the proposed change to the TDD generation prompt is
  verified here against the raw source or the raw data. If a claim cannot
  be confirmed from a specific line of a specific file, the audit says so
  explicitly and the change should not proceed on that claim.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SELF_IMPROVER = REPO_ROOT / "overnight" / "self_improver.py"
QUEUE_PATH = REPO_ROOT / "overnight" / "needs_manual_review.json"
LEDGER_PATH = REPO_ROOT / "overnight" / "improvement_ledger.jsonl"
PROVEN_PATH = REPO_ROOT / "overnight" / "proven_fixes.jsonl"


# ===========================================================================
# Output helpers
# ===========================================================================
def header(t: str) -> None:
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


def section(t: str) -> None:
    print()
    print(f"--- {t} ---")


def read_text_safe(p: Path) -> str | None:
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def find_line(path: Path, needle: str) -> tuple[int, str] | None:
    """Return (line_number, line) for the first line containing needle."""
    raw = read_text_safe(path)
    if raw is None:
        return None
    for i, line in enumerate(raw.splitlines(), 1):
        if needle in line:
            return (i, line.strip())
    return None


def confirm(assertion: str, source: str, evidence: str, ok: bool) -> bool:
    print()
    print(f"  ASSERTION: {assertion}")
    print(f"  SOURCE:    {source}")
    print(f"  EVIDENCE:  {evidence}")
    print(f"  RESULT:    {'CONFIRMED' if ok else 'NOT CONFIRMED'}")
    return ok


# ===========================================================================
# Section A: source-level assertions
# ===========================================================================
def audit_source_assertions() -> dict[str, bool]:
    section("SECTION A: SOURCE ASSERTIONS (self_improver.py)")
    results = {}

    # A1: RED-phase gate rejects tests that pass on old code.
    hit = find_line(SELF_IMPROVER, "TDD Red Phase FAILED")
    results["A1_red_phase_gate_exists"] = bool(hit)
    if hit:
        confirm(
            "The RED-phase gate rejects tests that pass on old code.",
            f"overnight/self_improver.py:{hit[0]}",
            hit[1][:120],
            True,
        )
    else:
        confirm(
            "The RED-phase gate rejects tests that pass on old code.",
            "overnight/self_improver.py",
            "needle not found",
            False,
        )

    # A2: TDD prompt asks for a failing test.
    hit = find_line(SELF_IMPROVER, "Write a minimal failing pytest test")
    results["A2_prompt_asks_for_failing_test"] = bool(hit)
    confirm(
        "The TDD generation prompt asks for a failing test.",
        f"overnight/self_improver.py:{hit[0]}" if hit else "overnight/self_improver.py",
        hit[1][:120] if hit else "needle not found",
        bool(hit),
    )

    # A3: FUNCTIONAL_CATEGORIES is a hardcoded set.
    hit = find_line(SELF_IMPROVER, "FUNCTIONAL_CATEGORIES =")
    results["A3_functional_categories_defined"] = bool(hit)
    confirm(
        "FUNCTIONAL_CATEGORIES is a hardcoded set at module level.",
        f"overnight/self_improver.py:{hit[0]}" if hit else "overnight/self_improver.py",
        hit[1][:120] if hit else "needle not found",
        bool(hit),
    )

    # A4: LOCAL_TDD routing requires four specific conditions.
    # Look for the classifier block.
    raw = read_text_safe(SELF_IMPROVER)
    if raw:
        has_local_tdd = 'return "LOCAL_TDD"' in raw
        has_severity_check = 'severity in {"low", "informational"}' in raw
        has_effort_check = 'effort in {"trivial", "small"}' in raw
        has_impact_check = 'impact in {"low", "medium"}' in raw
        results["A4_local_tdd_four_field_gate"] = (
            has_local_tdd and has_severity_check
            and has_effort_check and has_impact_check
        )
        confirm(
            "LOCAL_TDD routing is gated by all four fields "
            "(category, severity, effort, impact).",
            "overnight/self_improver.py",
            f"LOCAL_TDD={has_local_tdd} severity={has_severity_check} "
            f"effort={has_effort_check} impact={has_impact_check}",
            results["A4_local_tdd_four_field_gate"],
        )
    else:
        results["A4_local_tdd_four_field_gate"] = False

    # A5: Protected kernel exists (from the previous commit).
    pk = REPO_ROOT / "engine" / "protected_kernel.py"
    results["A5_protected_kernel_exists"] = pk.is_file()
    confirm(
        "Protected kernel module exists (previous hardening commit).",
        "engine/protected_kernel.py",
        "file present" if pk.is_file() else "file missing",
        pk.is_file(),
    )

    return results


# ===========================================================================
# Section B: data assertions
# ===========================================================================
def audit_data_assertions() -> dict[str, bool]:
    section("SECTION B: DATA ASSERTIONS")
    results = {}

    # B1: queue has expected count
    raw = read_text_safe(QUEUE_PATH)
    if raw is None:
        confirm("Queue file exists.", "overnight/needs_manual_review.json",
                "file missing", False)
        results["B1_queue_readable"] = False
        return results

    try:
        queue = json.loads(raw)
    except json.JSONDecodeError as e:
        confirm("Queue parses as JSON.", "overnight/needs_manual_review.json",
                str(e), False)
        results["B1_queue_readable"] = False
        return results

    results["B1_queue_readable"] = True
    confirm("Queue parses as a JSON list.",
            "overnight/needs_manual_review.json",
            f"len={len(queue)}", isinstance(queue, list))

    # B2: all items are unique by (file, description)
    seen = set()
    dups = 0
    for item in queue:
        issue = item.get("issue") or {}
        key = (item.get("file", ""), issue.get("description", ""))
        if key in seen:
            dups += 1
        seen.add(key)
    results["B2_no_duplicates"] = (dups == 0)
    confirm("All queue items are unique by (file, description).",
            "overnight/needs_manual_review.json",
            f"unique={len(seen)} duplicates={dups}",
            dups == 0)

    # B3: file distribution
    file_counts = Counter(item.get("file", "?") for item in queue)
    top_files = file_counts.most_common(8)
    confirm("File distribution computed.",
            "overnight/needs_manual_review.json",
            f"{len(file_counts)} unique files; top 8: "
            + ", ".join(f"{n}={c}" for n, c in top_files),
            True)

    # B4: category distribution
    cat_counts = Counter(
        (item.get("issue") or {}).get("category", "?") for item in queue
    )
    confirm("Category distribution computed.",
            "overnight/needs_manual_review.json",
            ", ".join(f"{c}={n}" for c, n in cat_counts.most_common()),
            True)

    return results


# ===========================================================================
# Section C: current classifier applied to the queue
# ===========================================================================
def audit_classifier_application(queue: list[dict]) -> dict[str, int]:
    section("SECTION C: CURRENT CLASSIFIER APPLIED TO QUEUE")
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from overnight.self_improver import _classify_issue_for_routing
    except ImportError as e:
        confirm("Classifier importable.", "overnight/self_improver.py",
                str(e), False)
        return {}

    # Apply the classifier to each item. The classifier reads category,
    # severity, effort, impact, description. It does not write anything.
    results: Counter = Counter()
    local_tdd_items: list[dict] = []
    for item in queue:
        issue = item.get("issue") or {}
        try:
            route = _classify_issue_for_routing(issue)
        except Exception as e:
            route = f"error:{type(e).__name__}"
        results[route] += 1
        if route == "LOCAL_TDD":
            local_tdd_items.append({
                "file": item.get("file", "?"),
                "category": issue.get("category"),
                "severity": issue.get("severity"),
                "effort": issue.get("effort"),
                "impact": issue.get("impact"),
                "desc": str(issue.get("description", ""))[:120],
            })

    print()
    print(f"  Routing of {len(queue)} queue items (using live classifier):")
    for route, n in results.most_common():
        pct = 100.0 * n / len(queue)
        print(f"    {route:<12} {n:>4}  ({pct:>5.1f}%)")

    if local_tdd_items:
        section(f"LOCAL_TDD-eligible items ({len(local_tdd_items)})")
        for item in local_tdd_items:
            print(f"  {item['file']}")
            print(f"    cat={item['category']} sev={item['severity']} "
                  f"eff={item['effort']} imp={item['impact']}")
            print(f"    {item['desc']}")
            print()

    return dict(results)


# ===========================================================================
# Section D: test coverage
# ===========================================================================
def audit_test_coverage(queue: list[dict]) -> dict[str, int]:
    section("SECTION D: TEST COVERAGE OF BACKLOG FILES")

    unique_files = sorted({item.get("file", "?") for item in queue})
    tests_dir = REPO_ROOT / "tests"

    with_tests: list[tuple[str, int]] = []
    without_tests: list[str] = []

    for f in unique_files:
        stem = Path(f).stem
        matches = list(tests_dir.rglob(f"test_{stem}.py"))
        matches += list(tests_dir.rglob(f"test_*{stem}*.py"))
        matches += list(tests_dir.rglob(f"*{stem}*test*.py"))
        # Deduplicate by resolved path
        matches = list({p.resolve() for p in matches})
        if matches:
            with_tests.append((f, len(matches)))
        else:
            without_tests.append(f)

    print()
    print(f"  Files with tests:    {len(with_tests)} / {len(unique_files)}")
    print(f"  Files without tests: {len(without_tests)} / {len(unique_files)}")
    print()
    if without_tests:
        section("Files with NO tests")
        for f in without_tests:
            print(f"  {f}")

    return {
        "with_tests": len(with_tests),
        "without_tests": len(without_tests),
        "total": len(unique_files),
    }


# ===========================================================================
# Section E: trend
# ===========================================================================
def audit_trend() -> dict[str, int]:
    section("SECTION E: ESCALATION TREND")
    raw = read_text_safe(LEDGER_PATH)
    if raw is None:
        confirm("Ledger readable.", "overnight/improvement_ledger.jsonl",
                "missing", False)
        return {}

    now = datetime.now(timezone.utc)
    windows = {
        "last_7d": now - timedelta(days=7),
        "last_30d": now - timedelta(days=30),
        "last_90d": now - timedelta(days=90),
    }
    counts = {k: 0 for k in windows}
    total_escalated = 0
    total_records = 0
    malformed = 0

    for line in raw.splitlines():
        if not line.strip():
            continue
        total_records += 1
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if r.get("status") != "ESCALATED":
            continue
        total_escalated += 1
        ts_str = r.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            malformed += 1
            continue
        for key, cutoff in windows.items():
            if ts >= cutoff:
                counts[key] += 1

    print()
    print(f"  total ledger records: {total_records} (malformed={malformed})")
    print(f"  total ESCALATED:      {total_escalated}")
    print()
    for key, n in counts.items():
        pct = 100.0 * n / max(total_escalated, 1)
        print(f"  {key:<12} {n:>6}  ({pct:>5.1f}% of total escalations)")

    return {
        "total_records": total_records,
        "total_escalated": total_escalated,
        **counts,
    }


# ===========================================================================
# Main
# ===========================================================================
def main() -> int:
    print("soc-autopilot :: read-only TDD prompt change audit")

    header("SOURCES")
    for p in (SELF_IMPROVER, QUEUE_PATH, LEDGER_PATH, PROVEN_PATH):
        raw = read_text_safe(p)
        size = len(raw) if raw is not None else 0
        print(f"  {p.relative_to(REPO_ROOT)}: {size} chars"
              if raw is not None else
              f"  {p.relative_to(REPO_ROOT)}: MISSING")

    a_results = audit_source_assertions()
    b_results = audit_data_assertions()

    queue = []
    raw = read_text_safe(QUEUE_PATH)
    if raw:
        try:
            queue = json.loads(raw)
        except json.JSONDecodeError:
            queue = []

    c_results = audit_classifier_application(queue) if queue else {}
    d_results = audit_test_coverage(queue) if queue else {}
    e_results = audit_trend()

    header("SUMMARY OF ASSERTIONS")
    print()
    all_a = a_results
    for k, v in sorted(all_a.items()):
        print(f"  [{'OK' if v else 'FAIL'}]  {k}")

    print()
    print("  Classifier application:")
    for k, v in sorted(c_results.items()):
        print(f"    {k}: {v}")

    print()
    print("  Test coverage of backlog files:")
    for k, v in sorted(d_results.items()):
        print(f"    {k}: {v}")

    print()
    print("  Trend:")
    for k, v in sorted(e_results.items()):
        print(f"    {k}: {v}")

    print()
    print("  All reads completed. No writes were performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
