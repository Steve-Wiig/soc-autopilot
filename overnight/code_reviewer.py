#!/usr/bin/env python3
"""
Dual-Model Code Reviewer for soc-autopilot.

Uses NVIDIA Nemotron (via OpenRouter) to analyze code and suggest improvements,
then Gemini (via Google) to validate, prioritize, and catch false positives.

Architecture:
  Nemotron (1M context, code-specialized)
    ↓ identifies improvements
  Gemini (different training data, strong reasoning)
    ↓ validates, prioritizes, catches false positives
  Final Report (ranked by impact, severity, effort)

Output:
  overnight/reviews/<filename>.review.json  (per-file structured review)
  overnight/reviews/SUMMARY.md              (consolidated report)

Usage:
  python3 overnight/code_reviewer.py                    # Review all source files
  python3 overnight/code_reviewer.py engine/            # Review specific directory
  python3 overnight/code_reviewer.py engine/queue_manager.py  # Review single file
  python3 overnight/code_reviewer.py --dry-run          # Preview without writing
"""
import ast
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from overnight.llm_client import (
    generate, critique, load_api_keys, strip_fences,
    GENERATOR_MODEL, CRITIC_MODEL, gemini_pre_analysis
)

# ============================================================
# CONFIGURATION
# ============================================================
ROOT = Path("/home/swiig/Documents/soc-autopilot")
REVIEWS_DIR = ROOT / "overnight" / "reviews"
PROGRESS_FILE = ROOT / "overnight" / "reviews" / "progress.json"
SUMMARY_FILE = ROOT / "overnight" / "reviews" / "SUMMARY.md"

# Directories to skip
SKIP_DIRS = {".venv", "__pycache__", "overnight", ".git", "node_modules", "tests"}

# Focus areas for improvements (tied to blueprint concerns)
IMPROVEMENT_CATEGORIES = [
    "security",          # Unsanitized payloads, secrets, missing validation
    "reliability",       # Missing error handling, retries, edge cases
    "performance",       # N+1 queries, inefficient loops, missing indexes
    "correctness",       # Logic bugs, off-by-one, race conditions
    "maintainability",   # Missing docstrings, type hints, naming
    "documentation_compliance",  # datetime.utcnow, sys.exit, sqlite mocking
    "test_coverage",     # Untested functions, weak assertions
]

SEVERITY_LEVELS = ["critical", "high", "medium", "low", "informational"]

RATE_LIMIT_SLEEP = 4  # Seconds between API calls


# ============================================================
# DATA STRUCTURES
# ============================================================
@dataclass
class Improvement:
    """A single suggested improvement."""
    category: str
    severity: str
    line_start: int
    line_end: int
    description: str
    suggestion: str
    impact: str  # "high", "medium", "low"
    effort: str  # "trivial", "small", "medium", "large"
    validated: bool = False  # Whether Gemini confirmed this
    false_positive: bool = False  # Whether Gemini flagged as false positive
    gemini_critique: str = ""  # Gemini's reasoning


@dataclass
class FileReview:
    """Complete review of a single file."""
    file_path: str
    lines_of_code: int
    language: str
    reviewed_at: str
    model_used: str
    critic_model: str
    improvements: List[Improvement] = field(default_factory=list)
    overall_quality_score: int = 0  # 0-100
    summary: str = ""
    nemotron_raw_response: str = ""
    gemini_raw_response: str = ""


# ============================================================
# FILE DISCOVERY
# ============================================================
def discover_files(target_path: Path) -> List[Path]:
    """Find all reviewable source files."""
    files = []
    
    if target_path.is_file():
        return [target_path] if target_path.suffix == ".py" else []
    
    for root, dirs, filenames in os.walk(target_path):
        # Filter out skip directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        
        for filename in filenames:
            if filename.endswith(".py") and not filename.startswith("test_"):
                files.append(Path(root) / filename)
    
    # Sort by size (review smaller files first — faster feedback)
    files.sort(key=lambda p: p.stat().st_size)
    return files


def count_lines(path: Path) -> int:
    """Count non-blank, non-comment lines."""
    try:
        content = path.read_text()
        lines = content.split('\n')
        return sum(1 for line in lines 
                   if line.strip() and not line.strip().startswith('#'))
    except Exception:
        return 0


