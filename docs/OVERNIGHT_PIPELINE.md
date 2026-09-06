# OVERNIGHT PIPELINE — Architecture & Operations Guide (v11.11)

## 1. Overview

The overnight self-improving pipeline runs as a standalone cron job (`0 3 * * *`) on the SOC control plane. It consumes the advisory queue produced by daytime triage, performs multi-model analysis with quota-aware fallbacks, and applies verified fixes through a test-gated commit gate. Zero network mutations occur outside the LLM providers; all code changes are local, git-tracked, and pytest-validated before merge. **No `git push` is ever executed by the pipeline.**

**Entry point**: `overnight/self_improver.py::main()`
**State files**: `overnight/fix_backlog.json`, `overnight/openrouter_quota.json`, `overnight/advisory_queue.jsonl`
**Lock file**: `overnight/.pipeline.lock` (prevents concurrent runs)

---

## 2. Unified Queue (Advisory Generation)rchitecture

### 2.1 Unified Queue (Advisory Generation) — Gemini Pre-fill (`overnight/self_improver.py::phase_a_prefill`)

```python
async def phase_a_prefill(advisories: list[Advisory]) -> list[PrefillResult]:
    client = LLMClient(provider="gemini", model="gemini-1.5-flash")
    results = []
    for adv in advisories:
        prompt = PREFILL_TEMPLATE.render(advisory=adv, context=load_context(adv))
        resp = await client.complete(prompt, max_tokens=2048, temperature=0.1)
        results.append(PrefillResult(advisory_id=adv.id, draft=resp.text, tokens=resp.usage))
    return results
```

- **Purpose**: Generate initial fix drafts for all advisories in a single cheap pass.
- **Model**: `gemini-1.5-flash` (1M token context, $0.075/1M input).
- **Output**: `PrefillResult` objects serialized to `overnight/phase_a_prefill.jsonl`.
- **Failure mode**: If Gemini quota exhausted, skip Unified Queue (Advisory Generation) and proceed to Shadow Canary & Backlog Drain with empty drafts.

### 2.2 Shadow Canary & Backlog Drain — Analysis with Fallback Chain (`overnight/self_improver.py::phase_b_analyze`)

```python
async def phase_b_analyze(prefills: list[PrefillResult]) -> list[AnalysisResult]:
    client = LLMClient()  # full fallback chain: openrouter -> groq -> gemini
    results = []
    for pf in prefills:
        prompt = ANALYSIS_TEMPLATE.render(prefill=pf, backlog=load_backlog())
        resp = await client.complete_with_fallback(
            prompt,
            primary="openrouter/anthropic/claude-3.5-sonnet",
            fallbacks=["groq/llama-3.1-70b-versatile", "gemini/gemini-1.5-pro"],
            max_tokens=4096,
            temperature=0.2,
        )
        results.append(AnalysisResult(
            advisory_id=pf.advisory_id,
            fix_plan=resp.text,
            model_used=resp.model,
            provider=resp.provider,
            tokens=resp.usage,
        ))
    return results
```

- **Fallback chain**: OpenRouter (Claude 3.5 Sonnet) → Groq (Llama 3.1 70B) → Gemini (1.5 Pro).
- **Token-aware pacing**: `LLMClient` tracks per-provider token budgets; pauses 2s per 10k tokens emitted.
- **Cooldown tracking**: 60s cooldown after any 429/503; persisted in `overnight/llm_cooldown.json`.
- **Exponential backoff**: Base 1s, max 60s, jitter ±25%.
- **Rate-limit header pre-emption**: Reads `x-ratelimit-remaining`, `x-ratelimit-reset`; sleeps proactively.
- **Model curation**: Only curated models in `overnight/models.yaml` are eligible; auto-updated weekly via `overnight/update_model_catalog.py`.
- **All-providers-exhausted behavior**: If every provider is in cooldown or returns errors, `complete_with_fallback` raises `AllProvidersExhausted`. The pipeline catches this and exits with code **75 (EX_TEMPFAIL)** so the systemd timer (`overnight-pipeline.timer`) will retry on the next scheduled run.

### 2.3 Phase C — Backlog Drain (`overnight/self_improver.py::phase_c_drain`)

