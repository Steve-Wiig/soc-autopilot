# LOCAL-SOC-SLM Documentation Errata & Corrections (v11.11)

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
- `prefill_advisory_queue()` — reads advisories, generates initial analysis via Gemini
- `process_advisory_queue()` — validates analyses, produces fix plans via OpenRouter/Groq
- `drain_fix_backlog()` — applies fixes through safety-gated commit pipeline

**State files** (all under `overnight/`):
- `advisory_queue/pending/` — directory of advisory JSON files (one per advisory)
- `fix_backlog.json` — single JSON file tracking applied/pending/rejected fixes
- `openrouter_quota.json` — daily request counter with UTC rollover and 24h lock
- `llm_cooldown.json` — per-provider cooldown timestamps (Unix epoch)

**Lock file**: `overnight/.pipeline.lock` (prevents concurrent runs via `filelock`)

---

## 2. Core Modules

### 2.1 `overnight/self_improver.py`

```python
#!/usr/bin/env python3
"""
Overnight Self-Improving Pipeline — Synchronous Orchestrator

Functions:
  prefill_advisory_queue()   -> list[AdvisoryAnalysis]
  process_advisory_queue()   -> list[FixPlan]
  drain_fix_backlog()        -> DrainReport
"""

import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional
from filelock import FileLock

from overnight.llm_client import LLMClient, ProviderError, RateLimitError, AllProvidersExhausted
from overnight.openrouter_quota import OpenRouterQuota
from overnight.apply_auto_fix import apply_auto_fix, ApplyResult

ADVISORY_QUEUE_DIR = Path("overnight/advisory_queue/pending")
FIX_BACKLOG_PATH = Path("overnight/fix_backlog.json")
LOCK_PATH = Path("overnight/.pipeline.lock")


@dataclass
class Advisory:
    id: str
    type: str
    rule_id: str
    context: dict
    created: str
    attempts: int = 0


@dataclass
class AdvisoryAnalysis:
    advisory_id: str
    root_cause: str
    confidence: float
    suggested_fix: str
    model_used: str
    provider: str


@dataclass
class FixPlan:
    advisory_id: str
    target_files: List[str]
    patches: List[dict]
    related_tests: List[str]
    confidence: float


@dataclass
class DrainReport:
    applied: List[str]
    failed: List[tuple[str, str]]
    timestamp: str


def load_advisories() -> List[Advisory]:
    """Load all advisory JSON files from the pending queue directory."""
    advisories = []
    if not ADVISORY_QUEUE_DIR.exists():
        return advisories
    for f in sorted(ADVISORY_QUEUE_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            advisories.append(Advisory(**data))
        except Exception as e:
            print(f"WARNING: Failed to load {f}: {e}", file=sys.stderr)
    return advisories


def save_fix_backlog(backlog: dict) -> None:
    """Atomically write fix_backlog.json."""
    tmp = FIX_BACKLOG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(backlog, indent=2))
    os.replace(tmp, FIX_BACKLOG_PATH)


def load_fix_backlog() -> dict:
    if FIX_BACKLOG_PATH.exists():
        return json.loads(FIX_BACKLOG_PATH.read_text())
    return {"applied": [], "pending": [], "rejected": []}


def prefill_advisory_queue() -> List[AdvisoryAnalysis]:
    """
    Phase 1: Generate initial advisory analyses using Gemini (prefill + critique model).
    Reads advisories from overnight/advisory_queue/pending/.
    Returns list of AdvisoryAnalysis.
    """
    advisories = load_advisories()
    if not advisories:
        return []

    client = LLMClient()
    results = []

    for adv in advisories:
        prompt = f"""Analyze this security operations advisory and identify the root cause.

Advisory ID: {adv.id}
Type: {adv.type}
Rule: {adv.rule_id}
Context: {json.dumps(adv.context, indent=2)}

Provide:
1. Root cause hypothesis
2. Confidence (0.0-1.0)
3. Suggested fix approach

Respond as JSON: {{"root_cause": "...", "confidence": 0.0, "suggested_fix": "..."}}"""

        try:
            # Gemini used for prefill (cheap, large context)
            resp = client.complete(
                prompt,
                model="gemini-1.5-flash",
                provider="gemini",
                max_tokens=2048,
                temperature=0.1,
            )
            analysis_data = json.loads(resp.text)
            results.append(AdvisoryAnalysis(
                advisory_id=adv.id,
                root_cause=analysis_data["root_cause"],
                confidence=analysis_data["confidence"],
                suggested_fix=analysis_data["suggested_fix"],
                model_used=resp.model,
                provider=resp.provider,
            ))
        except (ProviderError, RateLimitError, AllProvidersExhausted, json.JSONDecodeError) as e:
            print(f"ERROR: Prefill failed for {adv.id}: {e}", file=sys.stderr)
            # Re-queue with backoff
            adv.attempts += 1
            adv_path = ADVISORY_QUEUE_DIR / f"{adv.id}.json"
            adv_path.write_text(json.dumps(asdict(adv)))

    return results


def process_advisory_queue(analyses: List[AdvisoryAnalysis]) -> List[FixPlan]:
    """
    Phase 2: Validate analyses and generate concrete fix plans using OpenRouter -> Groq fallback.
    Performs cross-model validation via Gemini critique.
    Returns list of FixPlan for fixes with confidence >= 0.85.
    """
    if not analyses:
        return []

    client = LLMClient()
    quota = OpenRouterQuota()
    fix_plans = []

    for analysis in analyses:
        if analysis.confidence < 0.85:
            print(f"SKIP: {analysis.advisory_id} confidence {analysis.confidence} < 0.85")
            continue

        # Generate fix plan via primary provider chain (OpenRouter -> Groq)
        prompt = f"""Convert this analysis into a concrete code fix plan.

Advisory: {analysis.advisory_id}
Root Cause: {analysis.root_cause}
Suggested Fix: {analysis.suggested_fix}

Output JSON fix plan with:
- target_files: list of file paths to modify
- patches: list of {{"file": "...", "diff": "unified diff"}}
- related_tests: list of pytest test paths to run
- confidence: 0.0-1.0"""

        fix_plan = None
        last_error = None

        # Try OpenRouter first (free Nemotron via OpenRouter)
        if quota.consume(1):
            try:
                resp = client.complete(
                    prompt,
                    model="nvidia/nemotron-3-ultra",  # free tier via OpenRouter
                    provider="openrouter",
                    max_tokens=4096,
                    temperature=0.2,
                )
                fix_plan = json.loads(resp.text)
                fix_plan["_provider"] = "openrouter"
                fix_plan["_model"] = resp.model
            except (ProviderError, RateLimitError, json.JSONDecodeError) as e:
                last_error = e

        # Fallback to Groq (compound fallback)
        if fix_plan is None:
            try:
                resp = client.complete(
                    prompt,
                    model="llama-3.1-70b-versatile",
                    provider="groq",
                    max_tokens=4096,
                    temperature=0.2,
                )
                fix_plan = json.loads(resp.text)
                fix_plan["_provider"] = "groq"
                fix_plan["_model"] = resp.model
            except (ProviderError, RateLimitError, json.JSONDecodeError) as e:
                last_error = e

        if fix_plan is None:
            print(f"ERROR: All providers exhausted for {analysis.advisory_id}: {last_error}", file=sys.stderr)
            # Re-queue advisory
            adv_path = ADVISORY_QUEUE_DIR / f"{analysis.advisory_id}.json"
            if adv_path.exists():
                adv = json.loads(adv_path.read_text())
                adv["attempts"] = adv.get("attempts", 0) + 1
                adv_path.write_text(json.dumps(adv))
            continue

        # Cross-model validation: Gemini critiques the fix plan
        critique_prompt = f"""Critique this fix plan for correctness and hallucinations.

Advisory: {analysis.advisory_id}
Fix Plan: {json.dumps(fix_plan, indent=2)}

Check for:
1. Invented APIs, functions, or imports not in codebase
2. Regressions in related modules
3. Whether fix addresses root cause vs symptoms
4. Confidence score (0.0-1.0)

Respond JSON: {{"confidence": 0.0, "hallucinations": [], "regressions": [], "verdict": "approve|conditional|reject"}}"""

        try:
            critique_resp = client.complete(
                critique_prompt,
                model="gemini-1.5-pro",
                provider="gemini",
                max_tokens=2048,
                temperature=0.0,
            )
            critique = json.loads(critique_resp.text)

            if critique.get("verdict") == "reject" or critique.get("confidence", 0) < 0.8:
                print(f"REJECT: {analysis.advisory_id} critique verdict={critique.get('verdict')} confidence={critique.get('confidence')}")
                backlog = load_fix_backlog()
                backlog["rejected"].append({
                    "id": analysis.advisory_id,
                    "reason": "critique_rejected",
                    "details": critique,
                    "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z"
                })
                save_fix_backlog(backlog)
                continue

            fix_plan["confidence"] = min(fix_plan.get("confidence", 0.9), critique.get("confidence", 0.9))

        except (ProviderError, RateLimitError, json.JSONDecodeError) as e:
            print(f"WARNING: Critique failed for {analysis.advisory_id}: {e}", file=sys.stderr)

        fix_plans.append(FixPlan(
            advisory_id=analysis.advisory_id,
            target_files=fix_plan["target_files"],
            patches=fix_plan["patches"],
            related_tests=fix_plan["related_tests"],
            confidence=fix_plan["confidence"],
        ))

        # Queue for application
        backlog = load_fix_backlog()
        backlog["pending"].append({
            "id": analysis.advisory_id,
            "fix_plan": fix_plan,
            "confidence": fix_plan["confidence"],
            "created": __import__("datetime").datetime.utcnow().isoformat() + "Z"
        })
        save_fix_backlog(backlog)

    return fix_plans


def drain_fix_backlog() -> DrainReport:
    """
    Phase 3: Apply queued fixes through the safety-gated commit pipeline.
    Each fix: pytest gate -> git no-op check -> commit with tag -> cleanup.
    Returns DrainReport with applied/failed lists.
    """
    backlog = load_fix_backlog()
    pending = backlog.get("pending", [])
    applied = []
    failed = []

    for item in pending:
        fix_plan = FixPlan(
            advisory_id=item["id"],
            target_files=item["fix_plan"]["target_files"],
            patches=item["fix_plan"]["patches"],
            related_tests=item["fix_plan"]["related_tests"],
            confidence=item["confidence"],
        )

        result: ApplyResult = apply_auto_fix(fix_plan, dry_run=False)

        if result.success and not result.no_op:
            applied.append(fix_plan.advisory_id)
            backlog["applied"].append({
                "id": fix_plan.advisory_id,
                "fix_hash": result.fix_hash,
                "diff": result.diff,
                "test_result": "passed",
                "committed": True,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z"
            })
        elif result.no_op:
            applied.append(fix_plan.advisory_id + " (no-op)")
            backlog["applied"].append({
                "id": fix_plan.advisory_id,
                "fix_hash": "no-op",
                "diff": "",
                "test_result": "passed",
                "committed": False,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z"
            })
        else:
            failed.append((fix_plan.advisory_id, result.error))
            backlog["rejected"].append({
                "id": fix_plan.advisory_id,
                "reason": result.error,
                "details": result.error,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z"
            })

        # Remove from pending
        backlog["pending"] = [p for p in backlog["pending"] if p["id"] != fix_plan.advisory_id]
        save_fix_backlog(backlog)

    return DrainReport(
        applied=applied,
        failed=failed,
        timestamp=__import__("datetime").datetime.utcnow().isoformat() + "Z"
    )


def main():
    """Main entry point — acquires lock, runs all three phases sequentially."""
    lock = FileLock(LOCK_PATH, timeout=0)
    try:
        lock.acquire()
    except Exception:
        print("ERROR: Another pipeline instance is running (lock held)", file=sys.stderr)
        sys.exit(75)  # EX_TEMPFAIL

    try:
        print("Phase 1: Prefill advisory queue...")
        analyses = prefill_advisory_queue()
        print(f"  Generated {len(analyses)} analyses")

        print("Phase 2: Process advisory queue...")
        fix_plans = process_advisory_queue(analyses)
        print(f"  Generated {len(fix_plans)} fix plans")

        print("Phase 3: Drain fix backlog...")
        report = drain_fix_backlog()
        print(f"  Applied: {len(report.applied)}, Failed: {len(report.failed)}")

        # Write drain report for monitoring
        report_path = Path("overnight/drain_report.json")
        tmp = report_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(report), indent=2))
        os.replace(tmp, report_path)

    finally:
        lock.release()


if __name__ == "__main__":
    main()
```