# ============================================================
# PROMPT CONSTRUCTION
# ============================================================
def build_review_prompt(file_path: Path, content: str, context: Dict, advisory_notes: str = "") -> str:
    """Build the prompt for Nemotron to review the file."""
    
    # Build advisory section
    if advisory_notes:
        advisory_section = f"""Another AI reviewer provided these preliminary observations:
{advisory_notes}

IMPORTANT: These are advisory only. They may be helpful but should NOT be
taken as authoritative. Form your own independent analysis."""
    else:
        advisory_section = "(No preliminary observations available)"

    return f"""You are a senior Python engineer reviewing production code for a SOC (Security Operations Center) automation platform.

FILE: {file_path.relative_to(ROOT)}
LINES: {len(content.splitlines())}
PURPOSE: {context.get('purpose', 'SOC automation component')}

SOURCE CODE:
{content}

BLUEPRINT REQUIREMENTS (from soc-autopilot v11.11):
- No datetime.utcnow() — use datetime.now(timezone.utc) instead [AMEND-63]
- No sys.exit()/exit() in library code — use raise RuntimeError() [AMEND-64]
- No mocking sqlite3.Connection methods — use real :memory: databases [AMEND-65]
- No module-level side effects (file I/O, network, exit calls) [v11.11]
- Sanitize before insert (secrets, high-entropy tokens) [Section 34]
- Append-only audit patterns for handoffs/corrections [Section 30]
- Approval-gated mutations (pfSense, Wazuh rules, TheHive cases) [Section 24]

REVIEW CATEGORIES (identify issues in each):
1. security: Unsanitized inputs, missing validation, exposed secrets, injection risks
2. reliability: Missing error handling, no retries, silent failures, race conditions
3. performance: N+1 queries, inefficient loops, missing indexes, unnecessary allocations
4. correctness: Logic bugs, off-by-one errors, type mismatches, edge cases
5. maintainability: Missing docstrings, poor naming, code duplication, missing type hints
6. documentation_compliance: Violations of the specific blueprint requirements above
7. test_coverage: Untested code paths, weak assertions, missing edge case tests

OUTPUT FORMAT:
Return a JSON array of improvement objects. Each object must have:
- category: one of the 7 categories above
- severity: critical | high | medium | low | informational
- line_start: integer (first line of the issue)
- line_end: integer (last line of the issue, same as line_start for single-line)
- description: clear explanation of the problem
- suggestion: concrete code-level fix
- impact: high | medium | low (business/operational impact)
- effort: trivial | small | medium | large (implementation effort)

Example:
[
  {{
    "category": "security",
    "severity": "high",
    "line_start": 42,
    "line_end": 45,
    "description": "User input passed directly to SQL query without sanitization",
    "suggestion": "Use parameterized queries: cursor.execute('SELECT * FROM x WHERE id = ?', (user_id,))",
    "impact": "high",
    "effort": "trivial"
  }}
]

RULES:
- CRITICAL: Your entire response must be ONLY a valid JSON array. Nothing else.
- Do NOT write any explanation, analysis, or commentary before or after the JSON.
- Do NOT wrap the JSON in markdown code fences.
- Do NOT start with "Let me analyze" or "Here is" or any other preamble.
- Start your response with [ and end with ]
- Be specific with line numbers. Don't guess — use the actual lines.
- Prioritize genuine issues over stylistic preferences.
- Don't flag things that are clearly intentional (e.g., demo code in __main__ blocks).
- Maximum 20 improvements per file (focus on highest-impact issues).
- If the file is clean, return an empty array: []

Remember: ONLY output the JSON array. No other text whatsoever.

ADVISORY CONTEXT (from another reviewer — NOT authoritative):
{advisory_section}

The above observations are preliminary and may be incomplete or incorrect.
Use them as a starting point if helpful, but form your OWN independent analysis.
You may agree, disagree, or find entirely different issues.

Analyze the file now. Output ONLY the JSON array:"""


