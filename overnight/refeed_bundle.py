#!/usr/bin/env python3
"""
Refed the master documentation bundle into the 500B Nemotron model along with
reviewer corrections. Writes the corrected output to a NEW test file.

The task is scoped to fix the two problem classes identified in review:
  A. Truncated source documents (ARCHITECTURE, LAB_SETUP_GUIDE, deployment_runbook)
  B. Overnight-layer drift (hallucinated because generate_docs.py only injects
     context for engine/, orchestrator/, memory/ — NOT overnight/ or tools/)

Output: overnight/reviews/MASTER_DOCUMENTATION_BUNDLE_TEST_v2.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from overnight.llm_client import generate, load_api_keys, strip_fences

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "overnight/reviews/MASTER_DOCUMENTATION_BUNDLE_TEST.md"
OUTPUT = ROOT / "overnight/reviews/MASTER_DOCUMENTATION_BUNDLE_TEST_v2.md"

# ============================================================
# REVIEWER CORRECTIONS (ground truth from manual review)
# ============================================================
CORRECTIONS = """\
## A. TRUNCATED SOURCE DOCUMENTS (cut off mid-generation at the 8K output cap)
1. docs/ARCHITECTURE.md — cuts off mid-class at `return ImprovementReport`;
   the SelfImprover class definition is incomplete (missing closing paren and
   the rest of the run() method body).
2. docs/LAB_SETUP_GUIDE.md — cuts off mid-XML-attribute at `<synchron` inside
   the Wazuh Manager ossec.conf block.
3. docs/deployment_runbook.md — cuts off at a bare `from` in the §11.3 code block.

## B. OVERNIGHT-LAYER DRIFT (hallucinated content — replace with ground truth)
The doc generator injects module context ONLY for engine/, orchestrator/, and
memory/. The overnight/ layer had NO grounding, so the model invented plausible
fiction. Replace ALL overnight-pipeline descriptions with this ground truth:

| Docs CLAIM (wrong) | GROUND TRUTH (correct) |
|---|---|
| `orchestrator/llm_client.py` with Ollama/vLLM/LM Studio providers | `overnight/llm_client.py` — providers are OpenRouter, Groq, Gemini |
| async `phase_a_prefill()` / `phase_b_analyze()` / `phase_c_drain()` | sync `prefill_advisory_queue()` / `process_advisory_queue()` / `drain_fix_backlog()` |
| `SelfImprover` class doing LoRA fine-tuning + DBSCAN clustering | flat script: advisory analysis -> Gemini validation -> test-gated code fixes |
| fix_backlog at `/var/lib/soc/`, `/data/self_improver/`, AND `overnight/` (3 paths) | `overnight/fix_backlog.json` (single path) |
| OpenRouter quota: `$10 USD/day` vs `50 RPD` vs `500K tokens` (3 models) | 1000 RPD (funded tier), 24h lock on exhaustion, UTC rollover |
| Schedule: 02:00 UTC vs 03:00 local vs `0 3 * * *` (3 answers) | NO hardcoded schedule — user-configured cron/systemd timer |
| "Last Updated: 2025-01-15" | Fabricated date — REMOVE |
| LLMProvider Protocol with claude-3.5-sonnet primary | free Nemotron via OpenRouter -> Groq compound fallback -> Gemini for prefill/critique |

## C. SAFETY CONTRACT (accurate in original — PRESERVE verbatim)
These concepts are correct and must be kept:
- Test-gated commits only (pytest must pass before `git commit`)
- No `git push` is ever executed by the pipeline
- `.orig_backup` crash recovery (restore on exception, cleanup on success)
- Git no-op detection (`git diff --exit-code`; skip commit if clean)
- 120s timeout on fix application
- Cross-model validation (Gemini critiques findings; catches 60-80% of hallucinations)
"""

# ============================================================
# PROMPT
# ============================================================
def build_prompt(bundle_text):
    return f"""You are given the complete master documentation bundle for soc-autopilot v11.11
and a set of REVIEWER CORRECTIONS that identify factual errors and truncated content.

Produce a CORRECTED documentation package with exactly these sections, in order:

# SECTION 1: ERRATA TABLE
A markdown table listing EVERY correction: | Document | Wrong | Correct |.
Cover all items in Section A and Section B of the corrections.

# SECTION 2: Overnight Self-Improving Pipeline — CORRECTED (full rewrite)
Rewrite the overnight pipeline architecture and operations guide using ONLY the
ground truth in the corrections. Describe the REAL components:
- overnight/self_improver.py: prefill_advisory_queue(), process_advisory_queue(),
  drain_fix_backlog() — synchronous, advisory queue in overnight/advisory_queue/pending/,
  fixes queued to overnight/fix_backlog.json
- overnight/llm_client.py: OpenRouter -> Groq fallback, Gemini for prefill + critique,
  token-aware pacing, cooldown tracking, exponential backoff, rate-limit header
  pre-emption, model curation
- overnight/openrouter_quota.py: 1000 RPD funded tier, 24h lock, UTC rollover,
  atomic writes
- The apply_auto_fix safety contract (Section C above — preserve verbatim)
Use exact module names, function names, and file paths from the ground truth.
Do NOT invent providers, classes, or paths not in the corrections.

# SECTION 3: TRUNCATION NOTES
For each truncated document (Section A), state what is missing and what must be
regenerated to complete it.

RULES:
- Output ONLY the corrected markdown. No preamble, no "here is", no explanations.
- Start with "# soc-autopilot Documentation Errata & Corrections (v11.11)".
- Be comprehensive in Section 2 (aim for 150-300 lines).
- Use the ground truth table as your single source of truth.

=== REVIEWER CORRECTIONS ===
{CORRECTIONS}

=== MASTER DOCUMENTATION BUNDLE (for reference) ===
{bundle_text}

Produce the corrected documentation package now:"""

# ============================================================
# MAIN
# ============================================================
def main():
    if not BUNDLE.exists():
        print(f"ERROR: {BUNDLE} not found. Run combine_docs.py first.")
        sys.exit(1)

    bundle_text = BUNDLE.read_text()
    bundle_lines = len(bundle_text.splitlines())
    print(f"Loaded bundle: {bundle_lines} lines, {len(bundle_text):,} chars")

    api_keys = load_api_keys()
    if not api_keys.get("openrouter"):
        print("ERROR: OPENROUTER_API_KEY not set in .env")
        sys.exit(1)

    prompt = build_prompt(bundle_text)
    print(f"Prompt size: {len(prompt):,} chars (~{len(prompt)//4:,} tokens)")
    print("Calling 500B Nemotron via generate() [OpenRouter -> Groq fallback]...")
    print("This may take 2-5 minutes. Be patient.")
    print()

    response = generate(
        prompt,
        api_keys,
        model_type="docs",
        max_tokens=16000,
        temperature=0.2,
    )

    if not response:
        print("ERROR: Empty response from all providers")
        sys.exit(2)

    content = strip_fences(response)
    print()
    print(f"Response received: {len(content):,} chars, {len(content.splitlines())} lines")

    # Write to new test file (never overwrite the original)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content)
    print()
    print(f"Corrected output written to: {OUTPUT}")
    print(f"   Review with: cat {OUTPUT.relative_to(ROOT)} | less")

if __name__ == "__main__":
    main()
