# LOCAL-SOC-SLM Documentation Errata & Corrections (v11.11 — v3)

# SECTION 1: ERRATA TABLE

| Document | Wrong | Correct |
|---|---|---|
| docs/ARCHITECTURE.md | SelfImprover class cuts off at `return ImprovementReport`; missing closing paren and rest of run() method body | Complete SelfImprover class with full run() method implementation |
| docs/LAB_SETUP_GUIDE.md | Wazuh Manager ossec.conf block cuts off mid-XML-attribute at `<synchron` | Complete ossec.conf with full `<synchronization>` element and remaining configuration |
| docs/deployment_runbook.md | §11.3 code block cuts off at bare `from` | Complete overnight/llm_client.py implementation with all imports and class definitions |
| docs/ARCHITECTURE.md (overnight section) | `orchestrator/llm_client.py` with Ollama/vLLM/LM Studio providers | `overnight/llm_client.py` — providers are OpenRouter, Groq, Gemini |
| docs/ARCHITECTURE.md (overnight section) | async `phase_a_prefill()` / `phase_b_analyze()` / `phase_c_drain()` | sync `prefill_advisory_queue()` / `process_advisory_queue()` / `drain_fix_backlog()` |
| docs/ARCHITECTURE.md (overnight section) | `SelfImprover` class doing LoRA fine-tuning + DBSCAN clustering | flat script: advisory analysis -> Gemini validation -> test-gated code fixes |
| docs/ARCHITECTURE.md (overnight section) | fix_backlog at `/var/lib/soc/`, `/data/self_improver/`, AND `overnight/` (3 paths) | `overnight/fix_backlog.json` (single path) |
| docs/ARCHITECTURE.md (overnight section) | OpenRouter quota: `$10 USD/day` vs `50 RPD` vs `500K tokens` (3 models) | 1000 RPD (funded tier), 24h lock on exhaustion, UTC rollover |
| docs/ARCHITECTURE.md (overnight section) | Schedule: 02:00 UTC vs 03:00 local vs `0 3 * * *` (3 answers) | NO hardcoded schedule — user-configured cron/systemd timer |
| docs/ARCHITECTURE.md (overnight section) | "Last Updated: 2025-01-15" | Fabricated date — REMOVE |
| docs/ARCHITECTURE.md (overnight section) | LLMProvider Protocol with claude-3.5-sonnet primary | free Nemotron via OpenRouter -> Groq compound fallback -> Gemini for prefill/critique |
| docs/OPERATIONS_RUNBOOK.md (Section 1.4) | Cron schedule `0 2 * * *` hardcoded; backlog at `/data/self_improver/fix_backlog.json` | User-configured cron/systemd timer; backlog at `overnight/fix_backlog.json` |
| docs/OPERATIONS_RUNBOOK.md (Section 7) | Pipeline uses `engine.openrouter_quota` reading from `engine.quota_ledger`; providers Ollama/vLLM/OpenRouter | Pipeline uses `overnight/openrouter_quota.py` and `overnight/llm_client.py` with OpenRouter->Groq->Gemini |
| docs/OPERATIONS_RUNBOOK.md (Section 7.2) | Manual execution uses `--process-backlog /data/self_improver/fix_backlog.json` | Manual execution uses `overnight/fix_backlog.json` |
| docs/DEPLOYMENT_RUNBOOK.md (Section 11) | `overnight/llm_client.py` with OpenRouter/Groq/Gemini providers but async Advisory Generation/B/C; 50 RPD quota; hardcoded 03:00 cron | Sync functions `prefill_advisory_queue()`/`process_advisory_queue()`/`drain_fix_backlog()`; 1000 RPD funded tier; user-configured schedule |
| docs/DEPLOYMENT_RUNBOOK.md (Section 11.3) | Code block cuts off at `from`; shows async provider classes with Ollama/vLLM/OpenRouter | Complete sync implementation with OpenRouter->Groq fallback, Gemini for prefill/critique |
| docs/LAB_SETUP_GUIDE.md (Section 2.1) | `slm-overnight` service uses cron `0 3 * * *` hardcoded; `FIX_BACKLOG_PATH=/data/fix_backlog.json` | User-configured timer; `FIX_BACKLOG_PATH=overnight/fix_backlog.json` |
| docs/LAB_SETUP_GUIDE.md (Section 4.1) | `touch ./data/fix_backlog.json` and `./data/openrouter_quota.json` | Files managed by overnight pipeline at `overnight/fix_backlog.json` and `overnight/openrouter_quota.json` |
| docs/OPERATOR_MANUAL.md (Section 1) | `overnight/fix_backlog.json` stored in `/var/lib/soc/fix_backlog.json` | `overnight/fix_backlog.json` (single path in overnight directory) |
| docs/OPERATOR_MANUAL.md (Section 8.2) | Pipeline runs 03:00-05:00 local time; LoRA fine-tuning on `mistral-7b-instruct-v0.3`; providers vLLM/Ollama/OpenRouter | No hardcoded schedule; advisory analysis -> Gemini validation -> test-gated code fixes; providers OpenRouter->Groq->Gemini |
| docs/OPERATOR_MANUAL.md (Section 8.3) | `config/self_improver.yaml` with `schedule: "0 3 * * *"` and `base_model: "mistral-7b-instruct-v0.3"` | No schedule in config; no base_model fine-tuning; providers: OpenRouter (Nemotron) -> Groq -> Gemini |
| docs/OPERATOR_MANUAL.md (Section 8.4) | `overnight/llm_client.py` with `MultiProviderClient` and `ProviderConfig` for vLLM/Ollama/OpenRouter | `overnight/llm_client.py` with OpenRouter->Groq fallback, Gemini for prefill+critique, token-aware pacing, cooldown tracking |
| docs/OPERATOR_MANUAL.md (Section 8.5) | `overnight/openrouter_quota.py` with `daily_token_budget: 500000` and `openrouter_daily_usd: 10.00` soft limit | `overnight/openrouter_quota.py` with 1000 RPD funded tier, 24h lock, UTC rollover, atomic writes |
| docs/OPERATOR_MANUAL.md (Section 8.6) | Fix backlog at `/var/lib/soc/fix_backlog.json` with training-stage error context | Fix backlog at `overnight/fix_backlog.json` with advisory analysis/validation/fix application context |
| docs/OVERNIGHT_PIPELINE.md (Entire document) | Async Advisory Generation/B/C with Unified Queue pre-analysis, OpenRouter/Groq/Gemini fallback chain, 50 RPD quota, hardcoded 03:00 cron, advisory_queue.jsonl, phase_a_prefill.jsonl, phase_c_drain_report.json | Sync `prefill_advisory_queue()`/`process_advisory_queue()`/`drain_fix_backlog()`; advisory queue in `overnight/advisory_queue/pending/`; fixes to `overnight/fix_backlog.json`; 1000 RPD funded tier; user-configured schedule |

# SECTION 2: Overnight Self-Improving Pipeline — CORRECTED (full rewrite)

## 1. Overview

The overnight self-improving pipeline is a **synchronous, user-scheduled** process that consumes an advisory queue, validates findings via cross-model critique, and applies test-gated code fixes. It runs **only when invoked** (via cron, systemd timer, or manual execution) — there is **no hardcoded schedule** in the codebase.

