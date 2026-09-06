# LLM Documentation Audit Prompts

Use these prompts when routing heavy documentation forensics through high-context API models (e.g., Qwen 72B via OpenRouter/Groq) to avoid local 16GB VRAM limits.

## Execution Strategy (From Gemini/ChatGPT Handoffs)
1. **Staged Execution:** Do NOT request all deliverables in a single prompt. 
2. **Phase 1 First:** Force the model to output the Audit Report and Status Snapshot first. Review it to ensure it correctly identified the v11.10 safety gates.
3. **Phase 2 Second:** Once the audit is verified, prompt for the actual Master Documentation rewrite.
4. **API Routing:** Use high-context API endpoints for this read-heavy task. Reserve local GPU compute for the atomic auto-fix commits.

---

## Phase 1: The Audit & Snapshot
**Input:** Paste the contents of `audit_context.txt` (generated via `cat docs/*.md > audit_context.txt`) at the bottom.

You are an expert Technical Documentation Auditor and Systems Architect. 
Your task is to perform a "documentation-forensics pass" on the soc-autopilot project. 
I have provided the current documentation corpus and the project file tree below.

DO NOT rewrite the master blueprint yet. We are doing this in staged phases to ensure accuracy.

### YOUR IMMEDIATE TASK (Phase 1):
Analyze the provided documentation and produce two specific deliverables:

**Deliverable 1: The Documentation Audit Report**
Create a concise, evidence-based report identifying:
1. What is actually current vs. what is historical.
2. Contradictions between older and newer documentation.
3. Missing documentation (features present in code but missing from docs).
4. A "Documentation Reconciliation Table" showing: [Topic] | [Old Doc Claim] | [New Doc Reality] | [Action Required].

**Deliverable 2: The "Current State" Snapshot**
Write a short, highly accurate "What is this system TODAY?" section.

### STRICT RULES:
- Treat older status documents as HISTORICAL. Treat newer hardening docs as CANONICAL.
- Do not invent implementation details. Mark unverified claims as "UNVERIFIED".
- Preserve "Critical Operational Lessons" verbatim.

---

## Phase 2: The Master Documentation Rewrite
**Input:** Paste the output from Phase 1.

Excellent work on the Audit Report and Current State Snapshot. The forensic analysis is approved. 
We are now moving to Phase 2: Generating the actual, final MASTER_DOCUMENTATION_BUNDLE.md.

### YOUR TASK:
Write the complete, consolidated MASTER_DOCUMENTATION_BUNDLE.md based strictly on the Audit Report and Current State Snapshot.

### STRICT RULES:
1. Eradicate stale historical material (e.g., v11.11 async/JSONL architecture).
2. Declare the system as the current Hardened State (v11.10).
3. Incorporate the newest "Critical Operational Lessons" verbatim.
4. Confirm all implemented safety gates (AST, CoT, Pytest) as active controls.
5. Output ONLY the raw Markdown. No conversational filler.
