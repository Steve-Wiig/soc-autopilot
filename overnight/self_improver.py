import hashlib
import string
#!/usr/bin/env python3
"""
soc-autopilot: Autonomous Engineering System
A Staff-Level, Self-Healing, Test-Driven, Causal-Triage Autonomous Engineering System.
"""
import sys, json, subprocess, time, argparse, ast, re, os, hashlib, uuid
from pathlib import Path
from datetime import datetime
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from overnight.llm_client import generate, load_api_keys, strip_fences, gemini_pre_analysis, _call_gemini
from overnight.budget_manager import APIBudgetManager
from overnight.code_reviewer import review_file, extract_json_from_response, build_review_prompt, get_file_context

ROOT = Path(__file__).resolve().parent.parent
QUEUE_DIR = ROOT / "overnight" / "advisory_queue" / "pending"
FIX_BACKLOG = ROOT / "overnight" / "fix_backlog.json"
DEFERRED_BACKLOG = ROOT / "overnight" / "fix_backlog_deferred.json"
LESSONS_FILE = ROOT / "overnight" / "lessons_learned.json"

SAFE_CATEGORIES = {"maintainability", "blueprint_compliance", "performance"}
SAFE_SEVERITIES = {"low", "informational", "medium"}

# Try to import advanced engines (degrade gracefully if missing)
try: from engine.defeat_ledger import is_ast_defeated, check_and_record_defeat
except ImportError: is_ast_defeated = lambda x: False; check_and_record_defeat = lambda *a, **k: None

try: from engine.multi_file_patcher import parse_multi_file_diff, apply_multi_file_patches
except ImportError: parse_multi_file_diff = None; apply_multi_file_patches = None

try: from engine.reasoning_ledger import record_interaction
except ImportError: record_interaction = lambda *a, **k: None

try: from engine.cer_critic import generate_strategic_constraint
except ImportError: generate_strategic_constraint = lambda *a, **k: "Adopt a different algorithmic strategy."

try: from engine.failure_autopsy import perform_autopsy
except ImportError: perform_autopsy = lambda *a, **k: ""

# ============================================================
# QUEUE & STATE MANAGEMENT
# ============================================================
def _load_json(path):
    try: return json.loads(path.read_text()) if path.exists() else []
    except Exception: return []

def _save_json(path, data): path.write_text(json.dumps(data, indent=2))

# ============================================================
# PYTEST CACHING (Improvement #4)
# Memoizes pytest results by (repo_fingerprint, targets).
# Invalidates when a fix is committed via Shadow Canary.
# ============================================================
_baseline_cache = {"fingerprint": None, "result": None, "targets": None}

def _get_repo_fingerprint():
    """Hash relevant repo files (tracked + untracked) to detect state changes.
    
    Includes full file content (not truncated) and untracked files to prevent
    false cache hits when test/engine code changes beyond the 4KB mark or
    when new untracked test files are added.
    """
    try:
        # Get tracked files
        res1 = subprocess.run(
            ["git", "ls-tree", "-r", "HEAD", "--name-only"],
            capture_output=True, text=True, cwd=ROOT, timeout=10
        )
        tracked = set(f.strip() for f in res1.stdout.splitlines() if f.strip()) if res1.returncode == 0 else set()

        # Get untracked files (respecting .gitignore)
        res2 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=ROOT, timeout=10
        )
        untracked = set(f.strip() for f in res2.stdout.splitlines() if f.strip()) if res2.returncode == 0 else set()

        # Only hash relevant code directories to avoid invalidating cache on docs/README changes
        relevant_prefixes = ("tests/", "engine/", "overnight/", "memory/", "orchestrator/", "tools/")
        
        h = hashlib.sha256()
        for f in sorted(tracked | untracked):
            if not any(f.startswith(p) for p in relevant_prefixes):
                continue
            h.update(f.encode())
            p_file = ROOT / f
            if p_file.exists():
                h.update(p_file.read_bytes())
            else:
                h.update(b"__DELETED__")
        return h.hexdigest()
    except Exception:
        return None



def run_pytest_cached(targets, timeout=60):
    """Cached pytest for baseline checks. Sniper Scope must use uncached run_pytest."""
    fp = _get_repo_fingerprint()
    targets_key = tuple(sorted(targets))
    
    if (fp is not None and
        _baseline_cache["fingerprint"] == fp and 
        _baseline_cache["targets"] == targets_key):
        print(f"       ♻️  pytest cache hit (fingerprint: {fp[:8] if fp else 'none'}...)")
        return _baseline_cache["result"]
    
    result = run_pytest(targets, timeout=timeout)
    _baseline_cache.update({
        "fingerprint": fp, 
        "result": result, 
        "targets": targets_key
    })
    return result