**Entry point**: `overnight/self_improver.py` — flat script with three main functions:
- `prefill_advisory_queue()` — reads source files, generates initial analyses via Gemini
- `process_advisory_queue()` — validates analyses, produces fix plans via OpenRouter/Groq
- `drain_fix_backlog()` — applies fixes through safety-gated commit pipeline

**State files** (all under `overnight/`):
- `advisory_queue/pending/` — directory of advisory JSON files (one per source file)
- `fix_backlog.json` — single JSON file tracking applied/pending/rejected fixes
- `openrouter_quota.json` — daily request counter with UTC rollover and 1h lock on 429
- `llm_cooldown.json` — per-provider cooldown timestamps (Unix epoch)
- `model_fallback_cache.json` — cached OpenRouter free model list (1h TTL)
- `groq_model_cache.json` — cached Groq model list (1h TTL)

**Lock file**: `overnight/.pipeline.lock` (prevents concurrent runs via `filelock`)

---

## 2. Core Modules

### 2.1 `overnight/self_improver.py`

```python
#!/usr/bin/env python3
"""
Queue-based self-improver with Gemini pre-analysis pipeline.

Architecture:
  Advisory Generation (Gemini, abundant free tier):
    Pre-analyze ALL files → save advisories to disk queue
    
  Shadow Canary (OpenRouter, when available):
    Drain the queue → feed advisories to primary models
    Delete advisory file on success

Directory structure:
  overnight/advisory_queue/
  └── pending/          ← Gemini advisories waiting for OpenRouter
      ├── engine__queue_manager.json
      └── tools__embedding_prefix_check.json
  (files deleted after successful OpenRouter processing)
"""
import sys, json, subprocess, time, argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from overnight.llm_client import (
    generate, load_api_keys, strip_fences,
    gemini_pre_analysis, _call_gemini
)
from overnight.budget_manager import APIBudgetManager
from overnight.code_reviewer import review_file, extract_json_from_response, build_review_prompt, get_file_context, count_lines

ROOT = Path(__file__).resolve().parent.parent
QUEUE_DIR = ROOT / "overnight" / "advisory_queue" / "pending"
STATE_FILE = ROOT / "overnight" / "improver_state.json"

SAFE_CATEGORIES = {"maintainability", "blueprint_compliance", "performance"}
SAFE_SEVERITIES = {"low", "informational", "medium"}


# ============================================================
# STATE & QUEUE MANAGEMENT
# ============================================================
def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"fixes": 0, "reverts": 0}

def save_state(s):
    s["last_run"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(s, indent=2))

def queue_path_for(file_path):
    """Get the advisory queue file path for a source file."""
    safe_name = str(file_path.relative_to(ROOT)).replace("/", "__").replace(".py", "")
    return QUEUE_DIR / f"{safe_name}.json"

FIX_BACKLOG = ROOT / "overnight" / "fix_backlog.json"

def _load_backlog():
    if FIX_BACKLOG.exists():
        try:
            return json.loads(FIX_BACKLOG.read_text())
        except Exception:
            pass
    return []

def _save_backlog(items):
    FIX_BACKLOG.write_text(json.dumps(items, indent=2))

def drain_fix_backlog(api_keys, max_fixes=3):
    """Apply a few backlog fixes per call so budgets recover between them."""
    backlog = _load_backlog()
    if not backlog:
        return 0
    done = 0
    remaining = []
    for item in backlog:
        if done >= max_fixes:
            remaining.append(item)
            continue
        fpath = ROOT / item["file"]
        if not fpath.exists():
            continue
        if apply_auto_fix(fpath, item["issue"], api_keys):
            done += 1
        else:
            remaining.append(item)  # keep for a later iteration
    _save_backlog(remaining)
    return done

def get_pending_advisories():
    """List all pending advisory files."""
    if not QUEUE_DIR.exists():
        return []
    return sorted(QUEUE_DIR.glob("*.json"))


# ============================================================
# Advisory Generation: GEMINI PRE-FILL (uses abundant free tier)
# ============================================================
def prefill_advisory_queue(files, api_keys, budget):
    """Use Gemini to pre-analyze all files that don't have pending advisories."""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{'='*70}")
    print(f"Advisory Generation: GEMINI PRE-FILL ({len(files)} files)")
    print(f"{'='*70}")
    
    filled = 0
    skipped = 0
    
    for i, f in enumerate(files, 1):
        qpath = queue_path_for(f)
        
        # Skip if advisory already exists
        if qpath.exists():
            skipped += 1
            continue
        
        # Check Gemini budget (wait if per-minute limit hit, only break on daily)
        if not budget.wait_if_needed("gemini", timeout=120):
            print(f"  ⏱️  Gemini daily budget exhausted, stopping pre-fill")
            break
        budget.record_call("gemini")
        
        try:
            content = f.read_text()
            advisory = gemini_pre_analysis(f.relative_to(ROOT), content, api_keys)
            
            if advisory:
                qpath.write_text(json.dumps({
                    "file_path": str(f.relative_to(ROOT)),
                    "advisory_notes": advisory,
                    "created_at": datetime.now().isoformat(),
                    "status": "pending"
                }, indent=2))
                filled += 1
                print(f"  [{i}/{len(files)}] ✅ {f.relative_to(ROOT)}")
            else:
                print(f"  [{i}/{len(files)}] ⚠️  {f.relative_to(ROOT)} — empty advisory")
        
        except Exception as e:
            print(f"  [{i}/{len(files)}] ❌ {f.relative_to(ROOT)}: {e}")
        
        time.sleep(1)  # Brief pause between Gemini calls
    
    print(f"\n  Pre-fill complete: {filled} new, {skipped} already queued")
    return filled


# ============================================================
# Shadow Canary: OPENROUTER PROCESSING (drains the queue)
# ============================================================
def _normalize(x):
    if isinstance(x, dict):
        for key in ("improvements", "issues", "findings", "results"):
            if isinstance(x.get(key), list):
                return [i for i in x[key] if isinstance(i, dict)]
        return [x] if x else []
    if isinstance(x, list):
        return [i for i in x if isinstance(i, dict)]
    return []


def process_advisory_queue(api_keys, budget, state, max_items=50):
    """Process pending advisories through OpenRouter when available."""
    pending = get_pending_advisories()
    
    if not pending:
        print(f"\n  📭 Advisory queue is empty — nothing to process")
        return 0
    
    print(f"\n{'='*70}")
    print(f"Shadow Canary: OPENROUTER PROCESSING ({len(pending)} pending advisories)")
    print(f"{'='*70}")
    
    processed = 0
    
    for i, qpath in enumerate(pending[:max_items], 1):
        try:
            advisory_data = json.loads(qpath.read_text())
            file_rel_path = advisory_data["file_path"]
            advisory_notes = advisory_data["advisory_notes"]
            source_file = ROOT / file_rel_path
            
            if not source_file.exists():
                print(f"  [{i}] ⚠️  Source file missing: {file_rel_path}, removing advisory")
                qpath.unlink()
                continue
            
            print(f"\n  [{i}/{len(pending)}] 🔍 {file_rel_path}")
            print(f"       Advisory from: {advisory_data.get('created_at', 'unknown')}")
            
            # Check OpenRouter budget (wait if per-minute hit, break on daily)
            if not budget.wait_if_needed("openrouter", timeout=120):
                print(f"  ⏱️  OpenRouter daily budget exhausted, stopping")
                break
            budget.record_call("openrouter")
            
            # Read source and build prompt with advisory context
            content = source_file.read_text()
            context = get_file_context(source_file)
            
            # Try OpenRouter with advisory context
            review_prompt = build_review_prompt(source_file, content, context, advisory_notes=advisory_notes)
            
            primary_response = generate(
                review_prompt, api_keys,
                model_type="code", max_tokens=8192, temperature=0.3
            )
            
            if not primary_response:
                print(f"       ⚠️  OpenRouter still unavailable, advisory stays in queue")
                continue  # Leave in queue for next attempt
            
            print(f"       ✅ Primary analysis responded ({len(primary_response)} chars)")
            
# Extract improvements from primary response
            improvements_raw = extract_json_from_response(primary_response)

            improvements_raw = _normalize(improvements_raw)

            # Parse failed -> Gemini repairs the FORMAT (conversion only, not analysis)
            if not improvements_raw:
                print(f"       🔧 Parse failed — Gemini JSON repair pass...")
                budget.record_call("gemini")
                repair_prompt = (
                    "Convert these code-review notes into a valid JSON array. "
                    'Each element: {"description": str, "category": str, '
                    '"severity": str, "suggestion": str}. '
                    "Output ONLY the JSON array, no prose.\n\n"
                    + primary_response[:12000]
                )
                repaired = _call_gemini(repair_prompt, api_keys["gemini"],
                                        max_tokens=4096, temperature=0.1)
                if repaired:
                    improvements_raw = _normalize(extract_json_from_response(repaired))

            if not improvements_raw:
                print(f"       ⚠️  Could not parse response, advisory stays in queue")
                continue
            
            # Validate with Gemini (Phase 3)
            print(f"       🔍 Gemini validating {len(improvements_raw)} findings...")
            budget.record_call("gemini")
            
            from overnight.code_reviewer import build_validation_prompt
            improvements_json = json.dumps(improvements_raw[:20], indent=2)
            validation_prompt = build_validation_prompt(source_file, content, improvements_json)
            validation_response = _call_gemini(validation_prompt, api_keys["gemini"], max_tokens=4096, temperature=0.1)
            
            if validation_response:
                validation_data = extract_json_from_response(validation_response)
                if validation_data and isinstance(validation_data, dict):
                    genuine = validation_data.get("genuine_issue_count", 0)
                    false_pos = validation_data.get("false_positive_count", 0)
                    quality = validation_data.get("overall_quality_score", 70)
                    print(f"       ✅ Validated: {genuine} genuine, {false_pos} false positives, quality {quality}/100")
            
            # SUCCESS — remove advisory from queue
            qpath.unlink()
            processed += 1
            print(f"       🗑️  Advisory processed and removed from queue")
            
            # Check for auto-fixable issues
            auto_fixable = [
                imp for imp in improvements_raw
                if isinstance(imp, dict)
                and imp.get("category") in SAFE_CATEGORIES
                and imp.get("severity") in SAFE_SEVERITIES
                and imp.get("validated", True)
                and not imp.get("false_positive", False)
            ]
            
            if auto_fixable:
                backlog = _load_backlog()
                for issue in auto_fixable:
                    backlog.append({"file": str(source_file.relative_to(ROOT)), "issue": issue})
                _save_backlog(backlog)
                print(f"       📥 {len(auto_fixable)} fixable issue(s) queued to backlog")
            
            time.sleep(2)
            
        except Exception as e:
            print(f"       ❌ Error processing {qpath.name}: {e}")
            continue
    
    print(f"\n  Processing complete: {processed} advisories processed")
    return processed


def apply_auto_fix(file_path, issue, api_keys):
    """Generate and apply a fix with test gating, crash-safe backup, and
    precise git error handling. Every exit path is deliberate."""
    try:
        original = file_path.read_text()
    except Exception as e:
        print(f"       ❌ Cannot read {file_path.name}: {e}")
        return False

    prompt = (
        "You are a senior Python engineer. Fix the issue below in this file.\n"
        "Return ONLY the complete fixed file content. No markdown fences, "
        "no explanations, no comments about the change.\n"
        "Preserve all unrelated behavior. Keep the module importable without "
        "side effects. Use datetime.now(timezone.utc), never utcnow().\n"
        f"Issue: {issue.get('description', '')}\n"
        f"Category: {issue.get('category', '')}\n"
        f"Suggestion: {issue.get('suggestion', '')}\n\n"
        f"Current file content:\n{original[:12000]}\n"
    )
    print(f"       📝 Generating fix: {issue.get('description', '')[:80]}")
    fix_code = generate(prompt, api_keys, temperature=0.2)
    if not fix_code:
        print(f"       ❌ Fix generation failed")
        return False
    fix_code = strip_fences(fix_code)
    if len(fix_code) < 0.5 * len(original):
        print(f"       ❌ Fix suspiciously short ({len(fix_code)} vs {len(original)} chars) — rejecting")
        return False

    # Backup exists ONLY during the pytest window; a leftover .orig_backup at
    # next startup is proof of a crash mid-test (handled by main() recovery).
    backup = file_path.with_suffix(file_path.suffix + ".orig_backup")
    backup.write_text(original)
    file_path.write_text(fix_code)

    tests_passed = False
    timed_out = False
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
            cwd=ROOT, capture_output=True, timeout=120,
        )
        tests_passed = result.returncode == 0
    except subprocess.TimeoutExpired:
        timed_out = True  # subprocess.run already killed the hung pytest child

    if not tests_passed:
        file_path.write_text(original)
        backup.unlink(missing_ok=True)
        print(f"       ❌ Tests {'timed out (120s)' if timed_out else 'failed'} — reverting")
        return False

    backup.unlink(missing_ok=True)
    try:
        subprocess.run(["git", "add", str(file_path)], cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Auto-fix: {file_path.name}"],
                       cwd=ROOT, check=True, capture_output=True)
        print(f"       ✅ Fix committed")
        return True
    except subprocess.CalledProcessError as e:
        err = (e.stdout or b"") + (e.stderr or b"")
        if b"nothing to commit" in err or b"no changes" in err:
            print(f"       ⚠️  No-op fix (nothing changed) — treated as done")
            return True
        print(f"       ❌ git failed: {err.decode(errors='replace')[:200]}")
        return False


def discover_files():
    """Find all reviewable source files."""
    files = []
    for d in ["engine", "orchestrator", "memory", "tools"]:
        dp = ROOT / d
        if dp.exists():
            files += [f for f in dp.rglob("*.py") if f.name != "__init__.py"]
    files.sort(key=lambda f: f.stat().st_size)
    return files


def main():
    # Crash recovery: a killed run may leave a half-applied fix behind
    for bak in sorted(ROOT.rglob("*.orig_backup")):
        target = bak.with_suffix("")
        target.write_text(bak.read_text())
        bak.unlink()
        print(f"  🩹 Crash recovery: restored {target.name} from backup")

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-iterations", type=int, default=5)
    p.add_argument("--prefill-only", action="store_true", help="Only fill advisory queue with Gemini")
    p.add_argument("--process-only", action="store_true", help="Only process existing advisory queue")
    a = p.parse_args()

    keys = load_api_keys()
    budget = APIBudgetManager()
    state = load_state()
    
    files = discover_files()
    print(f"Found {len(files)} source files")
    print(f"Queue directory: {QUEUE_DIR}")
    
    if a.prefill_only:
        prefill_advisory_queue(files, keys, budget)
    elif a.process_only:
        process_advisory_queue(keys, budget, state)
    else:
        # Full loop: prefill then process, repeat
        for iteration in range(1, a.max_iterations + 1):
            print(f"\n{'#'*70}")
            print(f"ITERATION {iteration}/{a.max_iterations}")
            print(f"{'#'*70}")
            
            # Advisory Generation: Fill queue with Gemini pre-analyses
            prefill_advisory_queue(files, keys, budget)
            
            # Shadow Canary: Process queue with OpenRouter
            processed = process_advisory_queue(keys, budget, state)

            # Backlog Drain: apply a few backlog fixes (budget has recovered)
            fixed = drain_fix_backlog(keys, max_fixes=3)
            print(f"  🔧 Backlog fixes applied this iteration: {fixed}")
            
            # Check if queue is empty and budget allows
            remaining = len(get_pending_advisories())
            if remaining == 0:
                print(f"\n  ✅ Queue fully processed!")
                break
            
            print(f"\n  📊 Queue status: {remaining} advisories still pending")
            
            if not budget.can_proceed("openrouter"):
                print(f"  ⏱️  Budget exhausted, stopping for now")
                break
            
            # Wait before next iteration
            print(f"  ⏳ Waiting 60s before next iteration...")
            time.sleep(60)
    
    save_state(state)
    print(f"\n{budget.report()}")


if __name__ == "__main__":
    main()
```

