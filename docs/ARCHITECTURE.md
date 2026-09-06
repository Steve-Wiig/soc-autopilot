# soc-autopilot: Autonomous Engineering Architecture

This document outlines the cognitive architecture, safety gates, and operational topology of the autonomous self-improving pipeline.

## 1. Core Pillars

### Pillar 1: The Memory Layer (Defeat Ledger)
*   **Purpose:** Prevents infinite API token burn on "poison pill" bugs.
*   **Mechanism:** Hashes the AST (stripping docstrings/comments) and the normalized pytest traceback. 
*   **Quarantine:** If a specific file AST + failure signature hits 3 strikes, the `is_ast_defeated()` pre-flight check instantly aborts generation.

### Pillar 2: The Output Contract (Patch-Diff)
*   **Purpose:** Eliminates LLM truncation and massive token waste on large files.
*   **Mechanism:** Forces both WHOLE-FILE and SURGICAL paths to output deterministic Aider-style `<<<<<<< SEARCH / >>>>>>> REPLACE` blocks.
*   **Engine:** `engine/patch_parser.py` applies the diffs safely, falling back to fuzzy matching if the LLM hallucinates minor whitespace shifts.

### Pillar 3: Cognitive Escalation (The Meta-Critic)
*   **Purpose:** Breaks the "Local Minimum Trap" where the LLM repeatedly generates the same logically flawed code.
*   **Mechanism:** When Attempt 1 passes syntax but fails `pytest`, a fast/cheap model (Mistral 7B) analyzes the traceback and generates a 1-sentence **Strategic Constraint**.
*   **Refeed:** This constraint is injected into the Attempt 2 prompt, forcing the heavy model to adopt a fundamentally different algorithm.

### Pillar 4: The Red-Green Baseline
*   **Purpose:** Turns the LLM from a "guesser" into a "stack-trace resolver" and eliminates stale advisories.
*   **Mechanism:** Runs `pytest` *before* calling the LLM. If tests pass, the advisory is a false positive and is instantly deleted. If they fail, the raw stack trace is injected into the Attempt 1 prompt.

## 2. Operational Topology & Safety Gates

### Advisory Generation: Gemini Pre-Fill (The Ghostbuster)
*   Scans all source files and generates advisories.
*   **Ghostbuster Protocol:** AST-driven negative constraint injected into the prompt forbidding the reporting of stylistic issues, missing docstrings, or type hints.

### Shadow Canary: OpenRouter Processing
*   Drains the advisory queue and feeds issues to heavy coding models.
*   **Stylistic Noise Filter:** Instantly defers any advisory categorized as `style`, `maintainability`, or `complexity` to protect the API budget.

### The Bounded Repair Loop (Sniper Scope)
*   **Test Isolation:** Maps the target file to its specific `test_*.py` file. Drops `pytest` feedback time from ~7s to ~0.2s.
*   **The Loop:** Generation -> Patch Parser -> AST Check -> Pytest Check. If Pytest fails on Attempt 1, triggers the Meta-Critic and retries with the strategic constraint on Attempt 2.

## 3. Telemetry & Evacuation
*   **Stage 1:** 12 telemetry hooks write JSONL events to a local 1MB rotating buffer.
*   **Stage 2:** A `cron` job runs every 5 minutes, checks the `st_dev` guardrail to ensure the NAS is mounted, and `rsync`s the outbox to the 200GB NAS archive.
*   **Fail-Open:** If the NAS is asleep, the syncer safely aborts to protect the 30GB root disk.

## 4. Future Roadmap (The Winter Projects)
*   **The Efficacy Matrix:** Use JSONL telemetry to dynamically route tasks to the provider with the highest historical success rate.
*   **Causal Triage:** Cluster tracebacks to fix root-cause imports instead of attacking 15 leaf-node test files.
*   **TDD Sub-Agent:** Generate the failing `pytest` test *before* generating the fix.

## 5. Advanced Cognitive Pillars (Post-Final Form)

### Pillar 5: The Fuzzy Multi-File Patcher
*   **Purpose:** Enables cross-file atomic transactions (e.g., changing a function signature and its imports simultaneously).
*   **Mechanism:** Parses Aider-style `<<<<<<< path/to/file.py` blocks. If exact string matching fails due to whitespace hallucinations, it uses `difflib.SequenceMatcher` to find the closest 80% matching block and applies the patch surgically.