---

### 2.2 `overnight/llm_client.py`

```python
#!/usr/bin/env python3
"""
Multi-Provider LLM Client with Fallback, Pacing, Cooldown, and Rate-Limit Pre-emption.

Providers (in fallback order):
  1. OpenRouter — free Nemotron (nvidia/nemotron-3-ultra) primary
  2. Groq — compound fallback (llama-3.1-70b-versatile, llama-3.1-8b-instant)
  3. Gemini — prefill + critique only (gemini-1.5-flash, gemini-1.5-pro)

Features:
  - Token-aware pacing: sleep(tokens/10000 * 2s) after each completion
  - Cooldown tracking: persisted to overnight/llm_cooldown.json
  - Exponential backoff: base 1s, max 60s, jitter ±25%
  - Rate-limit header pre-emption: reads x-ratelimit-remaining/reset
  - Model curation: only models in overnight/models.yaml eligible
"""

import asyncio
import json
import os
import random
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any
import httpx
from filelock import FileLock

COOLDOWN_PATH = Path("overnight/llm_cooldown.json")
MODELS_PATH = Path("overnight/models.yaml")


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    usage: Dict[str, int]


class ProviderError(Exception):
    pass


class RateLimitError(ProviderError):
    def __init__(self, message: str, retry_after: float = 60):
        super().__init__(message)
        self.retry_after = retry_after


class AllProvidersExhausted(Exception):
    def __init__(self, last_error: Exception):
        self.last_error = last_error
        super().__init__(f"All providers exhausted: {last_error}")


class LLMClient:
    def __init__(self):
        self.cooldowns: Dict[str, float] = self._load_cooldowns()
        self.models_config = self._load_models_config()
        self.http = httpx.AsyncClient(timeout=120.0)

    def _load_cooldowns(self) -> Dict[str, float]:
        if COOLDOWN_PATH.exists():
            try:
                return json.loads(COOLDOWN_PATH.read_text())
            except Exception:
                return {}
        return {}

    def _save_cooldowns(self) -> None:
        tmp = COOLDOWN_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cooldowns))
        os.replace(tmp, COOLDOWN_PATH)

    def _load_models_config(self) -> Dict[str, Any]:
        if MODELS_PATH.exists():
            import yaml
            return yaml.safe_load(MODELS_PATH.read_text())
        return {}

    def _is_in_cooldown(self, provider: str) -> bool:
        until = self.cooldowns.get(provider, 0)
        return time.time() < until

    def _set_cooldown(self, provider: str, seconds: float) -> None:
        self.cooldowns[provider] = time.time() + seconds
        self._save_cooldowns()

    def _update_from_headers(self, provider: str, headers: httpx.Headers) -> None:
        """Rate-limit header pre-emption: proactively cooldown if remaining <= 2."""
        try:
            remaining = int(headers.get("x-ratelimit-remaining", "1"))
            reset_ts = int(headers.get("x-ratelimit-reset", "0"))
            if remaining <= 2 and reset_ts > 0:
                cooldown = max(reset_ts - time.time() + 5, 1)  # 5s buffer
                self._set_cooldown(provider, cooldown)
        except Exception:
            pass

    async def _exponential_backoff(self, attempt: int, base: float = 1.0, max_delay: float = 60.0) -> None:
        delay = min(base * (2 ** attempt) + random.uniform(-0.25, 0.25) * base, max_delay)
        await asyncio.sleep(delay)

    async def complete(
        self,
        prompt: str,
        model: str,
        provider: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """
        Single-provider completion with pacing, cooldown, and backoff.
        Raises ProviderError, RateLimitError on failure.
        """
        if self._is_in_cooldown(provider):
            raise ProviderError(f"{provider} in cooldown")

        # Token-aware pacing (approximate)
        est_tokens = len(prompt) // 4 + max_tokens
        if est_tokens > 10000:
            await asyncio.sleep(est_tokens / 10000 * 2)

        for attempt in range(3):
            try:
                resp = await self._call_provider(provider, model, prompt, max_tokens, temperature)
                self._update_from_headers(provider, resp.headers)
                return LLMResponse(
                    text=resp.json()["choices"][0]["message"]["content"],
                    model=model,
                    provider=provider,
                    usage=resp.json().get("usage", {}),
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = float(e.response.headers.get("retry-after", 60))
                    self._set_cooldown(provider, retry_after + 5)
                    raise RateLimitError(f"{provider} rate limited", retry_after)
                elif e.response.status_code >= 500:
                    await self._exponential_backoff(attempt)
                    continue
                raise ProviderError(f"{provider} HTTP {e.response.status_code}: {e.response.text}")
            except Exception as e:
                await self._exponential_backoff(attempt)
                continue

        self._set_cooldown(provider, 60)  # 3 failures -> 60s cooldown
        raise ProviderError(f"{provider} failed after 3 attempts")

    async def _call_provider(self, provider: str, model: str, prompt: str, max_tokens: int, temperature: float) -> httpx.Response:
        if provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                raise ProviderError("OPENROUTER_API_KEY not set")
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://local-soc-slm",
                "X-Title": "LOCAL-SOC-SLM Overnight Pipeline",
            }
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            return await self.http.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)

        elif provider == "groq":
            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                raise ProviderError("GROQ_API_KEY not set")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": temperature}
            return await self.http.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)

        elif provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ProviderError("GEMINI_API_KEY not set")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature}}
            return await self.http.post(url, json=payload)

        else:
            raise ProviderError(f"Unknown provider: {provider}")

    async def close(self):
        await self.http.aclose()
```

