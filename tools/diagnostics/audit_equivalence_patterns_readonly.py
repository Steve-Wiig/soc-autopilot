#!/usr/bin/env python3
"""
Read-only diagnostic: candidate equivalence pattern classification.

Answers:
  * Of the 14 proven fixes, which patterns account for the diffs?
  * Of the 27 failed fixes, which patterns were attempted?
  * Of the 137 backlog advisories, which would classify as each candidate
    SAFE_STRUCTURAL pattern?

SAFETY DISCIPLINE
  * Path.read_text() only.
  * No writes, no subprocess, no network, no env mutation.
  * stdout only.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OVERNIGHT = REPO_ROOT / "overnight"

QUEUE = OVERNIGHT / "needs_manual_review.json"
LEDGER = OVERNIGHT / "improvement_ledger.jsonl"
PROVEN = OVERNIGHT / "proven_fixes.jsonl"
FAILED = OVERNIGHT / "failed_fixes.jsonl"


# ===========================================================================
# Candidate patterns
# ===========================================================================
# Order matters. First matching pattern wins. Keep the SAFE_STRUCTURAL
# candidates first so that a behavior-changing match never masks them.
ADVISORY_PATTERNS = [
    # --- SAFE_STRUCTURAL candidates ---
    ("add_docstring", [
        r"\bdocstring",
        r"\bmissing documentation",
        r"\bmissing function docstring",
        r"\bmissing.*documenting",
        r"\bdocument.*parameters",
        r"\bdescribe.*parameters",
        r"\breturn type hint",
    ]),
    ("split_import", [
        r"multiple imports on (a )?single line",
        r"imports on single line",
        r"combine.*import",
        r"split.*import",
        r"multiple imports.*line",
    ]),
    ("extract_string_constant", [
        r"hardcoded string",
        r"extract.*literal",
        r"repeated literal",
        r"magic string",
        r"inline string",
        r"repeated regex",
        r"extract.*into a constant",
        r"literal into a constant",
    ]),
    ("extract_numeric_constant", [
        r"hardcoded max_tokens",
        r"hardcoded temperature",
        r"hardcoded.*\b(max|limit|threshold|timeout)\b",
        r"magic number",
    ]),
    ("add_type_annotation", [
        r"missing type hint",
        r"missing.*type annotation",
        r"add.*type hint",
        r"return type",
    ]),

    # --- behavior-adding (should NOT be classified structural) ---
    ("behavior_adding", [
        r"audit logging",
        r"missing audit",
        r"add.*sanitiz",
        r"missing.*sanitiz",
        r"silent exception",
        r"exception handling",
        r"missing.*logging",
        r"log.*decision",
        r"logging.*for",
        r"raise.*exception",
    ]),

    # --- behavior-preserving optimization ---
    ("behavior_preserving_optimization", [
        r"precompile",
        r"reads entire ledger",
        r"reads .* on each call",
        r"O\(N\) per",
        r"linear latency",
        r"memory pressure",
        r"redundant data",
        r"repeated allocation",
    ]),

    # --- structural refactoring (borderline) ---
    ("structural_refactor", [
        r"extract.*function",
        r"extract.*method",
        r"refactor",
        r"split.*function",
        r"combine.*functions",
        r"rename.*variable",
    ]),
]


def classify_advisory(text: str) -> str:
    """Classify an advisory by its description. Returns pattern name or 'unknown'."""
    if not text:
        return "unknown"
    t = text.lower()
    for pattern, keywords in ADVISORY_PATTERNS:
        for kw in keywords:
            if re.search(kw, t):
                return pattern
    return "unknown"


# ===========================================================================
# Diff classification (for proven/failed fixes)
# ===========================================================================
def parse_diff_blocks(diff_text: str) -> list[tuple[str, str]]:
    """Extract (search, replace) pairs from an aider-style diff."""
    pattern = re.compile(
        r'<<<<<<<?\s*\S+\s*\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE',
        re.DOTALL,
    )
    return [(m.group(1), m.group(2)) for m in pattern.finditer(diff_text)]


def classify_diff(diff_text: str) -> tuple[str, str]:
    """Return (pattern, evidence). Heuristic. Honest about uncertainty."""
    blocks = parse_diff_blocks(diff_text)
    if not blocks:
        return ("unknown", "no SEARCH/REPLACE blocks found")

    # Look at the largest block for classification
    search, replace = max(blocks, key=lambda b: len(b[1]))

    s_has_docstring = '"""' in search or "'''" in search
    r_has_docstring = '"""' in replace or "'''" in replace
    if r_has_docstring and not s_has_docstring:
        return ("add_docstring", "adds triple-quoted docstring")

    if re.search(r"^import\s+\w+\s*,\s*\w+", search, re.MULTILINE):
        if replace.count("\nimport ") >= 1 or replace.count("\nfrom ") >= 1:
            return ("split_import", "comma-separated imports split across lines")

    s_literals = len(re.findall(r'"[^"]{3,}"', search) + re.findall(r"'[^']{3,}'", search))
    r_literals = len(re.findall(r'"[^"]{3,}"', replace) + re.findall(r"'[^']{3,}'", replace))
    if r_literals > s_literals and len(replace) > len(search):
        return ("behavior_adding", "adds string literal(s) — likely logging or message")

    s_returns = re.findall(r"\breturn\b", search)
    r_returns = re.findall(r"\breturn\b", replace)
    if s_returns and r_returns and s_returns != r_returns:
        return ("behavior_adding", "return structure changed")

    if re.search(r"^def ", replace, re.MULTILINE) and not re.search(r"^def ", search, re.MULTILINE):
        return ("structural_refactor", "adds a new function definition")

    if len(replace) > len(search) * 1.5:
        return ("behavior_adding", "replace block substantially larger")

    if len(replace) < len(search):
        return ("removal_or_simplification", "replace shorter than search")

    return ("unknown", f"unclassified ({len(search)} → {len(replace)} chars)")