```python
async def phase_c_drain(analyses: list[AnalysisResult]) -> DrainReport:
    applied = []
    failed = []
    for ar in analyses:
        if ar.fix_plan.confidence < 0.85:
            failed.append((ar.advisory_id, "low_confidence"))
            continue
        result = await apply_auto_fix(ar.fix_plan, dry_run=False)
        if result.success:
            applied.append(ar.advisory_id)
            record_fix(ar.advisory_id, ar.fix_plan, result.diff)
        else:
            failed.append((ar.advisory_id, result.error))
            requeue_advisory(ar.advisory_id, reason=result.error)
    return DrainReport(applied=applied, failed=failed, timestamp=utcnow())
```

- **Confidence gate**: Only fixes with `confidence >= 0.85` proceed.
- **Re-queue**: Failed items return to `overnight/advisory_queue.jsonl` with backoff metadata.
- **Idempotency**: `apply_auto_fix` is idempotent; re-running on same advisory produces no-op diff.

---

## 3. LLM Client — Multi-Provider Fallback Chain (`overnight/llm_client.py`)

### 3.1 Provider Abstraction

```python
class LLMProvider(Protocol):
    async def complete(self, prompt: str, **kwargs) -> LLMResponse: ...
    def estimate_tokens(self, text: str) -> int: ...
    def get_rate_limit_headers(self) -> dict[str, str]: ...

class OpenRouterProvider(LLMProvider):
    BASE_URL = "https://openrouter.ai/api/v1"
    MODELS = ["anthropic/claude-3.5-sonnet", "anthropic/claude-3-haiku", "meta-llama/llama-3.1-405b"]

class GroqProvider(LLMProvider):
    BASE_URL = "https://api.groq.com/openai/v1"
    MODELS = ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]

class GeminiProvider(LLMProvider):
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    MODELS = ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.0-pro"]
```

### 3.2 Fallback Logic (`LLMClient.complete_with_fallback`)

```python
async def complete_with_fallback(
    self,
    prompt: str,
    primary: str,
    fallbacks: list[str],
    **kwargs
) -> LLMResponse:
    chain = [primary] + fallbacks
    last_error = None
    for model_spec in chain:
        provider_name, model = model_spec.split("/", 1)
        provider = self._get_provider(provider_name)
        if not provider.is_healthy():
            continue
        if not self._quota_allows(provider_name, model, kwargs.get("max_tokens", 4096)):
            continue
        try:
            resp = await provider.complete(prompt, model=model, **kwargs)
            self._record_success(provider_name, model, resp.usage)
            return resp
        except RateLimitError as e:
            self._record_rate_limit(provider_name, e.retry_after)
            last_error = e
        except ProviderError as e:
            self._record_error(provider_name, e)
            last_error = e
    raise AllProvidersExhausted(last_error)
```

### 3.3 Token-Aware Pacing & Cooldown

- **Token budget**: Per-provider daily token limits in `overnight/token_budgets.yaml`.
- **Pacing**: `await asyncio.sleep(tokens_emitted / 10000 * 2)` after each completion.
- **Cooldown file**: `overnight/llm_cooldown.json` — `{ "openrouter": 1724563200, "groq": 0 }` (unix timestamp until ready).
- **Health check**: `provider.is_healthy()` returns `False` if cooldown active or 3+ consecutive errors.

### 3.4 Rate-Limit Header Pre-emption

```python
def _update_from_headers(self, provider: str, headers: dict):
    remaining = int(headers.get("x-ratelimit-remaining", "1"))
    reset_ts = int(headers.get("x-ratelimit-reset", "0"))
    if remaining <= 2:
        self._cooldowns[provider] = reset_ts + 5  # 5s buffer
        atomic_write_json("overnight/llm_cooldown.json", self._cooldowns)
```

---

## 4. OpenRouter Quota Manager (`overnight/openrouter_quota.py`)

### 4.1 50 RPD Enforcement