def build_validation_prompt(file_path: Path, content: str, improvements_json: str) -> str:
    """Build the prompt for Gemini to validate Nemotron's suggestions."""
    
    return f"""You are a senior code reviewer validating another engineer's code review.

FILE: {file_path.relative_to(ROOT)}

SOURCE CODE:
{content}

PROPOSED IMPROVEMENTS (from another reviewer):
{improvements_json}

YOUR TASK:
For each proposed improvement, determine:
1. Is it a GENUINE issue or a FALSE POSITIVE?
2. If genuine, is the severity correctly rated?
3. Is the suggestion practical and correct?

OUTPUT FORMAT:
Return a JSON object with:
- validated_improvements: array of improvement objects with added fields:
  - validated: true/false (is this a real issue?)
  - false_positive: true/false (is this a false positive?)
  - gemini_critique: string (your reasoning, 1-3 sentences)
  - adjusted_severity: the corrected severity (if different)
- overall_quality_score: 0-100 (file quality)
- summary: 2-3 sentence overall assessment
- false_positive_count: integer
- genuine_issue_count: integer

Example:
{{
  "validated_improvements": [
    {{
      "category": "security",
      "severity": "high",
      "line_start": 42,
      "line_end": 45,
      "description": "...",
      "suggestion": "...",
      "validated": true,
      "false_positive": false,
      "gemini_critique": "This is a real SQL injection risk. Parameterized queries are the correct fix.",
      "adjusted_severity": "high"
    }}
  ],
  "overall_quality_score": 72,
  "summary": "Solid code with good error handling. Main concern is SQL injection in the query builder.",
  "false_positive_count": 1,
  "genuine_issue_count": 4
}}

RULES:
- CRITICAL: Your entire response must be ONLY a valid JSON object. Nothing else.
- Do NOT write any explanation, analysis, or commentary before or after the JSON.
- Do NOT wrap the JSON in markdown code fences.
- Start your response with {{ and end with }}
- Be skeptical — flag false positives aggressively.
- If a suggestion is technically correct but low-impact, mark it low severity.
- If a suggestion misunderstands the code's intent, mark it false positive.
- Verify line numbers actually correspond to the described issue.

Remember: ONLY output the JSON object. No other text whatsoever.

Validate now. Output ONLY the JSON object:"""


# ============================================================
# EXTRACTION & PARSING
# ============================================================
def extract_json_from_response(response: str) -> Optional[Any]:
    """Extract JSON, preferring a list-of-dicts (the improvements array)."""
    if not response:
        return None

    response = strip_fences(response)
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    def _clean(c):
        return re.sub(r",\s*([}\]])", r"\1", c)

    def _try_parse(c):
        for text in (c, _clean(c)):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
        return None

    def _balanced_end(text, start):
        open_ch = text[start]
        close_ch = "]" if open_ch == "[" else "}"
        depth = 0; in_str = False; esc = False
        for j in range(start, len(text)):
            c = text[j]
            if in_str:
                if esc: esc = False
                elif c == "\\": esc = True
                elif c == '"': in_str = False
            else:
                if c == '"': in_str = True
                elif c == open_ch: depth += 1
                elif c == close_ch:
                    depth -= 1
                    if depth == 0: return j
        return -1

    candidates = []
    i = 0; n = len(response)
    while i < n:
        if response[i] in "[{":
            end = _balanced_end(response, i)
            if end != -1:
                parsed = _try_parse(response[i:end + 1])
                if parsed is not None:
                    candidates.append(parsed)
                i = end + 1
                continue
        i += 1

    if not candidates:
        for s, e in [("[", "]"), ("{", "}")]:
            si, ei = response.find(s), response.rfind(e)
            if si != -1 and ei != -1 and ei > si:
                parsed = _try_parse(response[si:ei + 1])
                if parsed is not None:
                    candidates.append(parsed)

    if not candidates:
        return None

    def _score(c):
        if isinstance(c, list) and c and all(isinstance(x, dict) for x in c):
            return 3   # improvements array
        if isinstance(c, list) and c:
            return 2
        if isinstance(c, dict) and c:
            return 1
        return 0

    return max(candidates, key=lambda c: (_score(c), len(json.dumps(c))))


def get_file_context(file_path: Path) -> Dict:
    """Determine the purpose/context of a file based on path."""
    rel_path = str(file_path.relative_to(ROOT))
    
    if "engine/intake" in rel_path:
        return {"purpose": "Alert intake adapter"}
    elif "engine/writeback" in rel_path:
        return {"purpose": "Writeback adapter to external platform"}
    elif "engine/" in rel_path:
        return {"purpose": "Core enrichment engine component"}
    elif "orchestrator/" in rel_path:
        return {"purpose": "Orchestration/routing component"}
    elif "memory/" in rel_path:
        return {"purpose": "Memory/embedding/retention service"}
    elif "tools/" in rel_path:
        return {"purpose": "CI verification tool"}
    else:
        return {"purpose": "SOC automation component"}