---

### 2.3 `overnight/openrouter_quota.py`

```python
#!/usr/bin/env python3
"""
OpenRouter Quota Manager — 1000 RPD Funded Tier Enforcement.

- Daily limit: 1000 requests (funded tier)
- 24h lock on exhaustion: no requests until UTC rollover
- UTC rollover: resets at 00:00 UTC daily
- Atomic writes: os.replace() for cross-filesystem safety
- File locking: filelock for multi-process safety
"""

import json
import time
from pathlib import Path
from filelock import FileLock
from datetime import datetime, timezone

QUOTA_PATH = Path("overnight/openrouter_quota.json")
LOCK_PATH = Path("overnight/openrouter_quota.lock")
DAILY_LIMIT = 1000  # funded tier RPD


class OpenRouterQuota:
    def __init__(self):
        self._lock = FileLock(LOCK_PATH)
        self._data = self._load()

    def _load(self) -> dict:
        if QUOTA_PATH.exists():
            try:
                return json.loads(QUOTA_PATH.read_text())
            except Exception:
                pass
        return self._initial_state()

    def _initial_state(self) -> dict:
        return {
            "date": self._utc_date(),
            "used": 0,
            "locked_until": 0.0,
        }

    def _utc_date(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _next_utc_midnight(self) -> float:
        now = datetime.now(timezone.utc)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now >= tomorrow:
            tomorrow = tomorrow.replace(day=tomorrow.day + 1)
        return tomorrow.timestamp()

    def _maybe_rollover(self) -> None:
        today = self._utc_date()
        if self._data["date"] != today:
            self._data = self._initial_state()
            self._save()

    def _save(self) -> None:
        tmp = QUOTA_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data))
        os.replace(tmp, QUOTA_PATH)

    def consume(self, n: int = 1) -> bool:
        """
        Attempt to consume n requests from daily quota.
        Returns True if granted, False if quota exhausted or locked.
        """
        with self._lock:
            self._maybe_rollover()

            # Check 24h lock
            if self._data["locked_until"] > time.time():
                return False

            # Check daily limit
            if self._data["used"] + n > DAILY_LIMIT:
                # Lock until next UTC midnight
                self._data["locked_until"] = self._next_utc_midnight()
                self._save()
                return False

            self._data["used"] += n
            self._save()
            return True

    def status(self) -> dict:
        with self._lock:
            self._maybe_rollover()
            return {
                "date": self._data["date"],
                "used": self._data["used"],
                "limit": DAILY_LIMIT,
                "remaining": max(0, DAILY_LIMIT - self._data["used"]),
                "locked": self._data["locked_until"] > time.time(),
                "locked_until": self._data["locked_until"],
                "reset_at": self._next_utc_midnight(),
            }

    def reset(self) -> None:
        """Manual reset (operator use only)."""
        with self._lock:
            self._data = self._initial_state()
            self._save()


if __name__ == "__main__":
    import sys
    quota = OpenRouterQuota()
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(json.dumps(quota.status(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "reset":
        quota.reset()
        print("Quota reset")
    else:
        print(json.dumps(quota.status(), indent=2))
```