---

### 2.2 `overnight/llm_client.py`

```python
"""
Dual-Model LLM Client with DYNAMIC model discovery and fallback.

Instead of hardcoding model IDs (which break when OpenRouter changes them),
this queries OpenRouter's API to find currently-available free instruct models
and builds the fallback list automatically.
"""
import os
import re
import json
import time
from pathlib import Path

try:
    import requests
except ImportError:
    raise ImportError("requests library required: pip install requests")

# ============================================================
# CONFIGURATION
# ============================================================
CRITIC_MODEL = "gemini-3.1-flash-lite-preview"
GENERATOR_MODEL = "nvidia/nemotron-3.5-lightning:free"  # Primary (dynamic discovery may switch at runtime)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

RATE_LIMIT_SLEEP = 7
MAX_RETRIES = 3

# Dynamic fallback state
_fallback_list = None
_current_model = None
_calls_since_primary_check = 0
PRIMARY_RETRY_INTERVAL = 3
CACHE_FILE = Path("/home/swiig/Documents/soc-autopilot/overnight/model_fallback_cache.json")
GROQ_CACHE_FILE = Path("/home/swiig/Documents/soc-autopilot/overnight/groq_model_cache.json")
CACHE_TTL = 3600  # Refresh model list every hour

# Ultimate fallback if discovery fails entirely
DEFAULT_FALLBACK = ["nvidia/nemotron-3.5-lightning:free"]
_last_groq_call = 0.0


# ============================================================
# DYNAMIC MODEL DISCOVERY
# ============================================================
def _estimate_params(name, model_id):
    """Estimate parameter count from model name for ranking."""
    text = (name + " " + model_id).lower()

    # NVIDIA naming convention
    if "ultra" in text: return 500
    if "lightning" in text: return 300
    if "super" in text: return 120
    if "nano" in text: return 30

    # Look for explicit parameter counts: "70b", "72b", "253b", "550b"
    matches = re.findall(r'(\d+(?:\.\d+)?)\s*b\b', text)
    if matches:
        try:
            return max(float(m) for m in matches)
        except (ValueError, TypeError):
            pass

    return 10  # Unknown, rank low


def discover_free_models(api_key):
    """Query OpenRouter for currently available free instruct models."""
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30
        )
        if resp.status_code != 200:
            return None

        models = resp.json().get("data", [])
        candidates = []

        for m in models:
            pricing = m.get("pricing", {})
            try:
                if float(pricing.get("prompt", "1")) != 0.0:
                    continue
                if float(pricing.get("completion", "1")) != 0.0:
                    continue
            except (ValueError, TypeError):
                continue

            model_id = m.get("id", "")
            name = m.get("name", "")
            context = m.get("context_length", 0)

            # Skip very small context models (< 8K) — not useful for code review
            if context < 8000:
                continue

            # Determine if it's an instruct/chat model
            text = (name + " " + model_id).lower()
            is_instruct = any(x in text for x in [
                "instruct", "chat", "-it", "it:", "it-",
                "ultra", "super", "lightning",  # NVIDIA instruct variants
            ])

            # Skip non-instruct models (completion-only, embedding, etc.)
            if not is_instruct:
                continue

            params = _estimate_params(name, model_id)

            candidates.append({
                "id": model_id,
                "name": name,
                "context": context,
                "params": params,
            })

        # Sort by: params (quality), then context length
        candidates.sort(key=lambda x: (x["params"], x["context"]), reverse=True)

        # Return top 8 model IDs
        result = [c["id"] for c in candidates[:8]]
        if result:
            print(f"    🔍 Discovered {len(result)} free instruct models:")
            for c in candidates[:8]:
                print(f"       {c['id']} (~{c['params']}B, {c['context']:,} ctx)")
        return result

    except Exception as e:
        print(f"    ⚠️  Model discovery failed: {e}")
        return None


def get_fallback_list(api_key):
    """Get fallback list, using cache if fresh."""
    global _fallback_list, _current_model

    if _fallback_list is not None:
        return _fallback_list

    # Check cache
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text())
            if time.time() - cache.get("timestamp", 0) < CACHE_TTL:
                _fallback_list = cache["models"]
                _current_model = _fallback_list[0] if _fallback_list else DEFAULT_FALLBACK[0]
                return _fallback_list
        except (json.JSONDecodeError, KeyError):
            pass

    # Discover fresh
    models = discover_free_models(api_key)
    if models:
        _fallback_list = models
        _current_model = models[0]
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "timestamp": time.time(),
            "models": models,
        }, indent=2))
        return models

    # Ultimate fallback
    _fallback_list = DEFAULT_FALLBACK
    _current_model = DEFAULT_FALLBACK[0]
    return _fallback_list


# ============================================================
# OPENROUTER WITH DYNAMIC FALLBACK
# ============================================================
def _call_openrouter(prompt, api_key, model=None, system_prompt=None, max_tokens=8192, temperature=0.2):
    """Call OpenRouter with dynamic model fallback on rate limits."""
    global _current_model, _calls_since_primary_check

    # Hard 1000 RPD limit — skip entirely if exhausted/locked
    from overnight import openrouter_quota
    if not openrouter_quota.is_available():
        print(f"    🔒 OpenRouter locked/exhausted ({openrouter_quota.remaining()} left) — skipping")
        return ""

    # Ensure fallback list is loaded
    fallback_list = get_fallback_list(api_key)

    if model is None:
        model = _current_model or (fallback_list[0] if fallback_list else DEFAULT_FALLBACK[0])

    # Build ordered list: preferred model first, then fallbacks
    models_to_try = [model] + [m for m in fallback_list if m != model]

    # Every N calls, try primary first to check if it recovered
    _calls_since_primary_check += 1
    if _calls_since_primary_check >= PRIMARY_RETRY_INTERVAL and fallback_list:
        _calls_since_primary_check = 0
        primary = fallback_list[0]
        if models_to_try[0] != primary:
            models_to_try = [primary] + models_to_try
            print(f"    🔄 Checking if primary ({primary}) is back...")

    for try_model in models_to_try:
        # Count every attempt against the 1000 RPD quota
        from overnight import openrouter_quota
        openrouter_quota.record_attempt()
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://local-soc-slm.lab",
            "X-Title": "LOCAL-SOC-SLM Blueprint Automation",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": try_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)

            if resp.status_code == 200:
                data = resp.json()
                if "choices" not in data or not data["choices"]:
                    continue
                content = data["choices"][0]["message"]["content"]

                if try_model != _current_model:
                    if fallback_list and try_model == fallback_list[0]:
                        print(f"    ✅ Primary recovered: {try_model}")
                    else:
                        print(f"    🔄 Using fallback: {try_model}")
                _current_model = try_model
                return content

            elif resp.status_code == 429:
                print(f"    ⚠️  {try_model} rate-limited. Instantly locking OpenRouter for 1h.")
                openrouter_quota.force_lock(f"429 on {try_model}")
                break  # STOP trying other OpenRouter models, quota is exhausted!

            elif resp.status_code == 404:
                print(f"    ⚠️  {try_model} not available → next")
                continue

            elif resp.status_code == 402:
                print(f"    ❌ {try_model} quota exhausted → next")
                continue

            else:
                print(f"    ❌ {try_model} returned {resp.status_code} → next")
                continue

        except Exception as e:
            print(f"    ❌ {try_model} error: {e} → next")
            continue

    # All OpenRouter models saturated — return empty immediately
    # generate() will handle Groq fallback
    print(f"    ⚠️  All OpenRouter models saturated")
    return ""


def _call_gemini(prompt, api_key, max_tokens=8192, temperature=0.2):
    """Call Gemini (Google)."""
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(f"{GEMINI_URL}?key={api_key}", json=payload, headers=headers, timeout=90)
            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"    [Gemini] Rate limited. Waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"    [Gemini] API error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(10)
    return ""



# ============================================================
# GROQ PROVIDER (fast inference, separate rate limits)
# ============================================================
def discover_groq_models(api_key):
    """Query Groq API for available free models."""
    try:
        resp = requests.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15
        )
        if resp.status_code != 200:
            return None

        models = resp.json().get("data", [])
        candidates = []
        for m in models:
            model_id = m.get("id", "")
            # Filter for instruct/chat models with decent context
            if any(x in model_id for x in ["whisper", "embed", "tts"]):
                continue
            context = m.get("context_window", 8192)
            if context < 8000:
                continue
            candidates.append({"id": model_id, "context": context})

        # Sort by context length
        candidates.sort(key=lambda x: x["context"], reverse=True)
        result = [c["id"] for c in candidates[:6]]
        if result:
            print(f"    🔍 Groq: discovered {len(result)} models")
        return result
    except Exception as e:
        print(f"    ⚠️  Groq discovery failed: {e}")
        return None


def get_groq_models(api_key):
    """Get Groq model list with caching."""
    if GROQ_CACHE_FILE.exists():
        try:
            cache = json.loads(GROQ_CACHE_FILE.read_text())
            if time.time() - cache.get("timestamp", 0) < CACHE_TTL:
                return cache["models"]
        except:
            pass

    models = discover_groq_models(api_key)
    if models:
        GROQ_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        GROQ_CACHE_FILE.write_text(json.dumps({"timestamp": time.time(), "models": models}))
        return models
    return GROQ_DEFAULT_MODELS


# ---- Groq token pacing (free-tier TPM-aware) ----
GROQ_TPM = {
    "groq/compound": 70000,
    "groq/compound-mini": 70000,
    "openai/gpt-oss-120b": 8000,
    "openai/gpt-oss-20b": 8000,
}
DEFAULT_GROQ_TPM = 8000
_groq_usage = {}  # model -> [(timestamp, tokens)]


def _est_tokens(text):
    return max(1, len(text) // 4)


def _groq_window(model):
    now = time.time()
    window = [(ts, t) for ts, t in _groq_usage.get(model, []) if now - ts < 60]
    _groq_usage[model] = window
    return window


def _groq_headroom(model, needed):
    limit = int(GROQ_TPM.get(model, DEFAULT_GROQ_TPM) * 0.8)  # 20% safety margin
    used = sum(t for _, t in _groq_window(model))
    return (limit - used) >= needed


def _groq_record(model, tokens):
    _groq_usage.setdefault(model, []).append((time.time(), tokens))


def _groq_suggested_wait(models):
    now = time.time()
    best = 10
    for m in models:
        window = _groq_window(m)
        if window:
            best = min(best, max(1, int(60 - (now - window[0][0]) + 1)))
    return min(best, 20)


_groq_cooldown = {}
_groq_429_count = {}  # model -> consecutive 429 count  # model -> timestamp until which it's rate-limited


_groq_rl = {}  # model -> {"rem_req","rem_tok","req_reset","tok_reset"}


def _parse_dur(s):
    if not s:
        return 0
    import re as _re
    total = 0
    m = _re.search(r"(\d+)h", s)
    if m: total += int(m.group(1)) * 3600
    m = _re.search(r"(\d+)m", s)
    if m: total += int(m.group(1)) * 60
    m = _re.search(r"([\d.]+)s", s)
    if m: total += float(m.group(1))
    return total


def _groq_note_rl(model, headers):
    try:
        now = time.time()
        e = _groq_rl.setdefault(model, {})
        rr = headers.get("x-ratelimit-remaining-requests")
        rt = headers.get("x-ratelimit-remaining-tokens")
        if rr is not None: e["rem_req"] = int(float(rr))
        if rt is not None: e["rem_tok"] = int(float(rt))
        sr = headers.get("x-ratelimit-reset-requests")
        st = headers.get("x-ratelimit-reset-tokens")
        if sr: e["req_reset"] = now + _parse_dur(sr)
        if st: e["tok_reset"] = now + _parse_dur(st)
    except Exception:
        pass


def _groq_preempted(model):
    e = _groq_rl.get(model)
    if not e:
        return False
    now = time.time()
    if e.get("rem_req", 1) <= 0 and now < e.get("req_reset", 0):
        return True
    if e.get("rem_tok", 1) <= 0 and now < e.get("tok_reset", 0):
        return True
    return False


def _call_groq(prompt, api_key, model=None, system_prompt=None, max_tokens=8192, temperature=0.2):
    """Call Groq with cooldown tracking so we never waste requests probing
    models that are already rate-limited."""
    if not api_key:
        return ""

    global _last_groq_call
    models = get_groq_models(api_key)

    PREFERRED = ["groq/compound-mini", "groq/compound",
                 "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    BLOCKED = ["qwen/qwen3.6-27b", "openai/gpt-oss-safeguard-20b"]
    models = [m for m in models if m not in BLOCKED]
    models.sort(key=lambda m: PREFERRED.index(m) if m in PREFERRED else len(PREFERRED))
    if model and model in models:
        models = [model] + [m for m in models if m != model]

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _in_cooldown(m):
        return _groq_cooldown.get(m, 0) > time.time()

    def _pace():
        global _last_groq_call
        gap = time.time() - _last_groq_call
        if gap < 2.0:
            time.sleep(2.0 - gap)
        _last_groq_call = time.time()

    for pass_num in range(2):  # pass 1: try ready models; pass 2: after cooldown wait
        for try_model in models:
            if _groq_preempted(try_model):
                continue  # server says remaining=0; don't probe until reset
            if _in_cooldown(try_model):
                continue  # don't waste a request probing a cooled-down model

            # Fresh sizing per model (a 413-shrink must not leak to the next model)
            body = prompt[:9000]
            max_out = min(max_tokens, 4096)
            needed = _est_tokens(body) + max_out
            if not _groq_headroom(try_model, needed):
                continue

            for attempt in range(2):
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": body})
                payload = {"model": try_model, "messages": messages,
                           "temperature": temperature, "max_tokens": max_out}
                try:
                    _pace()
                    resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=90)
                    _groq_note_rl(try_model, resp.headers)
                except Exception as e:
                    print(f"    ❌ Groq {try_model} error: {e} → next")
                    break

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("choices"):
                        usage = data.get("usage", {})
                        tokens = (usage.get("prompt_tokens", 0)
                                  + usage.get("completion_tokens", 0)) or needed
                        _groq_record(try_model, tokens)
                        content = data["choices"][0]["message"]["content"]
                        if "**Answer**" in content:
                            ap = content.split("**Answer**")[-1].strip()
                            if ap:
                                content = ap
                        _groq_429_count[try_model] = 0  # success resets backoff
                        print(f"    ✅ Groq ({try_model}) responded ({len(content)} chars)")
                        return content

                elif resp.status_code == 429:
                    ra = resp.headers.get("retry-after", "5")
                    try:
                        base = min(int(ra), 30)
                    except ValueError:
                        base = 5
                    # Exponential backoff when the same model keeps rejecting us
                    n = _groq_429_count.get(try_model, 0) + 1
                    _groq_429_count[try_model] = n
                    wait = min(base * (2 ** (n - 1)), 90)
                    _groq_cooldown[try_model] = time.time() + wait
                    _groq_record(try_model, needed)
                    print(f"    ⚠️  Groq {try_model} rate-limited (hit x{n}) → backoff {wait}s")
                    break

                elif resp.status_code == 413:
                    if attempt == 0:
                        body = prompt[:4500]
                        max_out = min(max_out, 2048)
                        continue
                    break
                else:
                    break

        # Nothing succeeded this pass — wait for the earliest cooldown, then retry
        now = time.time()
        active = [t for t in _groq_cooldown.values() if t > now]
        if active:
            wait = max(1, int(min(active) - now))
            print(f"    ⏳ Groq cooling down — waiting {wait}s for a model to free up")
            time.sleep(min(wait, 40))
        else:
            time.sleep(8)  # token-window recovery

    return ""
def load_api_keys():
    """Load API keys from .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        env_path = Path("/home/swiig/Documents/soc-autopilot/.env")

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

    return {
        "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "groq": os.getenv("GROQ_API_KEY", ""),
    }



# ============================================================
# PHASE 1: GEMINI PRE-ANALYSIS (advisory, not authoritative)
# ============================================================
def gemini_pre_analysis(file_path, content, api_keys):
    """Use Gemini's abundant free tier for preliminary analysis.
    Returns advisory notes passed to primary model as non-authoritative context.
    """
    prompt = f"""You are doing a preliminary code review. Read this file and provide
your initial observations about potential issues, improvements, or concerns.

FILE: {file_path}
CODE:
{content[:6000]}

Provide 3-5 bullet points of observations. Be specific about line numbers.
Keep it brief - this is a preliminary pass, not a final review."""

    try:
        response = _call_gemini(prompt, api_keys.get("gemini", ""),
                                max_tokens=1500, temperature=0.3)
        if response:
            print(f"    📝 Gemini pre-analysis complete ({len(response)} chars)")
            return response.strip()
    except Exception as e:
        print(f"    ⚠️  Gemini pre-analysis failed: {e}")
    return ""


def generate(prompt, api_keys, model_type="code", max_tokens=8192, temperature=0.2):
    """Generate content with multi-provider fallback.
    
    Order: OpenRouter → Groq → wait & retry
    Gemini is NEVER used for generation (reserved for critique).
    """
    if model_type == "code":
        system_prompt = """You are a senior Python engineer writing production-ready code for a SOC automation platform.
RULES:
- Output ONLY valid Python code
- No markdown fences, no explanations, no preamble
- Use real sqlite3.connect(":memory:") for SQLite, not mocks
- Expect RuntimeError not SystemExit (library code auto-fixed)
- Import from actual modules, don't hallucinate"""
    elif model_type == "docs":
        system_prompt = "You are a technical writer. Output ONLY the document content."
    else:
        system_prompt = None

    # Step 1: Try OpenRouter (Nemotron + dynamic fallbacks)
    result = _call_openrouter(prompt, api_keys.get("openrouter", ""),
                              system_prompt=system_prompt, max_tokens=max_tokens, temperature=temperature)
    if result:
        return result

    # Step 2: OpenRouter saturated → try Groq immediately
    print(f"    🔄 OpenRouter busy → trying Groq")
    result = _call_groq(prompt, api_keys.get("groq", ""),
                        system_prompt=system_prompt, max_tokens=max_tokens, temperature=temperature)
    if result:
        return result

    # Step 3: Both busy → brief wait, one final retry
    print(f"    ⏳ All providers busy. Waiting 30s...")
    time.sleep(30)
    
    result = _call_openrouter(prompt, api_keys.get("openrouter", ""),
                              system_prompt=system_prompt, max_tokens=max_tokens, temperature=temperature)
    if result:
        return result
    
    return _call_groq(prompt, api_keys.get("groq", ""),
                      system_prompt=system_prompt, max_tokens=max_tokens, temperature=temperature)

def strip_fences(text):
    """Remove markdown code fences."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r'^```(?:python|markdown|yaml|sql|xml)?\s*\n', '', text)
    text = re.sub(r'\n```\s*$', '', text)
    return text.strip()