# ============================================================
# REVIEW EXECUTION
# ============================================================
def review_file(file_path: Path, api_keys: Dict, dry_run: bool = False,
                show_prompts: bool = False) -> Optional[FileReview]:
    """Review a single file using dual-model pipeline.
    
    Flow:
    1. Nemotron analyzes freely (thinking/reasoning text accepted)
    2. Gemini extracts structured improvements from Nemotron's analysis
    3. Gemini validates its own extraction (self-check)
    """

    try:
        content = file_path.read_text()
    except Exception as e:
        print(f"  ⚠️  Could not read {file_path}: {e}")
        return None

    loc = count_lines(file_path)
    context = get_file_context(file_path)

    print(f"\n{'='*70}")
    print(f"REVIEWING: {file_path.relative_to(ROOT)}")
    print(f"{'='*70}")
    print(f"  Lines: {loc} | Context: {context['purpose']}")

    # ---- STEP 0: Gemini pre-analysis (advisory, uses abundant free tier) ----
    print(f"\n  [0/3] 📝 Gemini pre-analysis (advisory)...")
    advisory_notes = gemini_pre_analysis(file_path.relative_to(ROOT), content, api_keys)

    # ---- STEP 1: OpenRouter primary analysis (authoritative) ----
    print(f"\n  [1/3] 🤖 OpenRouter primary analysis...")
    review_prompt = build_review_prompt(file_path, content, context, advisory_notes=advisory_notes)

    if show_prompts:
        print(f"\n  --- PROMPT (first 500 chars) ---")
        print(f"  {review_prompt[:500]}...")

    if dry_run:
        print(f"  [DRY RUN] Would call Nemotron with {len(review_prompt)} chars")
        return None

    time.sleep(RATE_LIMIT_SLEEP)
    nemotron_response = generate(review_prompt, api_keys, model_type="code", temperature=0.3)

    if not nemotron_response:
        print(f"  ⚠️  Nemotron returned empty response")
        return None

    # Accept ANY response from Nemotron (JSON or prose)
    # First try to parse as JSON directly
    direct_json = extract_json_from_response(nemotron_response)
    
    if direct_json and isinstance(direct_json, list):
        print(f"  ✅ Nemotron returned valid JSON directly ({len(direct_json)} improvements)")
        improvements_raw = direct_json
    else:
        # Nemotron gave prose/thinking — that's fine, Gemini will extract structure
        print(f"  📝 Nemotron returned free-form analysis ({len(nemotron_response)} chars)")
        
        if show_prompts:
            print(f"\n  --- NEMOTRON ANALYSIS (first 500 chars) ---")
            print(f"  {nemotron_response[:500]}...")
        
        # STEP 1b: Ask Gemini to extract structured JSON from Nemotron's analysis
        print(f"  🔄 Asking Gemini to extract structured improvements...")
        
        extraction_prompt = f"""A code reviewer analyzed a Python file and wrote the following analysis:

FILE: {file_path.relative_to(ROOT)}

SOURCE CODE:
{content}

REVIEWER'S ANALYSIS:
{nemotron_response[:4000]}

Extract all improvement suggestions from the analysis above into a JSON array.
Each object must have:
- category: security | reliability | performance | correctness | maintainability | documentation_compliance | test_coverage
- severity: critical | high | medium | low | informational
- line_start: integer
- line_end: integer
- description: string
- suggestion: string
- impact: high | medium | low
- effort: trivial | small | medium | large

CRITICAL: Output ONLY the JSON array. No explanation. No markdown.
Start with [ and end with ]. If no issues found, output: []"""

        time.sleep(RATE_LIMIT_SLEEP)
        from overnight.llm_client import _call_gemini
        extraction_response = _call_gemini(extraction_prompt, api_keys["gemini"], max_tokens=4096, temperature=0.1)
        
        if not extraction_response:
            print(f"  ⚠️  Gemini extraction returned empty response")
            return None
        
        improvements_raw = extract_json_from_response(extraction_response)
        if improvements_raw is None or not isinstance(improvements_raw, list):
            print(f"  ⚠️  Could not extract structured improvements from analysis")
            if show_prompts:
                print(f"  Gemini response preview: {(extraction_response or '')[:300]}")
            return None
        
        print(f"  ✅ Gemini extracted {len(improvements_raw)} improvements from Nemotron's analysis")

    # ---- STEP 2: Build Improvement objects ----
    improvements = []
    for item in improvements_raw[:20]:
        try:
            imp = Improvement(
                category=item.get("category", "maintainability"),
                severity=item.get("severity", "low"),
                line_start=int(item.get("line_start", 1)),
                line_end=int(item.get("line_end", item.get("line_start", 1))),
                description=item.get("description", ""),
                suggestion=item.get("suggestion", ""),
                impact=item.get("impact", "low"),
                effort=item.get("effort", "small"),
            )
            improvements.append(imp)
        except (ValueError, TypeError) as e:
            print(f"  ⚠️  Skipping malformed improvement: {e}")

    if not improvements:
        print(f"  ✅ No improvements identified — file appears clean")
        review = FileReview(
            file_path=str(file_path.relative_to(ROOT)),
            lines_of_code=loc,
            language="python",
            reviewed_at=datetime.now().isoformat(),
            model_used=GENERATOR_MODEL,
            critic_model=CRITIC_MODEL,
            improvements=[],
            overall_quality_score=90,
            summary="No issues identified. Code appears clean.",
            nemotron_raw_response=nemotron_response[:2000],
            gemini_raw_response="",
        )
        return review

    print(f"  📋 {len(improvements)} potential improvements to validate")

    # ---- STEP 3: Gemini validates the improvements ----
    print(f"\n  [2/3] 🔍 Gemini validating...")
    improvements_json = json.dumps([asdict(imp) for imp in improvements], indent=2)
    validation_prompt = build_validation_prompt(file_path, content, improvements_json)

    if show_prompts:
        print(f"\n  --- VALIDATION PROMPT (first 500 chars) ---")
        print(f"  {validation_prompt[:500]}...")

    time.sleep(RATE_LIMIT_SLEEP)
    from overnight.llm_client import _call_gemini
    gemini_response = _call_gemini(validation_prompt, api_keys["gemini"], max_tokens=4096, temperature=0.1)

    if not gemini_response:
        print(f"  ⚠️  Gemini returned empty response, using improvements as-is")
        quality_score = 70
        summary = "Review completed but Gemini validation unavailable"
        for imp in improvements:
            imp.validated = True
    else:
        if show_prompts:
            print(f"\n  --- GEMINI RESPONSE (first 500 chars) ---")
            print(f"  {gemini_response[:500]}...")

        validation_data = extract_json_from_response(gemini_response)

        if validation_data and isinstance(validation_data, dict):
            validated_imps = validation_data.get("validated_improvements", [])
            for i, imp in enumerate(improvements):
                if i < len(validated_imps):
                    vi = validated_imps[i]
                    imp.validated = vi.get("validated", True)
                    imp.false_positive = vi.get("false_positive", False)
                    imp.gemini_critique = vi.get("gemini_critique", "")
                    if vi.get("adjusted_severity"):
                        imp.severity = vi["adjusted_severity"]

            quality_score = int(validation_data.get("overall_quality_score", 70))
            summary = validation_data.get("summary", "")

            genuine = sum(1 for imp in improvements if imp.validated and not imp.false_positive)
            false_pos = sum(1 for imp in improvements if imp.false_positive)
            print(f"  ✅ Gemini validated: {genuine} genuine, {false_pos} false positives")
            print(f"  📊 Quality score: {quality_score}/100")
        else:
            print(f"  ⚠️  Could not parse Gemini validation, using improvements as-is")
            quality_score = 70
            summary = "Review completed but validation parsing failed"
            for imp in improvements:
                imp.validated = True

    # ---- STEP 4: Assemble review ----
    print(f"\n  [3/3] 📋 Assembling review...")

    review = FileReview(
        file_path=str(file_path.relative_to(ROOT)),
        lines_of_code=loc,
        language="python",
        reviewed_at=datetime.now().isoformat(),
        model_used=GENERATOR_MODEL,
        critic_model=CRITIC_MODEL,
        improvements=improvements,
        overall_quality_score=quality_score,
        summary=summary,
        nemotron_raw_response=nemotron_response[:2000],
        gemini_raw_response=(gemini_response or "")[:2000],
    )

    # Print summary
    genuine = [i for i in improvements if i.validated and not i.false_positive]
    by_severity = {}
    for imp in genuine:
        by_severity[imp.severity] = by_severity.get(imp.severity, 0) + 1

    print(f"\n  📊 FINAL RESULTS:")
    print(f"     Quality: {quality_score}/100")
    print(f"     Total suggestions: {len(improvements)}")
    print(f"     Genuine issues: {len(genuine)}")
    if by_severity:
        print(f"     By severity: {by_severity}")
    if summary:
        print(f"     Summary: {summary[:150]}...")

    return review



