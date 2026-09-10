#!/usr/bin/env python3
"""
v3: Surgical pass that preserves the solid Sections 1 and 3 from v2,
rewrites ONLY Section 2 using VERBATIM ground-truth source code.

This time the model is given the real source files as "copy exactly"
material, eliminating the hallucinated code samples that appeared in v2.

Output: overnight/reviews/MASTER_DOCUMENTATION_BUNDLE_TEST_v3.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from overnight.llm_client import generate, load_api_keys, strip_fences

ROOT = Path(__file__).resolve().parent.parent
V2_INPUT = ROOT / "overnight/reviews/MASTER_DOCUMENTATION_BUNDLE_TEST_v2.md"
OUTPUT   = ROOT / "overnight/reviews/MASTER_DOCUMENTATION_BUNDLE_TEST_v3.md"

# ============================================================
# GROUND TRUTH: real source code for the overnight pipeline
# ============================================================
GROUND_TRUTH_FILES = {
    "overnight/self_improver.py":   ROOT / "overnight/self_improver.py",
    "overnight/llm_client.py":      ROOT / "overnight/llm_client.py",
    "overnight/openrouter_quota.py": ROOT / "overnight/openrouter_quota.py",
}

def load_ground_truth():
    sections = []
    for label, path in GROUND_TRUTH_FILES.items():
        if not path.exists():
            print(f"⚠️  Ground truth missing: {path}")
            continue
        content = path.read_text()
        lines = len(content.splitlines())
        print(f"  Loaded {label}: {lines} lines")
        sections.append(f"\n=== {label} ({lines} lines) ===\n```\n{content}\n```\n")
    return "\n".join(sections)

# ============================================================
# PROMPT
# ============================================================
def build_prompt(v2_text, ground_truth):
    return f"""You are given:

(1) A v2 corrected documentation package (below) that has:
    - SECTION 1: ERRATA TABLE (correct — preserve EXACTLY as-is)
    - SECTION 2: Overnight pipeline doc (contains HALLUCINATED code samples
      that do NOT match the real codebase — this section must be REWRITTEN)
    - SECTION 3: TRUNCATION NOTES (correct — preserve EXACTLY as-is)

(2) GROUND TRUTH source code for the overnight pipeline (below). The real
    implementation is SYNCHRONOUS (no async/await in the public API), uses
    requests/httpx sync, and has specific function names:
      - self_improver.py: prefill_advisory_queue(), process_advisory_queue(),
        drain_fix_backlog(), apply_auto_fix()
      - llm_client.py: generate(), _call_openrouter(), _call_groq(),
        _call_gemini(), _groq_preempted(), _groq_note_rl(), _pace()
      - openrouter_quota.py: is_available(), record_attempt(), remaining(),
        force_lock(), status() — module-level functions, NO class

YOUR TASK: Produce a v3 documentation package with these rules:

- SECTION 1 (ERRATA TABLE): Copy it EXACTLY as written in the v2 input.
- SECTION 3 (TRUNCATION NOTES): Copy it EXACTLY as written in the v2 input.
- SECTION 2 (Overnight pipeline): REWRITE using the ground-truth source code.
  For every code sample:
  * Copy function/class signatures VERBATIM from the ground truth
  * Use the real file paths: overnight/self_improver.py, overnight/llm_client.py,
    overnight/openrouter_quota.py
  * Do NOT invent dataclasses, classes, or imports not in the ground truth
    (e.g., no LLMClient class, no ProviderError, no RateLimitError, no
    AllProvidersExhausted, no ApplyResult dataclass, no FileLock import,
    no asyncio.wait_for — use what the real code uses)
  * Show the REAL sync implementations: generate() dispatching to _call_openrouter
    then _call_groq then _call_gemini; apply_auto_fix using subprocess.run
    with sys.executable and pytest

RULES:
- Output ONLY the v3 markdown. No preamble, no explanations.
- Start with "# soc-autopilot Documentation Errata & Corrections (v11.11 — v3)"
- Section 2 should be comprehensive (200-400 lines) but every code sample
  must be grounded in the actual source.

=== V2 INPUT (preserve Sections 1 and 3 exactly; rewrite Section 2) ===
{v2_text[:50000]}

=== GROUND TRUTH SOURCE CODE (use these EXACTLY for Section 2 code samples) ===
{ground_truth[:80000]}

Produce the v3 documentation package now:"""

# ============================================================
# MAIN
# ============================================================
def main():
    if not V2_INPUT.exists():
        print(f"ERROR: {V2_INPUT} not found. Run the v2 refeed first.")
        sys.exit(1)

    v2_text = V2_INPUT.read_text()
    print(f"Loaded v2: {len(v2_text.splitlines())} lines, {len(v2_text):,} chars")

    print("Loading ground truth:")
    ground_truth = load_ground_truth()

    api_keys = load_api_keys()
    if not api_keys.get("openrouter"):
        print("ERROR: OPENROUTER_API_KEY not set in .env")
        sys.exit(1)

    prompt = build_prompt(v2_text, ground_truth)
    print(f"\nPrompt size: {len(prompt):,} chars (~{len(prompt)//4:,} tokens)")
    print("Calling 500B Nemotron via generate() [OpenRouter -> Groq fallback]...")
    print("This may take 2-5 minutes. Be patient.")
    print()

    response = generate(
        prompt,
        api_keys,
        model_type="docs",
        max_tokens=20000,   # bumped from 16K for verbatim code samples
        temperature=0.1,    # lowered from 0.2 — copying demands precision
    )

    if not response:
        print("ERROR: Empty response from all providers")
        sys.exit(2)

    content = strip_fences(response)
    print()
    print(f"Response received: {len(content):,} chars, {len(content.splitlines())} lines")

    # Write to v3 (never overwrite v2)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content)
    print(f"\n✅ v3 output written to: {OUTPUT}")

    # Sanity check: real symbols should appear, hallucinated ones should NOT
    print("\n--- Sanity check (ground-truth symbols) ---")
    real_symbols = [
        "prefill_advisory_queue", "process_advisory_queue", "drain_fix_backlog",
        "apply_auto_fix", "_call_openrouter", "_call_groq", "_call_gemini",
        "is_available", "record_attempt", "force_lock", "strip_fences",
        "_groq_preempted", "_groq_note_rl",
    ]
    for sym in real_symbols:
        count = content.count(sym)
        status = "✅" if count > 0 else "❌ MISSING"
        print(f"  {status}  {sym}: {count}x")

    print("\n--- Sanity check (hallucination symbols — should be absent) ---")
    fake_symbols = [
        "LLMClient", "ProviderError", "RateLimitError", "AllProvidersExhausted",
        "ApplyResult", "FileLock", "asyncio.wait_for", "claude-3.5-sonnet",
        "Ollama", "vLLM", "LM Studio", "DBSCAN", "LoRA",
    ]
    for sym in fake_symbols:
        count = content.count(sym)
        status = "✅ absent" if count == 0 else f"⚠️  STILL PRESENT ({count}x)"
        print(f"  {status}  {sym}")

    print(f"\n📋 Review with: cat {OUTPUT.relative_to(ROOT)} | less")

if __name__ == "__main__":
    main()