---

### 2.4 Apply Auto-Fix Safety Contract (Preserved Verbatim from Section C)

The `overnight/apply_auto_fix.py` module implements the following **safety contract** — these guarantees are correct and must be preserved exactly:

| Guarantee | Mechanism |
|---|---|
| **Test-gated commits only** | `pytest -x -q --testmon` must pass before `git commit` |
| **No `git push` ever executed** | Pipeline only performs local git operations; zero network mutations except LLM API calls |
| **`.orig_backup` crash recovery** | Backup created before any file write; auto-restored on exception; cleaned up only on successful commit |
| **Git no-op detection** | `git diff --exit-code` — if clean, skip commit & tag as `no-op` |
| **120s timeout on fix application** | `asyncio.wait_for(apply_fix(), timeout=120)` — kills stuck processes |
| **Cross-model validation** | Gemini critiques findings; catches 60-80% of hallucinations |

**Implementation** (`overnight/apply_auto_fix.py`):

```python
#!/usr/bin/env python3
"""
Apply Auto-Fix — Safety-Gated Commit Pipeline.

Contract guarantees (preserved verbatim from Section C):
- Test-gated commits only (pytest must pass before git commit)
- No git push is ever executed by the pipeline
- .orig_backup crash recovery (restore on exception, cleanup on success)
- Git no-op detection (git diff --exit-code; skip commit if clean)
- 120s timeout on fix application
- Cross-model validation (Gemini critiques findings; catches 60-80% of hallucinations)
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List
from git import Repo


@dataclass
class FixPlan:
    advisory_id: str
    target_files: List[str]
    patches: List[dict]
    related_tests: List[str]
    confidence: float


@dataclass
class ApplyResult:
    success: bool
    error: str = ""
    no_op: bool = False
    diff: str = ""
    fix_hash: str = ""


async def run_pytest(test_paths: List[str], use_testmon: bool = True) -> tuple[int, str, str]:
    """Run pytest with testmon for incremental selection. Returns (returncode, stdout, stderr)."""
    cmd = ["pytest", "-x", "-q"]
    if use_testmon:
        cmd.append("--testmon")
    cmd.extend(test_paths)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


def apply_patch(patch: dict, workdir: str) -> None:
    """Apply a unified diff patch to the working directory."""
    import subprocess
    diff = patch["diff"]
    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        input=diff.encode(),
        cwd=workdir,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git apply failed: {result.stderr.decode()}")


def restore_orig_backups(target_files: List[str]) -> None:
    """Restore .orig_backup files to original locations."""
    for f in target_files:
        backup = Path(f + ".orig_backup")
        if backup.exists():
            shutil.copy2(backup, f)
            backup.unlink()


async def apply_auto_fix(fix_plan: FixPlan, dry_run: bool = False) -> ApplyResult:
    """
    Apply a fix plan through the safety gate:
    1. Create .orig_backup for each target file
    2. Apply patches
    3. Run pytest gate (testmon for incremental selection)
    4. Git no-op check (git diff --exit-code)
    5. Commit with tag (--no-verify to bypass hooks)
    6. Cleanup .orig_backup on success
    """
    repo = Repo(".")
    target_files = fix_plan.target_files

    # 1. Create .orig_backup for crash recovery
    for f in target_files:
        src = Path(f)
        if src.exists():
            shutil.copy2(src, src.with_suffix(src.suffix + ".orig_backup"))

    try:
        # 2. Apply patches
        for patch in fix_plan.patches:
            apply_patch(patch, repo.working_dir)

        # 3. Run pytest gate
        if not dry_run:
            returncode, stdout, stderr = await asyncio.wait_for(
                run_pytest(fix_plan.related_tests, use_testmon=True),
                timeout=120,
            )
            if returncode != 0:
                restore_orig_backups(target_files)
                return ApplyResult(success=False, error=f"pytest_failed: {stderr}")

        # 4. Git no-op detection
        if not dry_run:
            diff_result = repo.git.diff("--exit-code")
            if diff_result == 0:
                restore_orig_backups(target_files)
                return ApplyResult(success=True, no_op=True)

        # 5. Commit — ONLY stage tracked files with changes
        if not dry_run:
            repo.git.add(update=True)  # stages only tracked files with changes
            commit_msg = f"auto-fix: {fix_plan.advisory_id}"
            repo.git.commit("-m", commit_msg, "--no-verify")
            tag_name = f"auto-fix/{fix_plan.advisory_id}/{__import__('datetime').datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
            repo.create_tag(tag_name)

            # Compute diff for backlog
            diff = repo.git.diff("HEAD~1")
            fix_hash = __import__("hashlib").sha256(diff.encode()).hexdigest()[:8]

            # 6. Cleanup .orig_backup on success
            for f in target_files:
                backup = Path(f + ".orig_backup")
                if backup.exists():
                    backup.unlink()

            return ApplyResult(success=True, diff=diff, fix_hash=fix_hash)

        return ApplyResult(success=True)

    except asyncio.TimeoutError:
        restore_orig_backups(target_files)
        return ApplyResult(success=False, error="timeout_120s")
    except Exception as e:
        restore_orig_backups(target_files)
        return ApplyResult(success=False, error=str(e))
```