```python
class OpenRouterQuota:
    DAILY_LIMIT = 50
    QUOTA_FILE = Path("overnight/openrouter_quota.json")
    LOCK_FILE = Path("overnight/openrouter_quota.lock")

    def __init__(self):
        self._data = self._load()
        self._lock = FileLock(self.LOCK_FILE)  # requires `filelock` PyPI package

    def _load(self) -> dict:
        if self.QUOTA_FILE.exists():
            return json.loads(self.QUOTA_FILE.read_text())
        return {"date": utc_date(), "used": 0, "locked_until": 0}

    def consume(self, n: int = 1) -> bool:
        with self._lock:
            self._maybe_rollover()
            if self._data["locked_until"] > time.time():
                return False
            if self._data["used"] + n > self.DAILY_LIMIT:
                self._data["locked_until"] = next_utc_midnight()  # returns Unix timestamp (float)
                self._save()
                return False
            self._data["used"] += n
            self._save()
            return True

    def _maybe_rollover(self):
        today = utc_date()  # returns "YYYY-MM-DD" string in UTC
        if self._data["date"] != today:
            self._data = {"date": today, "used": 0, "locked_until": 0}
            self._save()
```

### 4.2 Atomic Writes & UTC Rollover

- **Atomic write**: Write to `.tmp`, `os.replace()` over target (POSIX atomic, cross-filesystem safe).
- **UTC rollover**: `utc_date()` returns `YYYY-MM-DD` in UTC; rollover at 00:00 UTC.
- **24h lock**: When limit hit, `locked_until` set to next midnight UTC (Unix timestamp via `next_utc_midnight()`); no requests until rollover.
- **Monitoring**: `cat overnight/openrouter_quota.json | jq '.used + "/" + (.DAILY_LIMIT|tostring)'`

---

## 5. Disk-Backed Advisory Queue & Fix Backlog

### 5.1 Advisory Queue (`overnight/advisory_queue.jsonl`)

```jsonl
{"id": "adv-20241219-001", "type": "false_positive", "rule_id": "wazuh-5710", "context": {...}, "created": "2024-12-19T14:32:11Z", "attempts": 0, "backoff_until": 0}
{"id": "adv-20241219-002", "type": "missing_enrichment", "rule_id": "suricata-2024321", "context": {...}, "created": "2024-12-19T15:01:44Z", "attempts": 1, "backoff_until": 1734633600}
```

- **Append-only**: Daytime workers `engine/queue_manager.py::enqueue_advisory()` append lines.
- **Crash resilience**: JSONL survives partial writes; reader skips malformed lines.
- **Decoupled analysis/fixing**: Unified Queue (Advisory Generation)/B read queue; Phase C drains; no in-memory coupling.

### 5.2 Fix Backlog (`overnight/fix_backlog.json`)

```json
{
  "applied": [
    {"id": "adv-20241218-003", "fix_hash": "a1b2c3d4", "diff": "...", "test_result": "passed", "committed": true, "timestamp": "2024-12-18T03:14:22Z"}
  ],
  "pending": [
    {"id": "adv-20241219-001", "fix_plan": {...}, "confidence": 0.92, "created": "2024-12-19T03:00:11Z"}
  ],
  "rejected": [
    {"id": "adv-20241218-005", "reason": "pytest_failed", "details": "test_sanitization.py::test_ipv6_parse FAILED", "timestamp": "2024-12-18T03:15:01Z"}
  ]
}
```

- **Atomic updates**: `atomic_write_json()` used for all mutations (uses `os.replace()`).
- **Deduplication**: `fix_hash` = SHA256 of unified diff; prevents re-applying identical fixes.
- **Audit trail**: Full history retained for 90 days (configurable via `overnight/retention.yaml`).

---

## 6. Apply Auto-Fix Safety Contract (`overnight/apply_auto_fix.py`)

### 6.1 Contract Guarantees

| Guarantee | Mechanism |
|-----------|-----------|
| **Test-gated commits** | `pytest -x -q --testmon` must pass before `git commit` |
| **Crash recovery** | `.orig_backup` created before any file write; auto-restore on exception |
| **Git no-op detection** | `git diff --exit-code` — if clean, skip commit & tag as `no-op` |
| **120s timeout** | `asyncio.wait_for(apply_fix(), timeout=120)` — kills stuck processes |
| **No network mutations** | Zero outbound calls except LLM providers; all FS ops local; **no `git push`** |
| **Git identity** | Pipeline user must have `git config user.email` and `user.name` set (systemd `Environment=` or `/etc/gitconfig`) |
| **Pre-commit bypass** | `git commit --no-verify` skips hooks that may call network or exceed timeout |

### 6.2 Implementation