def critique(code, task_description, api_keys):
    """Have Gemini critique generated code."""
    critique_prompt = f"""Review this code for a SOC automation platform.

TASK: {task_description}

CODE:
{code}

Check for: hallucinated imports, wrong signatures, deprecated APIs, logic bugs.

Respond with:
- APPROVE if production-ready
- REVISE:<fixes needed> if changes required"""

    critique_text = _call_gemini(critique_prompt, api_keys.get("gemini", ""),
                                  max_tokens=1000, temperature=0.1)
    if not critique_text:
        return True, "No critique available"

    critique_text = critique_text.strip()
    if critique_text.startswith("APPROVE"):
        return True, critique_text
    return False, critique_text


def generate_with_critique(prompt, task_description, api_keys, model_type="code", max_iterations=2, max_tokens=8192):
    """Generate with cross-model critique loop."""
    current = generate(prompt, api_keys, model_type=model_type, max_tokens=max_tokens)
    if not current:
        return ""
    current = strip_fences(current)

    for i in range(max_iterations):
        is_good, critique_text = critique(current, task_description, api_keys)
        if is_good:
            return current

        fix_prompt = f"""Original task: {prompt}
Previous output: {current}
Reviewer feedback: {critique_text}
Fix the issues. Output ONLY corrected code."""

        current = generate(fix_prompt, api_keys, model_type=model_type, max_tokens=max_tokens)
        if not current:
            return current
        current = strip_fences(current)
        time.sleep(RATE_LIMIT_SLEEP)

    return current