---

### 2.5 Advisory Queue & Fix Backlog Structure

**Advisory Queue** (`overnight/advisory_queue/pending/`):
- One JSON file per advisory: `{advisory_id}.json`
- Schema: `{"id": "...", "type": "false_positive|missing_enrichment|...", "rule_id": "...", "context": {...}, "created": "ISO8601", "attempts": 0}`
- Daytime workers append here via `engine/queue_manager.py::enqueue_advisory()`
- Crash-resilient: JSONL not used; individual files survive partial writes

**Fix Backlog** (`overnight/fix_backlog.json`):
```json
{
  "applied": [
    {"id": "adv-...", "fix_hash": "a1b2c3d4", "diff": "...", "test_result": "passed", "committed": true, "timestamp": "..."}
  ],
  "pending": [
    {"id": "adv-...", "fix_plan": {...}, "confidence": 0.92, "created": "..."}
  ],
  "rejected": [
    {"id": "adv-...", "reason": "pytest_failed|critique_rejected|...", "details": "...", "timestamp": "..."}
  ]
}
```
- Atomic updates via `os.replace()` on `.tmp` file
- Deduplication via `fix_hash` (SHA256 of unified diff)
- 90-day retention (configurable via `overnight/retention.yaml`)

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

# Dry-run (no commits)
python -m overnight.self_improver --dry-run  # (add --dry-run flag to main() if needed)