```python
async def apply_auto_fix(fix_plan: FixPlan, dry_run: bool = False) -> ApplyResult:
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Repo(".")
        # 1. Create .orig_backup for each target file
        for file_path in fix_plan.target_files:
            shutil.copy2(file_path, f"{file_path}.orig_backup")
        # 2. Apply patches
        for patch in fix_plan.patches:
            apply_patch(patch, repo.working_dir)
        # 3. Run pytest gate (testmon for incremental selection)
        if not dry_run:
            result = await asyncio.wait_for(
                run_pytest(fix_plan.related_tests, use_testmon=True),
                timeout=120
            )
            if result.returncode != 0:
                restore_orig_backups(fix_plan.target_files)
                return ApplyResult(success=False, error=f"pytest_failed: {result.stderr}")
        # 4. Git no-op check
        if not dry_run and repo.git.diff("--exit-code") == 0:
            restore_orig_backups(fix_plan.target_files)
            return ApplyResult(success=True, no_op=True)
        # 5. Commit — ONLY stage files that were actually modified
        if not dry_run:
            repo.git.add(update=True)  # stages only tracked files with changes; ignores untracked
            repo.git.commit("-m", f"auto-fix: {fix_plan.advisory_id}", "--no-verify")
            tag = f"auto-fix/{fix_plan.advisory_id}/{utcnow().strftime('%Y%m%d-%H%M%S')}"
            repo.create_tag(tag)
    return ApplyResult(success=True, diff=repo.git.diff("HEAD~1"))
```

### 6.3 Crash Recovery

- On any exception: `restore_orig_backups()` copies `.orig_backup` → original.
- `.orig_backup` files cleaned up only on successful commit.
- If process killed (SIGKILL), backups remain; next run detects and restores via `overnight/recover_backups.py`.

---

## 7. Cross-Model Validation (Gemini Critique)

### 7.1 Critique Loop

```python
async def cross_model_validate(fix_plan: FixPlan, primary_resp: LLMResponse) -> ValidationResult:
    critic = LLMClient(provider="gemini", model="gemini-1.5-pro")
    prompt = CRITIQUE_TEMPLATE.render(
        fix_plan=fix_plan,
        primary_analysis=primary_resp.text,
        primary_model=primary_resp.model,
    )
    critique = await critic.complete(prompt, max_tokens=2048, temperature=0.0)
    return parse_critique(critique.text)
```

### 7.2 Hallucination Detection

Critique prompt explicitly asks:
1. Does the fix address the root cause or only symptoms?
2. Are there any invented APIs, functions, or imports not in the codebase?
3. Does the diff introduce regressions in related modules?
4. Confidence score (0.0–1.0) for the fix as written.

**Threshold**: Fix proceeds only if `critique.confidence >= 0.8` AND no hallucination flags raised.

### 7.3 Example Critique Output

```json
{
  "confidence": 0.87,
  "hallucinations": [],
  "regressions": ["engine/sanitization_pipeline.py:142 — removes IPv6 normalization added in v11.3"],
  "suggestions": ["Preserve normalize_ipv6() call; only adjust regex for CIDR parsing"],
  "verdict": "conditional_approve"
}
```

---

## 8. Operations Runbook

### 8.1 Launch Commands

```bash
# Manual run (foreground, verbose)
cd /opt/soc-autopilot
python -m overnight.self_improver --verbose --dry-run

# Production run (via systemd timer)
systemctl start overnight-pipeline.service
systemctl status overnight-pipeline.timer

# Force re-run after quota reset
rm overnight/openrouter_quota.json overnight/llm_cooldown.json
python -m overnight.self_improver
```

### 8.2 Monitoring One-Liners

```bash
# Pipeline status (last run)
jq -r '.timestamp, .applied|length, .failed|length' overnight/phase_c_drain_report.json

# OpenRouter quota
watch -n 60 'cat overnight/openrouter_quota.json | jq "{used, limit: 50, locked: .locked_until > now}"'

# LLM cooldowns
cat overnight/llm_cooldown.json | jq 'to_entries[] | select(.value > now)'

# Advisory queue depth
wc -l overnight/advisory_queue.jsonl

# Fix backlog health
jq '{applied: .applied|length, pending: .pending|length, rejected: .rejected|length}' overnight/fix_backlog.json

# Recent git auto-fix tags
git tag -l "auto-fix/*" --sort=-creatordate | head -20
```

### 8.3 Budget Checks