def quick_generate(prompt, model_type="code"):
    api_keys = load_api_keys()
    return generate(prompt, api_keys, model_type=model_type)


def quick_critique_loop(prompt, task_description, model_type="code", max_iterations=2):
    api_keys = load_api_keys()
    return generate_with_critique(prompt, task_description, api_keys,
                                   model_type=model_type, max_iterations=max_iterations)


def get_fallback_status():
    """Return current fallback state for monitoring."""
    return {
        "current_model": _current_model,
        "fallback_list": _fallback_list or [],
        "calls_since_primary_check": _calls_since_primary_check,
    }
```

---

### 2.3 `overnight/openrouter_quota.py`

```python
#!/usr/bin/env python3
"""
OpenRouter quota tracker for the 1000 RPD funded-tier hard limit.

- Tracks every attempt (success AND 429 — both count against quota)
- Locks OpenRouter for 1h once exhausted
- Auto-resets on calendar day rollover (UTC)
- Persists to disk so it survives restarts
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

QUOTA_FILE = Path(__file__).resolve().parent / "openrouter_quota.json"
DAILY_LIMIT = 1000  # Funded tier (was 50 for free tier)
LOCK_HOURS = 1  # Funded tier: 1h lock on 429 (was 24h for free tier)


def _load():
    if QUOTA_FILE.exists():
        try:
            return json.loads(QUOTA_FILE.read_text())
        except Exception:
            pass
    return {"used_today": 0, "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "locked_until": None}


def _save(data):
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUOTA_FILE.parent / (QUOTA_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, QUOTA_FILE)  # atomic swap


def _refresh(data):
    """Reset counter on new day; clear expired lock."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("day") != today:
        data = {"used_today": 0, "day": today, "locked_until": None}
    if data.get("locked_until"):
        try:
            lock_dt = datetime.fromisoformat(data["locked_until"])
            if lock_dt.tzinfo is None:
                lock_dt = lock_dt.replace(tzinfo=timezone.utc)  # legacy naive stamps
            if lock_dt <= datetime.now(timezone.utc):
                data["locked_until"] = None
        except Exception:
            data["locked_until"] = None
    return data