### Pillar 6: Failure Autopsy & Prompt Evolution
*   **Purpose:** Prevents the LLM from making the exact same hallucination on Attempt 2.
*   **Mechanism:** When Attempt 1 fails (patch error or pytest failure), a fast LLM performs a "Failure Autopsy" to generate a 2-sentence cognitive constraint explaining *why* it failed (e.g., "abruptly truncated output").
*   **Dynamic Tuning:** The system analyzes the autopsy and dynamically adjusts `max_tokens` (if truncated) or `temperature` (if logic was flawed) for Attempt 2.
*   **Negative Prompting:** The raw, broken code from Attempt 1 is appended to the Attempt 2 prompt under a `<<<<<<< YOUR PREVIOUS FAILED ATTEMPT` block.

### Pillar 7: Test Quarantine Sanitizer (The Bouncer)
*   **Purpose:** Prevents hallucinated TDD tests from poisoning the Red-Green Baseline.
*   **Mechanism:** Runs `pytest --collect-only` on auto-generated `test_tdd_auto_*.py` files. If they fail collection (e.g., bad imports), they are instantly moved to `.quarantined_tests/` outside the `tests/` directory, ensuring `pytest` recursively ignores them.

## 6. Observability & Maintenance

### The Black Box Flight Recorder
*   **Mechanism:** Every prompt and raw response is logged to `reasoning_ledger.jsonl`.
*   **Guardrail:** Uses `st_dev` checks to write directly to the NAS (`/dev/sdc`) when mounted, falling back to a local buffer when offline.

### The System Doctor
*   **Mechanism:** A comprehensive read-only diagnostic script (`tools/system_doctor.py`) that prints the entire state of the machine: Git state, queues, defeat ledger, API budgets, NAS health, and recent logs.

## 5. Advanced Cognitive Pillars (Post-Final Form)

### Pillar 5: The Fuzzy Multi-File Patcher
*   **Purpose:** Enables cross-file atomic transactions (e.g., changing a function signature and its imports simultaneously).
*   **Mechanism:** Parses Aider-style `<<<<<<< path/to/file.py` blocks. If exact string matching fails due to whitespace hallucinations, it uses `difflib.SequenceMatcher` to find the closest 80% matching block and applies the patch surgically.

### Pillar 6: Failure Autopsy & Prompt Evolution
*   **Purpose:** Prevents the LLM from making the exact same hallucination on Attempt 2.
*   **Mechanism:** When Attempt 1 fails (patch error or pytest failure), a fast LLM performs a "Failure Autopsy" to generate a 2-sentence cognitive constraint explaining *why* it failed (e.g., "abruptly truncated output").
*   **Dynamic Tuning:** The system analyzes the autopsy and dynamically adjusts `max_tokens` (if truncated) or `temperature` (if logic was flawed) for Attempt 2.
*   **Negative Prompting:** The raw, broken code from Attempt 1 is appended to the Attempt 2 prompt under a `<<<<<<< YOUR PREVIOUS FAILED ATTEMPT` block.

### Pillar 7: Test Quarantine Sanitizer (The Bouncer)
*   **Purpose:** Prevents hallucinated TDD tests from poisoning the Red-Green Baseline.
*   **Mechanism:** Runs `pytest --collect-only` on auto-generated `test_tdd_auto_*.py` files. If they fail collection (e.g., bad imports), they are instantly moved to `.quarantined_tests/` outside the `tests/` directory, ensuring `pytest` recursively ignores them.

## 6. Observability & Maintenance

### The Black Box Flight Recorder
*   **Mechanism:** Every prompt and raw response is logged to `reasoning_ledger.jsonl`.
*   **Guardrail:** Uses `st_dev` checks to write directly to the NAS (`/dev/sdc`) when mounted, falling back to a local buffer when offline.

### The System Doctor
*   **Mechanism:** A comprehensive read-only diagnostic script (`tools/system_doctor.py`) that prints the entire state of the machine: Git state, queues, defeat ledger, API budgets, NAS health, and recent logs.

### Pillar 8: Stale Advisory Auto-Clear (The Ghost Protocol)
*   **Purpose:** Protects the API budget from untestable or already-fixed advisories.
*   **Mechanism:** Before invoking the LLM, the engine runs the Red-Green Baseline (`pytest`). If the baseline passes, the engine concludes the advisory is "stale" (the bug doesn't exist, or the test doesn't catch it) and immediately deletes it from the backlog without spending API tokens.
*   **Observability:** Dropped items print `✅ Baseline tests passed. Stale advisory.` to the matrix rain, providing a paper trail of queue depletion.