```bash
# Estimated monthly cost (based on last 30 days)
python -m overnight.cost_report --days 30
# Output:
# Provider       Requests   Input Tokens   Output Tokens   Est. Cost
# openrouter     1,240      45.2M          12.8M           $23.40
# groq           3,100      89.1M          34.5M           $0.00 (free tier)
# gemini         890        22.4M          8.1M            $2.15
# TOTAL                                                    $25.55
```

### 8.4 Safety Guarantees Checklist

- [ ] **Test-gated commits only**: `apply_auto_fix` runs `pytest -x -q --testmon` before any `git commit`.
- [ ] **No network mutations**: Pipeline only reads/writes local FS and calls LLM APIs (HTTPS, read-only prompts). **Git operations are strictly local; no `git push` is performed.**
- [ ] **Git audit trail**: Every fix tagged `auto-fix/<advisory_id>/<timestamp>`; `git log --oneline --grep=auto-fix` shows full history.
- [ ] **Rollback capability**: `git revert <tag>` or `git checkout <tag>^ -- <file>` restores pre-fix state.
- [ ] **Quota hard limits**: OpenRouter 50 RPD enforced at client + server; Gemini/Groq free tiers monitored.
- [ ] **Concurrency lock**: `overnight/.pipeline.lock` prevents overlapping runs (cron + manual).
- [ ] **Secrets**: API keys in `/etc/soc-autopilot/llm_keys.env` (600, root:root); never in repo.
- [ ] **Git identity configured**: `git config --global user.email "pipeline@local-soc-slm" && git config --global user.name "Overnight Pipeline"` (or via systemd `Environment=`).
- [ ] **Pre-commit hooks bypassed**: `git commit --no-verify` prevents external network calls or slow linters from breaking the 120s timeout.

---

## 9. Troubleshooting

| Symptom | Diagnosis | Resolution |
|---------|-----------|------------|
| Pipeline stuck at Shadow Canary & Backlog Drain | All providers in cooldown | `cat overnight/llm_cooldown.json`; wait or manually clear |
| OpenRouter 429 despite quota | Header pre-emption missed | Check `x-ratelimit-reset` in logs; increase buffer |
| `apply_auto_fix` timeout | Test suite hangs | Add `--timeout=60` to pytest; investigate flaky test; ensure `--testmon` is used |
| Fix rejected: `pytest_failed` | Fix breaks existing tests | Review `fix_backlog.json` rejected entry; adjust fix plan |
| Advisory re-queued repeatedly | Confidence < 0.85 or critique veto | Inspect Shadow Canary & Backlog Drain analysis + critique; may need manual triage |
| Pipeline exits with code 75 | All LLM providers exhausted (cooldown/error) | Systemd timer will retry automatically; check `llm_cooldown.json` |
| `git commit` fails with "author identity unknown" | Git user not configured for pipeline user | Set `git config user.email/name` in systemd unit or `/etc/gitconfig` |

---

## 10. File Reference

| Path | Purpose |
|------|---------|
| `overnight/self_improver.py` | Main pipeline orchestrator (Phases A/B/C) |
| `overnight/llm_client.py` | Multi-provider client, fallback, pacing, cooldown |
| `overnight/openrouter_quota.py` | 50 RPD quota manager with atomic writes |
| `overnight/apply_auto_fix.py` | Safety-contract fix application |
| `overnight/cross_validate.py` | Gemini critique loop |
| `overnight/models.yaml` | Curated model catalog (auto-updated) |
| `overnight/token_budgets.yaml` | Per-provider daily token limits |
| `overnight/advisory_queue.jsonl` | Disk-backed advisory queue (append-only) |
| `overnight/fix_backlog.json` | Applied/pending/rejected fix history |
| `overnight/openrouter_quota.json` | OpenRouter daily usage + lock state |
| `overnight/llm_cooldown.json` | Per-provider cooldown timestamps |
| `overnight/phase_a_prefill.jsonl` | Unified Queue (Advisory Generation) intermediate output |
| `overnight/phase_c_drain_report.json` | Phase C summary (applied/failed) |
| `overnight/recover_backups.py` | Crash recovery for `.orig_backup` files |
| `overnight/update_model_catalog.py` | Weekly model catalog refresh |
| `overnight/cost_report.py` | Budget estimation from usage logs |

---

## 11. Dependencies