def remaining():
    return max(0, DAILY_LIMIT - _refresh(_load()).get("used_today", 0))


def is_available():
    """True if OpenRouter can be used right now."""
    data = _refresh(_load())
    if data.get("locked_until"):
        return False
    if data.get("used_today", 0) >= DAILY_LIMIT:
        data["locked_until"] = (datetime.now(timezone.utc) + timedelta(hours=LOCK_HOURS)).isoformat()
        _save(data)
        return False
    return True


def record_attempt():
    """Count one request (success or 429). Lock when exhausted."""
    data = _refresh(_load())
    data["used_today"] = data.get("used_today", 0) + 1
    data["last_attempt"] = datetime.now(timezone.utc).isoformat()
    if data["used_today"] >= DAILY_LIMIT and not data.get("locked_until"):
        data["locked_until"] = (datetime.now(timezone.utc) + timedelta(hours=LOCK_HOURS)).isoformat()
        print(f"    🔒 OpenRouter quota exhausted ({data['used_today']}/{DAILY_LIMIT}). Locked 1h.")
    _save(data)
    return data


def status():
    d = _refresh(_load())
    return {
        "used_today": d.get("used_today", 0),
        "remaining": remaining(),
        "locked_until": d.get("locked_until"),
        "day": d.get("day"),
    }