# ===========================================================================
# I/O
# ===========================================================================
def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def read_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


# ===========================================================================
# Reporting
# ===========================================================================
def header(t: str) -> None:
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


def section(t: str) -> None:
    print()
    print(f"--- {t} ---")


def truncate(s, n=100):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ===========================================================================
# Main
# ===========================================================================
def main() -> int:
    print("soc-autopilot :: read-only equivalence pattern diagnostic")

    proven = read_jsonl(PROVEN)
    failed = read_jsonl(FAILED)
    queue = read_json(QUEUE) or []
    ledger = read_jsonl(LEDGER)

    print(f"proven_fixes records: {len(proven)}")
    print(f"failed_fixes records: {len(failed)}")
    print(f"manual review queue:  {len(queue)}")
    print(f"ledger records:       {len(ledger)}")

    # ------------------------------------------------------------------
    # 1. Proven fixes — ground truth by diff shape
    # ------------------------------------------------------------------
    header("1. PROVEN FIXES — actual diff shapes (ground truth)")
    proven_class: Counter = Counter()
    proven_samples: dict[str, list[tuple]] = defaultdict(list)

    for r in proven:
        pattern, evidence = classify_diff(r.get("fix_diff", ""))
        proven_class[pattern] += 1
        proven_samples[pattern].append((
            r.get("category", "?"),
            r.get("file", "?"),
            r.get("advisory", ""),
            evidence,
        ))

    print(f"{'pattern':<36} {'count':>6}  {'%':>6}")
    print("-" * 60)
    total_proven = max(len(proven), 1)
    for pattern, n in proven_class.most_common():
        print(f"  {pattern:<34} {n:>6}  {100*n/total_proven:>5.1f}%")

    for pattern in proven_class:
        section(f"proven samples: {pattern}")
        for cat, file, adv, ev in proven_samples[pattern][:4]:
            print(f"  [{cat}] {file}")
            print(f"    advisory: {truncate(adv, 110)}")
            print(f"    evidence: {ev}")

    # ------------------------------------------------------------------
    # 2. Failed fixes — attempted shapes
    # ------------------------------------------------------------------
    header("2. FAILED FIXES — attempted diff shapes")
    failed_class: Counter = Counter()
    for r in failed:
        pattern, _ = classify_diff(r.get("failed_diff", ""))
        failed_class[pattern] += 1

    total_failed = max(len(failed), 1)
    print(f"{'pattern':<36} {'count':>6}  {'%':>6}")
    print("-" * 60)
    for pattern, n in failed_class.most_common():
        print(f"  {pattern:<34} {n:>6}  {100*n/total_failed:>5.1f}%")

    # ------------------------------------------------------------------
    # 3. Backlog advisories — potential unlock
    # ------------------------------------------------------------------
    header("3. MANUAL REVIEW BACKLOG — pattern potential (advisory text)")
    queue_class: Counter = Counter()
    queue_samples: dict[str, list] = defaultdict(list)

    for item in queue:
        issue = item.get("issue") or {}
        desc = str(issue.get("description", ""))
        category = str(issue.get("category", "?"))
        pattern = classify_advisory(desc)
        queue_class[pattern] += 1
        queue_samples[pattern].append({
            "id": None,  # not available in queue file
            "file": item.get("file", "?"),
            "category": category,
            "desc": desc,
        })

    total_queue = max(len(queue), 1)
    print(f"{'pattern':<36} {'count':>6}  {'%':>6}")
    print("-" * 60)
    for pattern, n in queue_class.most_common():
        print(f"  {pattern:<34} {n:>6}  {100*n/total_queue:>5.1f}%")

    # Print samples for the SAFE_STRUCTURAL candidates
    SAFE_CANDIDATES = {
        "add_docstring",
        "split_import",
        "extract_string_constant",
        "extract_numeric_constant",
        "add_type_annotation",
    }
    for pattern in SAFE_CANDIDATES:
        if pattern not in queue_samples:
            continue
        section(f"backlog samples: {pattern} ({len(queue_samples[pattern])} items)")
        for s in queue_samples[pattern][:8]:
            print(f"  {s['file']}  [{s['category']}]")
            print(f"    {truncate(s['desc'], 130)}")

    # ------------------------------------------------------------------
    # 4. Historical escalations — trend
    # ------------------------------------------------------------------
    header("4. HISTORICAL ESCALATIONS — pattern trend (ledger)")
    hist_class: Counter = Counter()
    for r in ledger:
        if r.get("status") != "ESCALATED":
            continue
        pattern = classify_advisory(str(r.get("reason", "")))
        hist_class[pattern] += 1

    print(f"{'pattern':<36} {'count':>6}")
    print("-" * 60)
    for pattern, n in hist_class.most_common():
        print(f"  {pattern:<34} {n:>6}")

    # ------------------------------------------------------------------
    # 5. Shipping plan
    # ------------------------------------------------------------------
    header("5. SHIPPING PLAN — recommended pattern rollout order")

    print()
    print("  Per pattern: backlog count, complexity, recommendation")
    print()
    print(f"  {'pattern':<28} {'backlog':>8} {'proven':>8} {'difficulty':<12} verdict")
    print("  " + "-" * 90)

    def diff_difficulty(pattern: str) -> str:
        if pattern == "add_docstring":
            return "easy"
        if pattern == "split_import":
            return "easy"
        if pattern == "extract_string_constant":
            return "medium"
        if pattern == "extract_numeric_constant":
            return "medium"
        if pattern == "add_type_annotation":
            return "medium"
        return "n/a"

    def verdict(pattern: str, backlog_n: int, proven_n: int) -> str:
        if pattern in ("add_docstring", "split_import"):
            if proven_n >= 2:
                return "SHIP (evidence + high value)"
            return "SHIP (high value)"
        if pattern in ("extract_string_constant", "extract_numeric_constant"):
            if proven_n >= 1 and backlog_n >= 3:
                return "SHIP after v1"
            return "consider after v1"
        if pattern == "add_type_annotation":
            return "consider after v1"
        return "defer"

    SAFE_ORDER = [
        "add_docstring",
        "split_import",
        "extract_string_constant",
        "extract_numeric_constant",
        "add_type_annotation",
    ]
    for pattern in SAFE_ORDER:
        b = queue_class.get(pattern, 0)
        p = proven_class.get(pattern, 0)
        print(f"  {pattern:<28} {b:>8} {p:>8} {diff_difficulty(pattern):<12} {verdict(pattern, b, p)}")

    print()
    print("  Notes:")
    print("    * 'proven' is the count of proven fixes whose diff shape matched.")
    print("    * 'backlog' is the count of advisories whose text suggests the pattern.")
    print("    * The v1 pattern set should be the two 'easy' patterns.")
    print("    * Everything else falls through to the existing RED-phase path.")

    print()
    print("  All reads completed. No writes were performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
