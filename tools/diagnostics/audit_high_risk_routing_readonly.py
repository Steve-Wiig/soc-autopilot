#!/usr/bin/env python3
"""
Read-only diagnostic: high-risk routing signal attribution.

For each item in the manual review queue, report:
  - which terms from _HIGH_RISK_ROUTING_TERMS matched, if any
  - the issue fields (category, severity, effort, impact)
  - whether the item would classify as LOCAL_TDD if the high-risk
    signal were removed

SAFETY DISCIPLINE
  * Path.read_text() only.
  * No writes, no subprocess, no network.
  * stdout only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
QUEUE_PATH = REPO_ROOT / "overnight" / "needs_manual_review.json"


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    from overnight.self_improver import (
        _ALWAYS_HIGH_RISK,
        _SEVERITY_GATED_HIGH_RISK,
    )
    # Combined view for the diagnostic. The runtime classifier gates
    # _SEVERITY_GATED_HIGH_RISK on severity; this diagnostic shows all
    # lexical matches regardless.
    _HIGH_RISK_ROUTING_TERMS = _ALWAYS_HIGH_RISK + _SEVERITY_GATED_HIGH_RISK

    if not QUEUE_PATH.is_file():
        print(f"Queue missing: {QUEUE_PATH}")
        return 1

    with open(QUEUE_PATH, "r", encoding="utf-8", errors="replace") as f:
        queue = json.load(f)

    print(f"queue items: {len(queue)}")
    print(f"HIGH_RISK tuple has {len(_HIGH_RISK_ROUTING_TERMS)} terms")
    print()

    term_hits: Counter = Counter()
    high_risk_count = 0
    would_be_local_if_no_high_risk = 0

    rows = []
    for item in queue:
        issue = item.get("issue") or {}
        desc = str(issue.get("description", "")).strip().lower()
        matched = [t for t in _HIGH_RISK_ROUTING_TERMS if t in desc]
        if matched:
            high_risk_count += 1
            for t in matched:
                term_hits[t] += 1

        cat = str(issue.get("category", "")).strip().lower()
        sev = str(issue.get("severity", "")).strip().lower()
        eff = str(issue.get("effort", "")).strip().lower()
        imp = str(issue.get("impact", "")).strip().lower()

        would_be_local = (
            cat in {"maintainability", "performance"}
            and sev in {"low", "informational"}
            and eff in {"trivial", "small"}
            and imp in {"low", "medium"}
        )
        if matched and would_be_local:
            would_be_local_if_no_high_risk += 1

        rows.append({
            "file": item.get("file", "?"),
            "category": cat,
            "severity": sev,
            "effort": eff,
            "impact": imp,
            "matched_terms": matched,
            "would_be_LOCAL_TDD_without_high_risk": would_be_local,
        })

    print(f"items that triggered high-risk signal: {high_risk_count} / {len(queue)}")
    print(f"  of those, would be LOCAL_TDD if high-risk were ignored: "
          f"{would_be_local_if_no_high_risk}")
    print()

    print("=== matched term frequency ===")
    for term, n in term_hits.most_common():
        print(f"  {n:>4}  {term!r}")

    print()
    print("=== field coverage ===")
    for field in ("category", "severity", "effort", "impact"):
        present = sum(1 for r in rows if r[field])
        print(f"  items with non-empty {field}: {present} / {len(rows)}")

    print()
    print("=== sample per top term ===")
    for term, _ in term_hits.most_common(4):
        print(f"\n--- matches for {term!r} ---")
        shown = 0
        for r in rows:
            if term in r["matched_terms"]:
                print(f"  {r['file']}")
                print(f"    cat={r['category']!r} sev={r['severity']!r} "
                      f"eff={r['effort']!r} imp={r['impact']!r}")
                print(f"    matched={r['matched_terms']}")
                shown += 1
                if shown >= 3:
                    break

    return 0


if __name__ == "__main__":
    sys.exit(main())