# ============================================================
# PERSISTENCE
# ============================================================
def load_progress() -> Dict:
    """Load progress state."""
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"reviewed": [], "skipped": []}


def save_progress(progress: Dict):
    """Save progress state."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def save_review(review: FileReview):
    """Save a single file review."""
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Use sanitized filename
    safe_name = review.file_path.replace("/", "__").replace(".py", "")
    review_path = REVIEWS_DIR / f"{safe_name}.review.json"
    review_path.write_text(json.dumps(asdict(review), indent=2))


def generate_summary():
    """Generate consolidated SUMMARY.md from all reviews."""
    if not REVIEWS_DIR.exists():
        print("No reviews found")
        return
    
    reviews = []
    for f in REVIEWS_DIR.glob("*.review.json"):
        if f.name == "progress.json":
            continue
        try:
            data = json.loads(f.read_text())
            reviews.append(data)
        except Exception:
            continue
    
    if not reviews:
        print("No valid reviews found")
        return
    
    # Aggregate stats
    total_files = len(reviews)
    total_improvements = sum(len(r["improvements"]) for r in reviews)
    genuine_improvements = sum(
        sum(1 for imp in r["improvements"] if imp.get("validated") and not imp.get("false_positive"))
        for r in reviews
    )
    false_positives = sum(
        sum(1 for imp in r["improvements"] if imp.get("false_positive"))
        for r in reviews
    )
    
    avg_quality = sum(r["overall_quality_score"] for r in reviews) / total_files if reviews else 0
    
    # Categorize improvements
    by_category = {}
    by_severity = {}
    high_impact = []
    
    for r in reviews:
        for imp in r["improvements"]:
            if not imp.get("validated") or imp.get("false_positive"):
                continue
            cat = imp.get("category", "other")
            sev = imp.get("severity", "low")
            by_category[cat] = by_category.get(cat, 0) + 1
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if imp.get("impact") == "high" and sev in ("critical", "high"):
                high_impact.append({
                    "file": r["file_path"],
                    "category": cat,
                    "severity": sev,
                    "description": imp["description"],
                    "suggestion": imp["suggestion"],
                })
    
    # Build summary markdown
    md = f"""# soc-autopilot Code Review Summary

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Reviewer Models:** {GENERATOR_MODEL} (analysis) + {CRITIC_MODEL} (validation)