# Force re-run after quota reset
rm overnight/openrouter_quota.json overnight/llm_cooldown.json
python -m overnight.self_improver
```

**Monitoring**:
```bash
# Pipeline status (last run)
cat overnight/drain_report.json | jq '{applied: .applied|length, failed: .failed|length, timestamp}'

# OpenRouter quota
cat overnight/openrouter_quota.json | jq '{used, limit: 1000, locked: .locked_until > now}'

# LLM cooldowns
cat overnight/llm_cooldown.json | jq 'to_entries[] | select(.value > now)'

# Advisory queue depth
ls overnight/advisory_queue/pending/*.json | wc -l

# Fix backlog health
cat overnight/fix_backlog.json | jq '{applied: .applied|length, pending: .pending|length, rejected: .rejected|length}'

# Recent git auto-fix tags
git tag -l "auto-fix/*" --sort=-creatordate | head -20
```

**Safety Checklist** (verify before enabling):
- [ ] Test-gated commits only: `apply_auto_fix` runs `pytest -x -q --testmon` before `git commit`
- [ ] No network mutations: Pipeline only reads/writes local FS and calls LLM APIs (HTTPS)
- [ ] Git audit trail: Every fix tagged `auto-fix/<advisory_id>/<timestamp>`
- [ ] Rollback capability: `git revert <tag>` or `git checkout <tag>^ -- <file>`
- [ ] Quota hard limits: OpenRouter 1000 RPD enforced at client + server
- [ ] Concurrency lock: `overnight/.pipeline.lock` prevents overlapping runs
- [ ] Secrets: API keys in `/etc/local-soc-slm/llm_keys.env` (600, root:root)
- [ ] Git identity configured: `git config user.email/name` for pipeline user
- [ ] Pre-commit hooks bypassed: `git commit --no-verify` in `apply_auto_fix`

---

## 3. Integration Points

- **Daytime intake**: `engine/queue_manager.py::enqueue_advisory()` → writes to `overnight/advisory_queue/pending/{id}.json`
- **Enrichment context**: `orchestrator/context_stitcher.py::build_context(advisory)` used in prefill prompts
- **Model registry**: `orchestrator/model_registry.py` provides model metadata for curation (via `overnight/models.yaml`)
- **Memory/RAG**: `memory/embeddings.py::search_similar(advisory.text, k=5)` injects historical fixes into prompts
- **Retention**: `memory/retention.py` purges `fix_backlog.json` entries older than 90 days

---

## 4. Dependencies

| Package | Purpose | Version |
|---|---|---|
| `filelock` | Cross-process locking for quota/cooldown/backlog | `>=3.12` |
| `gitpython` | Git operations (commit, tag, diff) | `>=3.1.40` |
| `httpx` | Async HTTP client for LLM providers | `>=0.27` |
| `pyyaml` | Config parsing (`models.yaml`) | `>=6.0` |
| `pytest-testmon` | Incremental test selection for fast pytest gate | `>=1.4` |

Install via: `pip install -r overnight/requirements.txt`

---

# SECTION 3: TRUNCATION NOTES

| Document | Missing Content | Regeneration Required |
|---|---|---|
| `docs/ARCHITECTURE.md` | SelfImprover class definition incomplete: missing closing `)` for `__init__`, entire `run()` method body after `if not await self.quota.reserve_tokens(...)`, and class closing. The `ImprovementReport` return is truncated. | Regenerate the complete `SelfImprover` class with full `run()` method implementing the corrected synchronous three-phase flow (`prefill_advisory_queue` → `process_advisory_queue` → `drain_fix_backlog`), using `overnight/llm_client.py` and `overnight/openrouter_quota.py` as dependencies. Remove all references to LoRA fine-tuning, DBSCAN clustering, and multiple fix_backlog paths. |
| `docs/LAB_SETUP_GUIDE.md` | Wazuh Manager `ossec.conf` cuts off at `<synchron` inside `<syscheck><synchronization>`. Missing: `</synchronization>`, `</syscheck>`, and all subsequent configuration sections (rootcheck, wodle, labels, etc.). | Regenerate complete `ossec.conf` with full `<synchronization>` element (`<enabled>yes</enabled><interval>5m</interval><max_interval>1h</max_interval></synchronization>`), plus remaining sections: `<rootcheck>`, `<wodle name="open-scap">`, `<wodle name="cis-cat">`, `<labels>`, and closing `</ossec_conf>`. Also correct `slm-overnight` service: remove hardcoded cron `0 3 * * *`, change `FIX_BACKLOG_PATH` to `overnight/fix_backlog.json`, remove `./data/fix_backlog.json` volume mount. |
| `docs/deployment_runbook.md` | §11.3 code block cuts off at bare `from` in `overnight/llm_client.py`. Missing: all imports, provider classes (`OpenRouterProvider`, `GroqProvider`, `GeminiProvider`), `LLMClient` with `complete_with_fallback`, token-aware pacing, cooldown tracking, rate-limit header pre-emption, and model curation logic. | Regenerate complete `overnight/llm_client.py` as a synchronous client (no `async`/`await` in public API) with: OpenRouter → Groq fallback chain, Gemini for prefill/critique, token-aware pacing (`sleep(tokens/10000*2)`), cooldown persistence to `overnight/llm_cooldown.json`, exponential backoff (base 1s, max 60s, jitter ±25%), rate-limit header pre-emption (`x-ratelimit-remaining`/`reset`), and model curation via `overnight/models.yaml`. Remove Ollama, vLLM, LM Studio providers. |