def _record_ledger(file_path, issue, status, reason=""):
    """Append-only provenance ledger for autonomous decisions (Handoff Sec 10)."""
    ledger_path = ROOT / "overnight" / "improvement_ledger.jsonl"
    entry = {
        "timestamp": datetime.now().isoformat(),
        "file": _safe_relative_path(file_path),
        "category": issue.get("category", "unknown"),
        "status": status,
        "reason": reason
    }
    with open(ledger_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

def _escalate_to_manual(file_path, issue, reason):
    """Safely moves an advisory to the manual review queue."""
    manual_path = ROOT / "overnight" / "needs_manual_review.json"
    manual_queue = _load_json(manual_path)
    item = {
        "file": str(file_path.relative_to(ROOT)),
        "issue": issue,
        "deferred_reason": reason,
        "escalated_at": datetime.now().isoformat()
    }
    # Prevent duplicate escalations
    if not any(m.get("file") == item["file"] and m.get("issue", {}).get("description") == issue.get("description") for m in manual_queue):
        manual_queue.append(item)
        _save_json(manual_path, manual_queue)

# ============================================================
# HELPER ENGINES (Sniper, Pruner, Triage, TDD)
# ============================================================
def _get_test_targets(file_path):
    stem = file_path.stem
    targets = []
    for pattern in [f"tests/test_{stem}.py", f"tests/**/test_{stem}.py", f"tests/{stem}_check.py", f"tests/**/{stem}_check.py"]:
        targets.extend([str(p.relative_to(ROOT)) for p in ROOT.glob(pattern)])
    return targets if targets else ["tests/"]

def _prune_ast_context(source: str, issue_desc: str, max_chars: int = 20000) -> str:
    try: tree = ast.parse(source)
    except SyntaxError: return source[:max_chars]

    text_lower = issue_desc.lower()
    imports_globals = []
    definitions = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)): imports_globals.append(node)
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets): imports_globals.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): definitions.append(node)

    target_node = None
    for node in definitions:
        if node.name.lower() in text_lower: target_node = node; break

    def render(nodes):
        return "\n\n".join([ast.get_source_segment(source, n) for n in nodes if ast.get_source_segment(source, n)])

    # Focused context when the target is identified and fits.
    if target_node:
        pruned = render(imports_globals + [target_node])
        if pruned and len(pruned) <= max_chars:
            return pruned

    # IMPROVEMENT #10: no target match (or too big) -> show ALL real definitions
    # so the LLM never has to hallucinate the file structure.
    full = render(imports_globals + definitions)
    if full and len(full) <= max_chars:
        return full

    return source[:max_chars]


def _choose_context(original, issue_desc, raw_cap=24000):
    """IMPROVEMENT #11: send the raw file verbatim when it's small enough.
    Pruning drops comments/blank lines and breaks verbatim SEARCH matching."""
    if len(original) <= raw_cap:
        return original
    return _prune_ast_context(original, issue_desc)


import builtins as _builtins
_BUILTINS = set(dir(_builtins)) | {'__name__', '__file__', '__doc__', 'self', 'cls', 'None', 'True', 'False'}