## Executive Summary

| Metric | Value |
|---|---|
| Files reviewed | {total_files} |
| Total suggestions | {total_improvements} |
| Genuine issues | {genuine_improvements} |
| False positives caught | {false_positives} |
| False positive rate | {100*false_positives/max(total_improvements,1):.1f}% |
| Average quality score | {avg_quality:.1f}/100 |

## Issue Breakdown

### By Category

| Category | Count |
|---|---|
"""
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        md += f"| {cat} | {count} |\n"
    
    md += "\n### By Severity\n\n| Severity | Count |\n|---|---|\n"
    for sev in SEVERITY_LEVELS:
        if sev in by_severity:
            md += f"| {sev} | {by_severity[sev]} |\n"
    
    if high_impact:
        md += f"\n## High-Impact Issues (Priority Fixes)\n\n"
        for i, issue in enumerate(high_impact[:10], 1):
            md += f"### {i}. {issue['file']} ({issue['severity']})\n\n"
            md += f"**Category:** {issue['category']}\n\n"
            md += f"**Issue:** {issue['description']}\n\n"
            md += f"**Fix:** {issue['suggestion']}\n\n---\n\n"
    
    md += "\n## Per-File Reviews\n\n"
    for r in sorted(reviews, key=lambda x: x["overall_quality_score"]):
        genuine_count = sum(1 for imp in r["improvements"] 
                           if imp.get("validated") and not imp.get("false_positive"))
        md += f"- **{r['file_path']}** — {r['overall_quality_score']}/100, {genuine_count} issues\n"
    
    md += f"""
## Learning Insights

### False Positive Patterns
The Gemini critic caught {false_positives} false positives. Common patterns:
- Flagging intentional demo code in `__main__` blocks
- Misunderstanding error handling that's actually correct
- Suggesting optimizations that would reduce readability