| Package | Purpose | Version Constraint |
|---------|---------|-------------------|
| `filelock` | Cross-process file locking for quota/cooldown files | `>=3.12` |
| `gitpython` | Git operations (commit, tag, diff) | `>=3.1.40` |
| `httpx` | Async HTTP client for LLM providers | `>=0.27` |
| `pyyaml` | Config parsing (models.yaml, token_budgets.yaml) | `>=6.0` |
| `tenacity` | Retry/backoff logic (optional, used in providers) | `>=8.2` |
| `pytest-testmon` | Incremental test selection for fast pytest gate | `>=1.4` |

Install via: `pip install -r overnight/requirements.txt`

---

## 12. Integration Points

- **Daytime intake**: `engine/queue_manager.py::enqueue_advisory()` → `overnight/advisory_queue.jsonl`
- **Enrichment context**: `orchestrator/context_stitcher.py::build_context(advisory)` used in Unified Queue (Advisory Generation)/B prompts
- **Model registry**: `orchestrator/model_registry.py` provides model metadata for curation
- **Memory/RAG**: `memory/embeddings.py::search_similar(advisory.text, k=5)` injects historical fixes into prompts
- **Retention**: `memory/retention.py` purges `fix_backlog.json` entries older than 90 days

---

## 13. Atomic Write Utility (`overnight/utils/atomic_write.py`)

```python
import os
import json
from pathlib import Path

def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically using os.replace (POSIX atomic, cross-filesystem safe)."""
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    os.replace(tmp_path, path)  # atomic on POSIX; replaces target even across filesystems
```

Used by: `openrouter_quota.py`, `llm_client.py` (cooldown), `fix_backlog.json` mutations.

---


---

## 14. Overnight Run Wrapper & Recent Hardening (v11.10)

### 14.1 Launching an Overnight Run

Use the wrapper script for a budget-gated, self-reporting run:

    cd /home/swiig/Documents/soc-autopilot
    nohup bash overnight/overnight_run.sh > overnight/overnight_console.log 2>&1 &
    echo "Launched PID $!"

The wrapper:
1. Checks daily budget for Gemini + OpenRouter (stops if either < 60 calls remaining)
2. Invokes `--drain-backlog` once (internal loop handles all passes until backlog empty or budget exhausted)
3. Writes `overnight/morning_report.md` with commits, backlog delta, deferred count, and errors

In the morning: `cat overnight/morning_report.md`

### 14.2 Safety Hardening (added 2026-08-25)

| Defense | Location | What it catches |
|---|---|---|
| ast.parse gate | apply_auto_fix | Non-Python output (CoT prose, markdown) rejected before disk write |
| CoT detector | _looks_like_reasoning | Models returning "let me think..." prose instead of code |
| pytest gate | apply_auto_fix | Fixes that break tests are reverted |
| Truncation guard | apply_auto_fix | Rewrites suspiciously shorter than original (would delete code) |

Result: zero corrupted files across 90+ auto-fix commits.

### 14.3 Efficiency Improvements

- Large-prompt filter (llm_client.py): prompts >25k chars routed only to high-capacity models (ultra, 550b, super-120b, compound). Small models truncate mid-string on large files.
- Groq budget tracking: Groq calls now recorded via APIBudgetManager().record_call("groq").
- Anti-CoT prompts: system prompts forbid reasoning prose; first non-empty line must be valid Python.

### 14.4 Interpreting the Morning Report

- Auto-fix commits (12h): fixes that landed. Expect 20-90 per full drain.
- Backlog start -> end: should reach 0 if budget allowed.
- Deferred queue: items that failed 3x, quarantined for manual triage.
- Errors section: every rejected fix is a safety gate working, not a failure.

### 14.5 Known Limitations

- Deferred accumulation: hard architectural issues accumulate. Plan periodic manual triage.
- Large-file truncation: files >800 lines may fail if no high-capacity model available.
- Groq fallback: only used when OpenRouter saturated; context limits may truncate large prompts.

---

*Document version: v11.10 — Updated 2026-08-25 with overnight wrapper and safety hardening*

## Telemetry & Observability
The pipeline now records empirical efficacy data (first-pass success, repair-salvage rate, pytest failures) to `/mnt/backup-nas/soc-slm-telemetry/`. 
- **Fail-Open:** Telemetry failures never block remediation.
- **Root Disk Protection:** Local buffer is hard-capped at 50MB. Oldest data is dropped if NAS is unavailable for extended periods.