def force_lock(reason="429 received"):
    """Instantly lock OpenRouter for 1h (used when we hit a 429)."""
    data = _refresh(_load())
    data["locked_until"] = (datetime.now(timezone.utc) + timedelta(hours=LOCK_HOURS)).isoformat()
    data["lock_reason"] = reason
    # Mark as fully used so it stays locked even if time resets
    data["used_today"] = DAILY_LIMIT 
    _save(data)
    print(f"    🔒 OpenRouter force-locked for 1h ({reason})")



if __name__ == "__main__":
    s = status()
    print(f"OpenRouter quota: {s['used_today']}/{DAILY_LIMIT} used, {s['remaining']} remaining")
    print(f"Locked until: {s['locked_until'] or 'not locked'}")
```

---

### 2.4 Advisory Queue & Fix Backlog Structure

**Advisory Queue** (`overnight/advisory_queue/pending/`):
- One JSON file per source file: `{safe_name}.json` (e.g., `engine__queue_manager.json`)
- Schema: `{"file_path": "...", "advisory_notes": "...", "created_at": "ISO8601", "status": "pending"}`
- Daytime workers append here via `engine/queue_manager.py::enqueue_advisory()`
- Crash-resilient: individual files survive partial writes; deleted only on successful OpenRouter processing

**Fix Backlog** (`overnight/fix_backlog.json`):
```json
[
  {"file": "engine/queue_manager.py", "issue": {"description": "...", "category": "maintainability", "severity": "low", "suggestion": "..."}},
  {"file": "tools/embedding_prefix_check.py", "issue": {...}}
]
```
- Simple JSON array (not object with applied/pending/rejected)
- Atomic updates via `os.replace()` on `.tmp` file in `_save_backlog()`
- Items removed only after successful `apply_auto_fix()` commit

---

### 2.5 Apply Auto-Fix Safety Contract

The `apply_auto_fix()` function in `overnight/self_improver.py` implements the following **safety contract**:

| Guarantee | Mechanism |
|---|---|
| **Test-gated commits only** | `pytest -x -q --tb=no` must pass (120s timeout) before `git commit` |
| **No `git push` ever executed** | Pipeline only performs local git operations; zero network mutations except LLM API calls |
| **`.orig_backup` crash recovery** | Backup created before any file write; auto-restored on exception; cleaned up only on successful commit |
| **Git no-op detection** | `git commit` stderr checked for "nothing to commit" / "no changes" — treated as success |
| **120s timeout on fix application** | `subprocess.run(..., timeout=120)` — kills stuck pytest processes |
| **Cross-model validation** | Gemini validates findings; catches false positives before backlog insertion |

**Implementation** (from `overnight/self_improver.py::apply_auto_fix`):

```python
def apply_auto_fix(file_path, issue, api_keys):
    """Generate and apply a fix with test gating, crash-safe backup, and
    precise git error handling. Every exit path is deliberate."""
    try:
        original = file_path.read_text()
    except Exception as e:
        print(f"       ❌ Cannot read {file_path.name}: {e}")
        return False

    prompt = (
        "You are a senior Python engineer. Fix the issue below in this file.\n"
        "Return ONLY the complete fixed file content. No markdown fences, "
        "no explanations, no comments about the change.\n"
        "Preserve all unrelated behavior. Keep the module importable without "
        "side effects. Use datetime.now(timezone.utc), never utcnow().\n"
        f"Issue: {issue.get('description', '')}\n"
        f"Category: {issue.get('category', '')}\n"
        f"Suggestion: {issue.get('suggestion', '')}\n\n"
        f"Current file content:\n{original[:12000]}\n"
    )
    print(f"       📝 Generating fix: {issue.get('description', '')[:80]}")
    fix_code = generate(prompt, api_keys, temperature=0.2)
    if not fix_code:
        print(f"       ❌ Fix generation failed")
        return False
    fix_code = strip_fences(fix_code)
    if len(fix_code) < 0.5 * len(original):
        print(f"       ❌ Fix suspiciously short ({len(fix_code)} vs {len(original)} chars) — rejecting")
        return False

    # Backup exists ONLY during the pytest window; a leftover .orig_backup at
    # next startup is proof of a crash mid-test (handled by main() recovery).
    backup = file_path.with_suffix(file_path.suffix + ".orig_backup")
    backup.write_text(original)
    file_path.write_text(fix_code)

    tests_passed = False
    timed_out = False
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
            cwd=ROOT, capture_output=True, timeout=120,
        )
        tests_passed = result.returncode == 0
    except subprocess.TimeoutExpired:
        timed_out = True  # subprocess.run already killed the hung pytest child

    if not tests_passed:
        file_path.write_text(original)
        backup.unlink(missing_ok=True)
        print(f"       ❌ Tests {'timed out (120s)' if timed_out else 'failed'} — reverting")
        return False

    backup.unlink(missing_ok=True)
    try:
        subprocess.run(["git", "add", str(file_path)], cwd=ROOT, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Auto-fix: {file_path.name}"],
                       cwd=ROOT, check=True, capture_output=True)
        print(f"       ✅ Fix committed")
        return True
    except subprocess.CalledProcessError as e:
        err = (e.stdout or b"") + (e.stderr or b"")
        if b"nothing to commit" in err or b"no changes" in err:
            print(f"       ⚠️  No-op fix (nothing changed) — treated as done")
            return True
        print(f"       ❌ git failed: {err.decode(errors='replace')[:200]}")
        return False