### Most Common Issues
"""
    top_cats = sorted(by_category.items(), key=lambda x: -x[1])[:3]
    for cat, count in top_cats:
        md += f"- **{cat}**: {count} occurrences\n"
    
    md += """
## Next Steps

1. Review the high-impact issues above first
2. Open individual `.review.json` files for detailed line-by-line feedback
3. Implement fixes incrementally, running pytest after each change
4. Re-run the reviewer after fixes to verify improvements
"""
    
    SUMMARY_FILE.write_text(md)
    print(f"\n✅ Summary written to {SUMMARY_FILE.relative_to(ROOT)}")


# ============================================================
# MAIN
# ============================================================
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Dual-model code reviewer")
    parser.add_argument("path", nargs="?", default=".", 
                        help="File or directory to review (default: entire project)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be reviewed without calling APIs")
    parser.add_argument("--show-prompts", action="store_true",
                        help="Print the actual prompts sent to LLMs (learning mode)")
    parser.add_argument("--max-files", type=int, default=50,
                        help="Maximum files to review in one run (default: 50)")
    parser.add_argument("--reset", action="store_true",
                        help="Reset progress and re-review all files")
    parser.add_argument("--summary-only", action="store_true",
                        help="Only regenerate the summary from existing reviews")
    args = parser.parse_args()
    
    # Load API keys
    api_keys = load_api_keys()
    if not api_keys["openrouter"] or not api_keys["gemini"]:
        print("ERROR: API keys not set in .env")
        print("Need both OPENROUTER_API_KEY and GEMINI_API_KEY")
        sys.exit(1)
    
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Summary-only mode
    if args.summary_only:
        generate_summary()
        return
    
    # Determine target path
    target = Path(args.path)
    if not target.is_absolute():
        target = ROOT / target
    
    if not target.exists():
        print(f"ERROR: {target} not found")
        sys.exit(1)
    
    # Discover files
    files = discover_files(target)
    print(f"Found {len(files)} Python files to review")
    
    if not files:
        print("Nothing to review")
        return
    
    # Apply max-files limit
    if len(files) > args.max_files:
        print(f"Limiting to first {args.max_files} files (use --max-files to increase)")
        files = files[:args.max_files]
    
    # Load progress
    progress = load_progress() if not args.reset else {"reviewed": [], "skipped": []}
    
    # Filter out already-reviewed files
    todo = [f for f in files if str(f.relative_to(ROOT)) not in progress["reviewed"]]
    
    print(f"\nFiles to review: {len(todo)}")
    print(f"Already reviewed: {len(progress['reviewed'])}")
    
    if args.dry_run:
        print("\n=== DRY RUN MODE ===")
        for f in todo[:5]:
            print(f"  Would review: {f.relative_to(ROOT)} ({count_lines(f)} lines)")
        if len(todo) > 5:
            print(f"  ... and {len(todo) - 5} more")
        return
    
    # Review loop
    print(f"\n{'='*70}")
    print(f"DUAL-MODEL CODE REVIEW")
    print(f"Generator: {GENERATOR_MODEL}")
    print(f"Critic:    {CRITIC_MODEL}")
    print(f"{'='*70}")
    
    reviewed_count = 0
    for i, file_path in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}]", end="")
        
        review = review_file(
            file_path, api_keys, 
            dry_run=args.dry_run,
            show_prompts=args.show_prompts
        )
        
        if review:
            save_review(review)
            progress["reviewed"].append(str(file_path.relative_to(ROOT)))
            save_progress(progress)
            reviewed_count += 1
        
        # Progress update every 5 files
        if i % 5 == 0:
            print(f"\n  📊 Progress: {i}/{len(todo)} reviewed")
    
    print(f"\n{'='*70}")
    print(f"REVIEW COMPLETE")
    print(f"{'='*70}")
    print(f"Files reviewed this run: {reviewed_count}")
    print(f"Total files reviewed: {len(progress['reviewed'])}")
    print(f"\nGenerating summary...")
    
    generate_summary()
    
    print(f"\n{'='*70}")
    print(f"NEXT STEPS")
    print(f"{'='*70}")
    print(f"1. Open {SUMMARY_FILE.relative_to(ROOT)} for the consolidated report")
    print(f"2. Review individual files in {REVIEWS_DIR.relative_to(ROOT)}/")
    print(f"3. Implement high-impact fixes first")
    print(f"4. Re-run with --reset to see improvement after fixes")


if __name__ == "__main__":
    main()