def _check_for_ghost_names(source_code: str):
    """Check for hallucinated imports. Disabled aggressive local-var checking 
    to prevent false positives on loop variables (i, e, row, etc.)."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    # Only check for hallucinated external imports. 
    # Checking ast.Name nodes for local variables causes too many false positives.
    hallucinated = []
    known_stdlib = {'os', 'sys', 'json', 're', 'math', 'time', 'datetime', 'logging', 
                    'sqlite3', 'hashlib', 'uuid', 'pathlib', 'typing', 'collections', 
                    'contextlib', 'subprocess', 'argparse', 'tempfile', 'io'}
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split('.')[0]
                if root_mod not in known_stdlib and not root_mod.startswith(('engine', 'overnight', 'tools', 'orchestrator', 'memory')):
                    hallucinated.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_mod = node.module.split('.')[0]
                if root_mod not in known_stdlib and not root_mod.startswith(('engine', 'overnight', 'tools', 'orchestrator', 'memory')):
                    hallucinated.append(node.module)
                    
    return list(set(hallucinated))

def _get_imported_signatures(file_path, max_sigs=8):
    """IMPROVEMENT #16: extract REAL signatures of imported symbols so the
    model calls them correctly instead of hallucinating signatures."""
    try:
        tree = ast.parse(file_path.read_text())
    except Exception:
        return ""
    sigs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod_file = ROOT / Path(node.module.replace('.', '/') + '.py')
            if not mod_file.exists():
                continue
            try:
                mod_src = mod_file.read_text()
            except Exception:
                continue
            for alias in node.names:
                m = re.search(r'(def\s+' + re.escape(alias.name) + r'\s*\([^)]*\)[^:]*:)', mod_src)
                if m:
                    sigs.append(m.group(1).replace('\n', ' '))
                if len(sigs) >= max_sigs:
                    break
        if len(sigs) >= max_sigs:
            break
    if not sigs:
        return ""
    return "AVAILABLE IMPORTED API (call EXACTLY as shown, do not invent signatures):\n" + "\n".join(sigs) + "\n\n"


def triage_backlog():
    ledger_path = ROOT / "overnight" / "defeat_ledger.jsonl"
    if not ledger_path.exists() or ledger_path.stat().st_size == 0: return
    suspects = Counter()
    for line in ledger_path.read_text().splitlines():
        if not line.strip(): continue
        try:
            tb = json.loads(line).get("traceback", "")
            for full_path, rel_path in re.findall(r'File "([^"]*blueprint/([^"]+\.py))"', tb):
                if "/tests/" not in rel_path and "site-packages" not in full_path: suspects[rel_path] += 1
        except Exception: pass
    if not suspects: return
    root_file, count = suspects.most_common(1)[0]
    if count < 2: return
    print(f"  🕵️ CAUSAL TRIAGE: Root Cause '{root_file}' ({count} tracebacks)")
    backlog = _load_json(FIX_BACKLOG)
    root_items = [i for i in backlog if i["file"] == root_file]
    leaf_items = [i for i in backlog if i["file"] != root_file]
    if root_items and len(root_items) < len(backlog): _save_json(FIX_BACKLOG, root_items + leaf_items)


def _generate_tdd_test(issue_desc: str, target_file: str, api_keys: dict) -> str:
    # AST_SIGNATURE_FIX_V1
    sig_context = ""
    try:
        target_path = ROOT / target_file
        tree = ast.parse(target_path.read_text())
        defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if defs:
            sigs = []
            for d in defs[:10]:
                args = [a.arg for a in d.args.args if a.arg not in ('self', 'cls')]
                sigs.append(f"def {d.name}({', '.join(args)})")
            sig_context = f"REAL FUNCTION SIGNATURES IN THIS FILE (DO NOT INVENT NEW ARGUMENTS):\n{chr(10).join(sigs)}\n"
    except Exception as e:
        print(f"       ⚠️ TDD AST sig read failed: {e}")
        sig_context = ""

    prompt = (
        f"You are a senior QA engineer. Write a minimal failing pytest test for:\n"
        f"ISSUE: {issue_desc}\nTARGET FILE: {target_file}\n"
        f"PROJECT STRUCTURE: Files live in subdirectories (tools/, engine/, memory/).\n"
        f"IMPORT RULE: To import, you MUST use sys.path manipulation. Example:\n"
        f"import sys\nsys.path.insert(0, 'tools')  # or 'engine'\nfrom file_name import function_name\n\n"
        f"{sig_context}\n"
        "Output ONLY the python code for the test function. No markdown.\n"
    )
    raw = generate(prompt, api_keys, temperature=0.1, model_type="code")
    if not raw: return None
    code = strip_fences(raw)
    try: ast.parse(code); return code
    except SyntaxError: return None



def _failed_test_ids(tb):
    """Extract the set of failing test IDs from a pytest traceback string."""
    if not tb:
        return set()
    return set(re.findall(r'FAILED\s+([^\s]+)', tb))


def run_pytest(targets, timeout=60):
    """Returns None if tests pass, or the traceback string if they fail."""
    try:
        res = subprocess.run([sys.executable, "-m", "pytest", *targets, "-q", "--tb=short", "-x"], 
                             cwd=ROOT, capture_output=True, timeout=timeout)
        if res.returncode == 0: return None
        return (res.stderr.decode(errors='replace') + res.stdout.decode(errors='replace'))[:2000]
    except Exception: return "Pytest execution error"

# ============================================================
# FORENSIC ANALYSIS (Improvement #5)
# Two-phase: understand the defect BEFORE generating the fix.
# ============================================================
def _forensic_analysis(issue, source_code, baseline_tb, api_keys):
    """Phase 1: Structured root cause extraction before fix generation.
    
    Returns a formatted context string to inject into the fix prompt.
    Falls back to empty string on any failure (non-blocking).
    """
    issue_desc = issue.get("description", "Unknown issue")
    category = issue.get("category", "unknown")
    
    prompt = (
        "You are a senior code forensic analyst. Analyze this defect.\n"
        "Do NOT propose a fix. Only identify the root cause.\n\n"
        f"ISSUE ({category}): {issue_desc}\n\n"
        f"BASELINE TRACEBACK:\n{str(baseline_tb)[:1500]}\n\n"
        f"SOURCE CODE (relevant section):\n{source_code[:6000]}\n\n"
        "Output ONLY a JSON object with these exact keys:\n"
        '{\n'
        '  "root_cause": "one sentence describing WHY the bug exists",\n'
        '  "affected_function": "name of the function/method that needs changing",\n'
        '  "fix_strategy": "one sentence describing WHAT to change (not how)",\n'
        '  "constraints": ["list of things the fix must NOT do"],\n'
        '  "risk": "one sentence describing what could break"\n'
        '}\n'
    )
    
    try:
        raw = generate(prompt, api_keys, temperature=0.1, max_tokens=1024, model_type="json")
        if not raw:
            return ""
        
        raw = raw.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        
        # Try to parse as JSON
        import json as _json
        try:
            analysis = _json.loads(raw)
        except Exception:
            # Try to extract JSON from surrounding text
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                analysis = _json.loads(raw[start:end])
            else:
                return ""
        
        # Build structured context string
        context_parts = [
            "FORENSIC ANALYSIS (generated before fix):",
            f"  Root Cause: {analysis.get('root_cause', 'Unknown')}",
            f"  Affected Function: {analysis.get('affected_function', 'Unknown')}",
            f"  Fix Strategy: {analysis.get('fix_strategy', 'Unknown')}",
        ]
        constraints = analysis.get("constraints", [])
        if constraints:
            context_parts.append(f"  Constraints: {'; '.join(constraints[:3])}")
        risk = analysis.get("risk", "")
        if risk:
            context_parts.append(f"  Risk: {risk}")
        
        return "\n".join(context_parts) + "\n\n"
        
    except Exception:
        return ""  # Non-blocking: fall back to direct generation


# ============================================================
# PROVEN FIX MEMORY (Improvement #6)
# Stores successful fixes. Retrieves similar patterns for future fixes.
# This is how the system learns from itself.
# ============================================================
PROVEN_FIXES_PATH = ROOT / "overnight" / "proven_fixes.jsonl"

def _safe_relative_path(file_path):
    """Get relative path if possible, otherwise absolute path string."""
    try:
        return str(file_path.relative_to(ROOT))
    except (ValueError, TypeError):
        return str(file_path)

def _store_proven_fix(file_path, issue, diff_text, forensic_context):
    """Store a successfully applied fix as a proven pattern."""
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "category": issue.get("category", "unknown"),
            "file": _safe_relative_path(file_path),
            "advisory": issue.get("description", "")[:200],
            "fix_diff": diff_text[:2000],
            "forensic_summary": forensic_context[:300] if forensic_context else ""
        }
        with open(PROVEN_FIXES_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Non-blocking

def _retrieve_similar_fixes(issue, max_examples=2):
    """Retrieve proven fixes similar to the current advisory.
    
    Matching: exact category + keyword overlap in description.
    Returns formatted string for prompt injection, or empty string.
    """
    try:
        if not PROVEN_FIXES_PATH.exists():
            return ""
        
        entries = []
        for line in PROVEN_FIXES_PATH.read_text().strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        
        if not entries:
            return ""
        
        # Score by category match + keyword overlap
        target_category = issue.get("category", "").lower()
        target_words = set(issue.get("description", "").lower().split())
        
        scored = []
        for entry in entries:
            score = 0
            if entry.get("category", "").lower() == target_category:
                score += 10
            entry_words = set(entry.get("advisory", "").lower().split())
            overlap = len(target_words & entry_words)
            score += min(overlap, 5)
            if score > 0:
                scored.append((score, entry))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        top_matches = [e for _, e in scored[:max_examples]]
        
        if not top_matches:
            return ""
        
        # Format as few-shot examples
        parts = ["PROVEN FIX EXAMPLES (from past successful fixes in this codebase):"]
        for i, match in enumerate(top_matches, 1):
            parts.append(f"\nExample {i} ({match.get('category')}, {match.get('file')}):")
            parts.append(f"Advisory: {match.get('advisory', '')[:100]}")
            if match.get("forensic_summary"):
                parts.append(f"Analysis: {match['forensic_summary'][:150]}")
            parts.append(f"Fix applied:\n{match.get('fix_diff', '')[:800]}")
        
        parts.append("\nApply a similar pattern to the current advisory.\n\n")
        return "\n".join(parts)
        
    except Exception:
        return ""  # Non-blocking


# ============================================================
# NEGATIVE MEMORY (Improvement #14)
# Stores FAILED fixes so the system avoids repeating the same mistakes.
# Symmetric counterpart to proven_fix memory (positive learning).
# ============================================================
FAILED_FIXES_PATH = ROOT / "overnight" / "failed_fixes.jsonl"

def _store_failed_fix(file_path, issue, diff_text, constraint):
    """Store a failed fix attempt as a negative pattern to avoid."""
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "category": issue.get("category", "unknown"),
            "file": _safe_relative_path(file_path),
            "advisory": issue.get("description", "")[:200],
            "failed_diff": diff_text[:1500],
            "constraint": constraint[:300] if constraint else ""
        }
        with open(FAILED_FIXES_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Non-blocking

def _retrieve_failed_patterns(issue, max_examples=2):
    """Retrieve similar past failures to inject as AVOID warnings."""
    try:
        if not FAILED_FIXES_PATH.exists():
            return ""
        entries = []
        for line in FAILED_FIXES_PATH.read_text().strip().split("\n"):
            if line.strip():
                try: entries.append(json.loads(line))
                except Exception: pass
        if not entries:
            return ""
        target_category = issue.get("category", "").lower()
        target_words = set(issue.get("description", "").lower().split())
        scored = []
        for entry in entries:
            score = 0
            if entry.get("category", "").lower() == target_category:
                score += 10
            overlap = len(target_words & set(entry.get("advisory", "").lower().split()))
            score += min(overlap, 5)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [e for _, e in scored[:max_examples]]
        if not top:
            return ""
        parts = ["PAST FAILED APPROACHES (do NOT repeat these mistakes):"]
        for i, m in enumerate(top, 1):
            parts.append(f"\nFailed attempt {i} ({m.get('category')}, {m.get('file')}):")
            if m.get("constraint"):
                parts.append(f"Why it failed: {m['constraint'][:200]}")
            parts.append(f"Bad patch (AVOID this pattern):\n{m.get('failed_diff', '')[:500]}")
        parts.append("\nLearn from these failures. Do NOT repeat the same mistakes.\n\n")
        return "\n".join(parts)
    except Exception:
        return ""  # Non-blocking


# ============================================================
# CORE FIX ENGINE
# ============================================================
def apply_auto_fix(file_path, issue, api_keys):
    try: original = file_path.read_text()
    except Exception: return False

    if is_ast_defeated(original): return False
    if issue.get('category', '').lower() in ['style', 'documentation']: return False

    targets = _get_test_targets(file_path)
    
    # 1. RED-GREEN BASELINE
    baseline_tb = run_pytest_cached(targets)
    if baseline_tb is None:
        category = issue.get('category', '').lower()
        # Functional bugs with passing tests are truly stale (already fixed)
        if category in ['bug', 'correctness', 'style', 'documentation', '']:
            print(f"       ✅ Baseline tests passed. Stale advisory.")
            _record_ledger(file_path, issue, "STALE", "Baseline passed")
            return True
        else:
            # Security/Performance/Reliability flaws don't always have failing tests.
            # Do not drop them. Escalate to manual review.
            print(f"       ⚠️ Baseline passed, but category is '{category}'. Escalating (lacks regression test).")
            _escalate_to_manual(file_path, issue, f"Passed baseline but lacks regression test for {category} defect.")
            _record_ledger(file_path, issue, "ESCALATED", "Lacks regression test")
            return True
    print(f"       🔴 Baseline failure captured ({len(baseline_tb)} chars)")

    # 2. TDD SUB-AGENT
    print(f"       🧪 Spawning TDD Sub-Agent...")
    tdd_test_code = _generate_tdd_test(issue.get('description', ''), str(file_path.relative_to(ROOT)), api_keys)
    tdd_kept_path = None
    tdd_block = ""
    if tdd_test_code:
        test_path = ROOT / "tests" / f"test_tdd_auto_{file_path.stem}.py"
        try:
            test_path.write_text(tdd_test_code)
            # RED PHASE VERIFICATION: The test MUST fail before we apply the fix.
            # If it passes immediately, the test is vacuous and cannot validate the fix.
            red_check = run_pytest([str(test_path.relative_to(ROOT))])
            if red_check is None:
                print(f"       ⚠️ TDD Red Phase FAILED: Test passes immediately. Rejecting vacuous test.")
                test_path.unlink()
            else:
                print(f"       🔴 TDD Red Phase CONFIRMED: Test fails as expected.")
                tdd_block = f"ACCEPTANCE CRITERIA (Make this test pass):\n```python\n{tdd_test_code}\n```\n\n"
                tdd_kept_path = test_path
        except Exception: pass

    # 3. GENERATION LOOP
    critic_constraint = ""
    failed_attempt_1_raw = ""
    current_temp = 0.2
    current_max = 4096
    
    # FORENSIC ANALYSIS PHASE (Improvement #5)
    print(f"       🔬 Running forensic analysis...")
    forensic_context = _forensic_analysis(issue, original, baseline_tb, api_keys)
    api_sigs = _get_imported_signatures(file_path)
    
    # PROVEN FIX RETRIEVAL (Improvement #6)
    proven_examples = _retrieve_similar_fixes(issue)
    if proven_examples:
        forensic_context += proven_examples
        print(f"       📚 Retrieved {proven_examples.count('Example')} proven fix example(s)")

    # NEGATIVE MEMORY RETRIEVAL (Improvement #14)
    failed_patterns = _retrieve_failed_patterns(issue)
    if failed_patterns:
        forensic_context += failed_patterns
        print(f"       🚫 Retrieved {failed_patterns.count('Failed attempt')} failed pattern(s) to avoid")
    if forensic_context:
        print(f"       🔬 Forensic context: {forensic_context.split(chr(10))[1][:60]}...")
    else:
        print(f"       🔬 Forensic analysis unavailable (falling back to direct generation)")

    for attempt in range(2):
        pruned = _choose_context(original, issue.get('description', ''))
        
        prompt = (
            "You are a senior Python engineer. Fix the issue below.\n"
            "Output ONLY Aider-style SEARCH/REPLACE blocks.\n"
            "Format: <<<<<<< path/to/file.py\n[exact search text]\n=======\n[replace]\n>>>>>>> REPLACE\n\n"
            "CRITICAL RULES FOR THE SEARCH BLOCK:\n"
            "1. Copy lines EXACTLY as they appear between the ``` markers in CURRENT FILE.\n"
            "2. Do NOT add line numbers. Do NOT re-indent. Do NOT reformat.\n"
            "3. Preserve every space and newline exactly.\n\n"
            f"{tdd_block}"
            f"ISSUE: {issue.get('description', '')}\n\n"
            f"{forensic_context}"
            f"{api_sigs}"
            f"BASELINE TRACEBACK:\n```{baseline_tb}```\n\n"
            f"{f'CRITICAL STRATEGY SHIFT: {critic_constraint}' if critic_constraint else ''}\n"
            f"CURRENT FILE:\n```\n{pruned}\n```\n\n"
            f"FILE PATH: {file_path.relative_to(ROOT)}"
        )
        if attempt == 1 and failed_attempt_1_raw:
            prompt += f"\n\n<<<<<<< YOUR PREVIOUS FAILED ATTEMPT (DO NOT REPEAT THIS)\n{failed_attempt_1_raw[:3000]}\n>>>>>>> END FAILED ATTEMPT\n"
        raw = generate(prompt, api_keys, temperature=current_temp, max_tokens=current_max, model_type="patch")
        if not raw: return False
        
        # NEW: Strip LLM prose, extract ONLY the Aider diff blocks
        import re
        diff_blocks = re.findall(r'(<<<<<<<.*?>>>>>>> REPLACE)', raw, re.DOTALL)
        if diff_blocks:
            raw = "\n".join(diff_blocks)
            
        raw = strip_fences(raw)

        # Parse & Apply Patches
        modified_files = {}
        try:
            if parse_multi_file_diff:
                patches = parse_multi_file_diff(raw, ROOT)
                modified_files = apply_multi_file_patches(patches)
            else:
                # Fallback to simple single-file replace if engine missing
                modified_files = {file_path: original.replace(raw, raw)} # Dummy
        except Exception as e:
            if attempt == 0:
                failed_attempt_1_raw = raw
                print(f"       🩸 AUTOPSY: Analyzing patch failure...")
                critic_constraint = perform_autopsy(raw, str(e), api_keys)
                print(f"       🧠 Constraint: {critic_constraint[:80]}...")
                # DYNAMIC TUNING
                if "truncat" in critic_constraint.lower(): current_max = 8192; current_temp = 0.1
                elif "algorithm" in critic_constraint.lower() or "logic" in critic_constraint.lower(): current_temp = 0.6
                else: current_temp = 0.1
                continue
            return False

        # GUARD: If patch produced no changes, skip pytest and retry
        if not modified_files:
            try:
                (ROOT / "overnight" / "last_failed_raw.txt").write_text(
                    f"=== ADVISORY ===\n{issue.get('description','')}\n\n"
                    f"=== RAW MODEL OUTPUT (0 SEARCH/REPLACE blocks parsed) ===\n{raw[:6000]}\n")
            except Exception: pass
            print(f"       ⚠️ 0 SEARCH/REPLACE blocks parsed (format issue). Raw dumped to overnight/last_failed_raw.txt")
            if attempt == 0:
                failed_attempt_1_raw = raw
                continue
            return False

        # 👻 GHOST NAME GATE: Reject patches that use undefined names (saves Pytest runs)
        ghost_violations = {}
        for path, new_content in modified_files.items():
            ghosts = _check_for_ghost_names(new_content)
            if ghosts:
                ghost_violations[path.name] = ghosts

        if ghost_violations:
            ghosts_str = ", ".join([f"{k}({', '.join(v)})" for k,v in ghost_violations.items()])
            print(f"       👻 GHOST NAMES DETECTED: {ghosts_str}")
            if attempt == 0:
                failed_attempt_1_raw = raw
                critic_constraint = f"Generated code uses undefined names ({ghosts_str}). Add the missing imports or use existing ones."
                current_temp = 0.1
                continue
            return False

        # Backup & Write
        backups = {}
        for path, content in modified_files.items():
            backups[path] = path.read_text() if path.exists() else ""
            path.write_text(content)

        # Run Pytest (Sniper Scope)
        tb = run_pytest(targets)
        before_ids = _failed_test_ids(baseline_tb)
        after_ids = _failed_test_ids(tb)
        new_failures = after_ids - before_ids
        if tdd_kept_path is not None:
            tdd_passes = run_pytest([str(tdd_kept_path.relative_to(ROOT))]) is None
            success = (len(new_failures) == 0) and tdd_passes
        else:
            success = (tb is None) or (after_ids < before_ids)
        print(f"       📉 Delta: before={len(before_ids)} after={len(after_ids)} new_failures={len(new_failures)}")
        if success:
            # SUCCESS -> SHADOW CANARY
            import uuid
            from tools.shadow_canary import run_canary
            shadow_branch = f"shadow/autofix-{uuid.uuid4().hex[:8]}"
            modified_paths = [str(p) for p in modified_files.keys()]
            
            try:
                print(f"       🦜 Routing to Shadow Canary ({shadow_branch})...")
                subprocess.run(["git", "checkout", "master"], cwd=ROOT, capture_output=True)
                subprocess.run(["git", "checkout", "-b", shadow_branch], cwd=ROOT, check=True, capture_output=True)
                subprocess.run(["git", "add", *modified_paths], cwd=ROOT, check=True, capture_output=True)
                subprocess.run(["git", "commit", "-m", f"shadow: {file_path.name}"], cwd=ROOT, check=True, capture_output=True)
                
                if run_canary(modified_paths):
                    subprocess.run(["git", "checkout", "master"], cwd=ROOT, check=True, capture_output=True)
                    subprocess.run(["git", "merge", shadow_branch], cwd=ROOT, check=True, capture_output=True)
                    subprocess.run(["git", "branch", "-d", shadow_branch], cwd=ROOT, check=True, capture_output=True)
                    print(f"       🟢 CANARY PASSED: Merged to master")
                    # STORE PROVEN FIX (Improvement #6)
                    _store_proven_fix(file_path, issue, raw, forensic_context)
                    _record_ledger(file_path, issue, "APPLIED", "Canary passed")
                    return True
                else:
                    for path, content in backups.items(): path.write_text(content)
                    subprocess.run(["git", "checkout", "master"], cwd=ROOT, capture_output=True)
                    subprocess.run(["git", "branch", "-D", shadow_branch], cwd=ROOT, capture_output=True)
                    print(f"       🔴 CANARY FAILED: Reverted disk and shadow branch")
                    return False
                    
            except Exception as e:
                for path, content in backups.items(): path.write_text(content)
                subprocess.run(["git", "checkout", "master"], cwd=ROOT, capture_output=True)
                subprocess.run(["git", "branch", "-D", shadow_branch], cwd=ROOT, capture_output=True)
                print(f"       ⚠️ Shadow Git Error: {e}")
                return False

        # FAILURE: Revert
        for path, content in backups.items():
            path.write_text(content)
        
        if attempt == 0:
            failed_attempt_1_raw = raw
            print(f"       🩸 AUTOPSY: Analyzing test failure...")
            critic_constraint = perform_autopsy(list(modified_files.values())[0] if modified_files else original, tb, api_keys)
            print(f"       🧠 Constraint: {critic_constraint[:80]}...")
            # DYNAMIC TUNING
            if "truncat" in critic_constraint.lower(): current_max = 8192; current_temp = 0.1
            elif "algorithm" in critic_constraint.lower() or "logic" in critic_constraint.lower(): current_temp = 0.6
            else: current_temp = 0.1
            continue
        else:
            _record_ledger(file_path, issue, "REJECTED", "Failed generation/tests")
            _store_failed_fix(file_path, issue, raw, critic_constraint)
            check_and_record_defeat(str(file_path), original, tb)
            return False
    return False

# ============================================================
# SELF-IMPROVEMENT SCORECARD (Improvement #7)
# Analyzes the improvement ledger to measure whether the system
# is actually getting better over time.
# ============================================================
def compute_scorecard():
    """Compute self-improvement metrics from the improvement ledger.
    
    Returns a dict with:
    - total_decisions, applied, stale, escalated, rejected
    - success_rate (applied / non-stale decisions)
    - category_breakdown: {category: {applied, rejected, escalated}}
    - proven_fix_count: number of stored proven patterns
    - trend: "improving" | "stable" | "degrading" | "insufficient_data"
    """
    ledger_path = ROOT / "overnight" / "improvement_ledger.jsonl"
    proven_path = ROOT / "overnight" / "proven_fixes.jsonl"
    failed_path = ROOT / "overnight" / "failed_fixes.jsonl"
    
    scorecard = {
        "total_decisions": 0,
        "applied": 0,
        "stale": 0,
        "escalated": 0,
        "rejected": 0,
        "success_rate": 0.0,
        "category_breakdown": {},
        "proven_fix_count": 0,
        "failed_pattern_count": 0,
        "trend": "insufficient_data"
    }
    
    # Count proven fixes
    try:
        if proven_path.exists():
            scorecard["proven_fix_count"] = len([
                l for l in proven_path.read_text().strip().split("\n") if l.strip()
            ])
    except Exception:
        pass

    # Count failed patterns (negative memory)
    try:
        if failed_path.exists():
            scorecard["failed_pattern_count"] = len([
                l for l in failed_path.read_text().strip().split("\n") if l.strip()
            ])
    except Exception:
        pass
    
    # Parse ledger
    entries = []
    try:
        if ledger_path.exists():
            for line in ledger_path.read_text().strip().split("\n"):
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return scorecard
    
    if not entries:
        return scorecard
    
    scorecard["total_decisions"] = len(entries)
    
    # Count statuses and build category breakdown
    for entry in entries:
        status = entry.get("status", "UNKNOWN")
        category = entry.get("category", "unknown")
        
        if status == "APPLIED":
            scorecard["applied"] += 1
        elif status == "STALE":
            scorecard["stale"] += 1
        elif status == "ESCALATED":
            scorecard["escalated"] += 1
        elif status == "REJECTED":
            scorecard["rejected"] += 1
        
        if category not in scorecard["category_breakdown"]:
            scorecard["category_breakdown"][category] = {"applied": 0, "rejected": 0, "escalated": 0}
        if status in ("APPLIED", "REJECTED", "ESCALATED"):
            key = status.lower()
            if key in scorecard["category_breakdown"][category]:
                scorecard["category_breakdown"][category][key] += 1
    
    # Success rate: applied / (applied + rejected + escalated)
    actionable = scorecard["applied"] + scorecard["rejected"] + scorecard["escalated"]
    if actionable > 0:
        scorecard["success_rate"] = round(scorecard["applied"] / actionable * 100, 1)
    
    # Trend: compare first half vs second half success rates
    actionable_entries = [e for e in entries if e.get("status") in ("APPLIED", "REJECTED", "ESCALATED")]
    if len(actionable_entries) >= 6:
        mid = len(actionable_entries) // 2
        first_half = actionable_entries[:mid]
        second_half = actionable_entries[mid:]
        
        first_success = sum(1 for e in first_half if e["status"] == "APPLIED") / len(first_half)
        second_success = sum(1 for e in second_half if e["status"] == "APPLIED") / len(second_half)
        
        if second_success > first_success + 0.1:
            scorecard["trend"] = "improving"
        elif second_success < first_success - 0.1:
            scorecard["trend"] = "degrading"
        else:
            scorecard["trend"] = "stable"
    
    return scorecard


# ============================================================
# QUEUE DRAINING
# ============================================================
def drain_fix_backlog(api_keys, max_fixes=3):
    backlog = _load_json(FIX_BACKLOG)
    if not backlog: return 0
    done, remaining, deferred = 0, [], _load_json(DEFERRED_BACKLOG)
    for item in backlog:
        if done >= max_fixes: remaining.append(item); continue
        fpath = ROOT / item["file"]
        # --- EFFICIENCY: LOCAL SLM PRE-ROUTER (TOP OF LOOP) ---
        # Intercept stylistic advisories BEFORE checking cloud budget
        try:
            issue_desc = item.get('issue', {}).get('description', '')
        except AttributeError:
            issue_desc = ''
        
        if _classify_and_route_local(issue_desc):
            print(f"       🔀 Intercepted stylistic fix. Routing to Local SLM (Port 11435). Bypassing cloud budget.")
            _record_ledger(fpath, item.get('issue', {}), "DEFERRED", "Routed to Local SLM (Validation Phase)")
            if item in remaining: remaining.remove(item)
            continue
        # ----------------------------------------------------------------
        if not fpath.exists(): continue
        if apply_auto_fix(fpath, item["issue"], api_keys):
            done += 1
        else:
            item["attempts"] = item.get("attempts", 0) + 1
            if item["attempts"] >= 3: deferred.append(item)
            else: remaining.append(item)
    _save_json(FIX_BACKLOG, remaining)
    if deferred: _save_json(DEFERRED_BACKLOG, deferred)
    return done

def drain_backlog_loop(api_keys, budget, state, fixes_per_pass=4):
    print(f"BACKLOG DRAIN MODE ({fixes_per_pass} fixes/pass)")
    for pass_num in range(1, 101):
        if not _load_json(FIX_BACKLOG): break
        print(f"\n[Pass {pass_num}] {len(_load_json(FIX_BACKLOG))} fixes remaining...")
        triage_backlog()
        fixed = drain_fix_backlog(api_keys, max_fixes=fixes_per_pass)
        print(f"🔧 Pass {pass_num}: {fixed} applied")
        if fixed == 0: break
        time.sleep(15)

# ============================================================
# PHASE A & B (GEMINI / OPENROUTER)
# ============================================================
def prefill_advisory_queue(files, api_keys, budget):
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files, 1):
        qpath = QUEUE_DIR / f"{str(f.relative_to(ROOT)).replace('/', '__').replace('.py', '')}.json"
        if qpath.exists(): continue
        if not budget.wait_if_needed("gemini", timeout=120): break
        budget.record_call("gemini")
        try:
            advisory = gemini_pre_analysis(f.relative_to(ROOT), f.read_text(), api_keys)
            if advisory:
                qpath.write_text(json.dumps({"file_path": str(f.relative_to(ROOT)), "advisory_notes": advisory, "created_at": datetime.now().isoformat()}, indent=2))
        except Exception: pass
        time.sleep(1)


def normalize_advisory(text: str) -> str:
    if not text: return ""
    text = text.lower()
    text = text.translate(str.maketrans('', '', string.punctuation))
    return ' '.join(text.split())

def _check_cooldown(file_path: str, advisory_notes: str):
    import json, hashlib, string
    from datetime import datetime
    from pathlib import Path
    def norm(t):
        if not t: return ""
        return ' '.join(t.lower().translate(str.maketrans('', '', string.punctuation)).split())
    try:
        fixes_path = Path(__file__).parent / "failed_fixes.jsonl"
        if not fixes_path.exists(): return False, ""
        rel_path = str(file_path).replace(str(Path(__file__).parent.parent) + "/", "")
        target_hash = hashlib.sha256(f"{rel_path}::{norm(advisory_notes)}".encode()).hexdigest()
        now = datetime.now()
        failures = 0
        with open(fixes_path, 'r') as f:
            for line in f:
                if not line.strip(): continue
                try: entry = json.loads(line)
                except: continue
                if entry.get("file") != rel_path: continue
                stored_hash = hashlib.sha256(f"{rel_path}::{norm(entry.get('advisory', ''))}".encode()).hexdigest()
                if stored_hash == target_hash:
                    try:
                        if (now - datetime.fromisoformat(entry["timestamp"])).total_seconds() <= 86400: failures += 1
                    except: pass
                if failures >= 3: return True, f"Death loop cooldown ({failures} failures in 24h)"
        return False, ""
    except Exception as e:
        return True, f"Death loop cooldown (error: {type(e).__name__})"


def _classify_and_route_local(advisory_notes: str) -> bool:
    """Deterministic keyword classifier. Returns True if should route to Local SLM."""
    if not advisory_notes: return False
    notes_lower = advisory_notes.lower()
    
    # High-confidence local routing keywords (style/doc/maintainability)
    local_keywords = [
        'docstring', 'typo', 'comment', 'formatting', 'pep8', 'whitespace', 
        'unused import', 'black', 'flake8', 'mypy', 'type hint', 'variable name'
    ]
    
    if any(kw in notes_lower for kw in local_keywords):
        return True
    return False

def _call_local_slm_fallback(prompt: str) -> str:
    """Calls the sandboxed 1.5B model on port 11435."""
    import requests, json
    try:
        payload = {"model": "qwen2.5-coder:1.5b", "prompt": prompt, "stream": False}
        # Strict 15s timeout to prevent blocking the main queue
        resp = requests.post("http://127.0.0.1:11435/api/generate", json=payload, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception:
        pass
    return ""

def process_advisory_queue(api_keys, budget, state):
    pending = sorted(QUEUE_DIR.glob("*.json")) if QUEUE_DIR.exists() else []
    print(f"======================================================================\nPHASE B: OPENROUTER PROCESSING ({len(pending)} pending advisories)\n======================================================================")
    for i, qpath in enumerate(pending[:10], 1):
        if not budget.wait_if_needed("openrouter", timeout=120): break
        budget.record_call("openrouter")
        try:
            data = json.loads(qpath.read_text())
            source_file = ROOT / data["file_path"]
            print(f"  [{i}/{len(pending)}] 🔍 {data['file_path']}")
            if not source_file.exists(): qpath.unlink(); continue

            # --- STABILIZATION: COOLDOWN GATE ---



            skip, reason = _check_cooldown(data["file_path"], data.get("advisory_notes", ""))
            if skip:
                print(f"       ⏸️ {reason}. Skipping to save tokens.")
                dummy_issue = {"description": data.get("advisory_notes", "")[:200], "category": "maintainability"}
                _record_ledger(source_file, dummy_issue, "STALE", reason)
                if hasattr(qpath, 'unlink'): qpath.unlink(missing_ok=True)
                continue
            # --------------------------------------

            
            primary_response = generate(build_review_prompt(source_file, source_file.read_text(), get_file_context(source_file), advisory_notes=data["advisory_notes"]), api_keys, max_tokens=8192)
            if not primary_response: print("       ⚠️ Primary analysis failed"); continue
            
            improvements = extract_json_from_response(primary_response)
            if not improvements: print("       ⚠️ Parse failed"); qpath.unlink(); continue
            
            auto_fixable = [imp for imp in improvements if isinstance(imp, dict) and imp.get("category") in SAFE_CATEGORIES]
            print(f"       📥 {len(auto_fixable)} fixable issues queued to backlog")
            if auto_fixable:
                backlog = _load_json(FIX_BACKLOG)
                for issue in auto_fixable: backlog.append({"file": str(source_file.relative_to(ROOT)), "issue": issue})
                _save_json(FIX_BACKLOG, backlog)
            qpath.unlink()
        except Exception as e:
            print(f"       ❌ Queue Error: {e}")
        time.sleep(2)

def discover_files():
    files = []
    for d in ["engine", "orchestrator", "memory", "tools"]:
        dp = ROOT / d
        if dp.exists(): files += [f for f in dp.rglob("*.py") if f.name != "__init__.py"]
    return sorted(files, key=lambda f: f.stat().st_size)

def main():
    for bak in sorted(ROOT.rglob("*.orig_backup")):
        bak.with_suffix("").write_text(bak.read_text()); bak.unlink()
        
    p = argparse.ArgumentParser()
    p.add_argument("--drain-backlog", action="store_true")
    p.add_argument("--process-only", action="store_true")
    p.add_argument("--fixes-per-pass", type=int, default=4)
    p.add_argument("--continuous", action="store_true", help="Run in continuous loop mode")
    p.add_argument("--loop-interval", type=int, default=60, help="Seconds to sleep between cycles (default: 60)")
    a = p.parse_args()

    keys = load_api_keys()
    budget = APIBudgetManager()
    files = discover_files()

    if a.continuous:
        cycle = 1
        while True:
            print(f"\n{'='*60}")
            print(f"🔄 CONTINUOUS MODE - Cycle {cycle} - {datetime.now().isoformat()}")
            print(f"{'='*60}\n")
            
            try:
                if a.drain_backlog:
                    drain_backlog_loop(keys, budget, None, fixes_per_pass=a.fixes_per_pass)
                elif a.process_only:
                    process_advisory_queue(keys, budget, None)
                else:
                    prefill_advisory_queue(files, keys, budget)
                    process_advisory_queue(keys, budget, None)
                    drain_backlog_loop(keys, budget, None, fixes_per_pass=a.fixes_per_pass)
            except Exception as e:
                print(f"⚠️ Cycle {cycle} error: {e}")
            
            print(budget.report())
            
            print(f"\n💤 Sleeping {a.loop_interval}s before next cycle...")
            time.sleep(a.loop_interval)
            cycle += 1
    else:
        if a.drain_backlog:
            drain_backlog_loop(keys, budget, None, fixes_per_pass=a.fixes_per_pass)
        elif a.process_only:
            process_advisory_queue(keys, budget, None)
        else:
            prefill_advisory_queue(files, keys, budget)
            process_advisory_queue(keys, budget, None)
            drain_backlog_loop(keys, budget, None, fixes_per_pass=a.fixes_per_pass)

        print(budget.report())

if __name__ == "__main__":
    main()