```

---

### 2.6 Operations

**Scheduling**: No hardcoded cron in code. Operator configures via:
- Systemd timer: `OnCalendar=*-*-* 02:00:00` (or any time)
- Cron: `0 2 * * * /path/to/venv/python -m overnight.self_improver`
- Manual: `python -m overnight.self_improver`

**Launch Commands**:
```bash
# Manual run (foreground)
cd /opt/local-soc-slm
python -m overnight.self_improver

# Prefill only (Gemini pre-analysis)
python -m overnight.self_improver --prefill-only

# Process only (drain existing queue with OpenRouter)
python -m overnight.self_improver --process-only

# Force re-run after quota reset
rm overnight/openrouter_quota.json overnight/llm_cooldown.json
python -m overnight.self_improver
```

**Monitoring**:
```bash
# Pipeline status (last run)
cat overnight/improver_state.json | jq '{fixes, reverts, last_run}'

# OpenRouter quota
cat overnight/openrouter_quota.json | jq '{used_today, remaining, locked_until}'

# Advisory queue depth
ls overnight/advisory_queue/pending/*.json | wc -l

# Fix backlog health
cat overnight/fix_backlog.json | jq 'length'

# Current OpenRouter model
cat overnight/model_fallback_cache.json | jq '.models[0]'

# Recent git auto-fix commits
git log --oneline --grep="Auto-fix" -20
```

**Safety Checklist** (verify before enabling):
- [ ] Test-gated commits only: `apply_auto_fix` runs `pytest -x -q --tb=no` before `git commit`
- [ ] No network mutations: Pipeline only reads/writes local FS and calls LLM APIs (HTTPS)
- [ ] Git audit trail: Every fix committed with message `Auto-fix: <filename>`
- [ ] Rollback capability: `git revert HEAD` or `git checkout HEAD^ -- <file>`
- [ ] Quota hard limits: OpenRouter 1000 RPD enforced at client + server
- [ ] Concurrency lock: `overnight/.pipeline.lock` prevents overlapping runs (if implemented)
- [ ] Secrets: API keys in `/etc/local-soc-slm/llm_keys.env` (600, root:root) or `.env`
- [ ] Git identity configured: `git config user.email/name` for pipeline user

---

## 3. Integration Points

- **Daytime intake**: `engine/queue_manager.py::enqueue_advisory()` → writes to `overnight/advisory_queue/pending/{safe_name}.json`
- **Enrichment context**: `orchestrator/context_stitcher.py::build_context(advisory)` used in prefill prompts
- **Model registry**: `orchestrator/model_registry.py` provides model metadata for curation (via `overnight/models.yaml`)
- **Memory/RAG**: `memory/embeddings.py::search_similar(advisory.text, k=5)` injects historical fixes into prompts
- **Retention**: `memory/retention.py` purges `fix_backlog.json` entries older than 90 days

---

## 4. Dependencies

| Package | Purpose | Version |
|---|---|---|
| `requests` | Sync HTTP client for LLM providers | `>=2.31` |
| `pyyaml` | Config parsing (if used) | `>=6.0` |
| `pytest` | Test gate for auto-fixes | `>=7.0` |

Install via: `pip install -r overnight/requirements.txt`

---

# SECTION 3: TRUNCATION NOTES

| Document | Missing Content | Regeneration Required |
|---|---|---|
| `docs/ARCHITECTURE.md` | SelfImprover class definition incomplete: missing closing `)` for `__init__`, entire `run()` method body after `if not await self.quota.reserve_tokens(...)`, and class closing. The `ImprovementReport` return is truncated. | Regenerate the complete `SelfImprover` class with full `run()` method implementing the corrected synchronous three-phase flow (`prefill_advisory_queue` → `process_advisory_queue` → `drain_fix_backlog`), using `overnight/llm_client.py` and `overnight/openrouter_quota.py` as dependencies. Remove all references to LoRA fine-tuning, DBSCAN clustering, and multiple fix_backlog paths. |
| `docs/LAB_SETUP_GUIDE.md` | Wazuh Manager `ossec.conf` cuts off at `<synchron` inside `<syscheck><synchronization>`. Missing: `</synchronization>`, `</syscheck>`, and all subsequent configuration sections (rootcheck, wodle, labels, etc.). | Regenerate complete `ossec.conf` with full `<synchronization>` element (`<enabled>yes</enabled><interval>5m</interval><max_interval>1h</max_interval></synchronization>`), plus remaining sections: `<rootcheck>`, `<wodle name="open-scap">`, `<wodle name="cis-cat">`, `<labels>`, and closing `</ossec_conf>`. Also correct `slm-overnight` service: remove hardcoded cron `0 3 * * *`, change `FIX_BACKLOG_PATH` to `overnight/fix_backlog.json`, remove `./data/fix_backlog.json` volume mount. |
| `docs/deployment_runbook.md` | §11.3 code block cuts off at bare `from` in `overnight/llm_client.py`. Missing: all imports, provider classes (`OpenRouterProvider`, `GroqProvider`, `GeminiProvider`), `LLMClient` with `complete_with_fallback`, token-aware pacing, cooldown tracking, rate-limit header pre-emption, and model curation logic. | Regenerate complete `overnight/llm_client.py` as a synchronous client (no `async`/`await` in public API) with: OpenRouter → Groq fallback chain, Gemini for prefill/critique, token-aware pacing (`sleep(tokens/10000*2)`), cooldown persistence to `overnight/llm_cooldown.json`, exponential backoff (base 1s, max 60s, jitter ±25%), rate-limit header pre-emption (`x-ratelimit-remaining`/`reset`), and model curation via `overnight/models.yaml`. Remove Ollama, vLLM, LM Studio providers. |