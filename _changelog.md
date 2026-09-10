
SOURCE: soc-autopilot
BLOCK: CHANGELOG
SHA256: ab8067b
────────────────────────────────────────────────────────────────────────

v11.11:
- Updated blueprint to current operational baseline (Sept 3, 2026)
- Removed superseded master files (v11.6.0-v11.11.0)
- Declared split files (sections/, amendments/, appendices/) as canonical
- Updated all version references from v11.6.0 to v11.11
- Cleaned up .gitignore duplicates
- Removed committed runtime artifacts and old scripts

v11.10:
- Introduced hardened overnight operating model
- Added synchronous advisory/fix processing
- Added persistent advisory and fix queues
- Implemented OpenRouter/Groq/Gemini provider architecture
- Added AST validation, CoT detection, truncation protection
- Added pytest gating, backup/rollback behavior
- Added quota-aware execution
- Added operational dashboard/reporting
- Documented queue/configuration failure modes

v11.11:
- Historical baseline (superseded by v11.10/v11.11)

SOURCE: soc-autopilot (historical)
BLOCK:  CHANGELOG
SHA256: 515ec36919ce5b83
────────────────────────────────────────────────────────────────────────

v11.6.0-master:
- Added AMEND-47 through AMEND-52.
- Added Executive Summary, How to Read This Document, Glossary, and Blueprint
  Layers to reduce cognitive load and improve onboarding.
- Added Section 38: Operational Knowledge Generation & Externalized Memory.
- Defined SLM lab-journalist Wiki generation as append-only or draft-only,
  sanitized before commit, and queued at low severity.
- Added Appendix Q: Runbooks & Failure Mode Analysis.
- Added tools/wiki_sanitization_check.py to Appendix O.
- Added Appendix N research item R-117 for Wiki sanitization and Git audit
  proof.
- Added Appendix P ledger metadata guidance for Wiki commit references.
- Updated release checklist and completeness manifest for v11.6.0.
- No change to deterministic safety contract.
- No change to approval-gated mutation policy.
- No change to prohibition on autonomous online tuning.
v11.5.2-master:
- Consolidated v11.3, v11.3-updated, v11.4-complete, v11.5, v11.5-master,
and v11.5.1 into one corrected master document.
- Added AMEND-42 through AMEND-46.
- Restored full Appendix M human-readable structure, including endpoint
worksheet, API safety matrix, quick reference, reading list, acceptance
criteria, compact link index, and verification notes.
- Restored full amendment text for AMEND-1 through AMEND-41.
- Restored Appendix O implementation skeletons and explicit CI pipeline
examples.
- Restored Appendix P production-hardening templates required by v11.5 and
v11.5.1.
- Added embedding prefix idempotency tool skeleton and CI gate.
- Added sanitization field-policy tool contract and CI gate.
- Added queue stale recovery tool contract and CI gate.
- Added hash-chain concurrency tool contract and CI gate.
- Added changelog completeness tool contract and CI gate.
- Strengthened completeness manifest to detect omitted Appendix M
subsections, missing amendment text, missing Appendix O skeletons,
missing CI examples, missing Appendix P templates, and missing document
termination marker.
- Corrected v11.5-master Contents typo where Section 28 showed "664 start"
instead of "64GB start".
- No change to deterministic safety contract.
- No change to approval-gated mutation policy.
- No change to prohibition on autonomous online tuning.
v11.5.1-master:
- Consolidated v11.3, v11.3-updated, v11.4-complete, v11.5, and v11.5.1
into one master document.
- Added AMEND-37 through AMEND-41.
- Added stale job recovery and lease-based heartbeat handling to Section 35.
- Added field-aware entropy handling and quarantine-by-reference for
high-value suspicious command-line payloads.
- Added hash-chain concurrency policy and serialized chain sealing.
- Made embedding prefix injection idempotent.
- Added Appendix N research items R-112 through R-116.
- Added v11.5.1 CI tool requirements to Appendix O.
- Added v11.5.1 SQL and Python templates to Appendix P.
- Added changelog completeness and document termination integrity check.
v11.5-master:
- Consolidated v11.3, v11.3-updated, v11.4-complete, and v11.5 update into
one master document.
- Renumbered v11.5 amendments to AMEND-27 through AMEND-36 to avoid
collision with v11.4-complete amendment numbering.
- Added Section 35: Asynchronous Ingestion, Backpressure, and Triage Queue
Governance.
- Added Section 36: Time-Partitioned Vector Memory and Index Lifecycle.
- Added Section 37: Hash-Chained Audit Ledger and Tamper Detection.
- Added Appendix P: Production-Hardening SQL, Python, and CI Templates.
- Updated Section 33 to require dynamic VRAM detection and 90% safety cap.
- Updated Section 34 to require two-pass sanitization using regex and
Shannon entropy.
- Added queue backpressure, shedding, dead-letter, and severity
prioritization requirements.
- Added time-partitioned case_embeddings policy with active-partition HNSW
index lifecycle.
- Added hash-chain tamper detection for handoffs and corrections.
- Added Appendix N research items R-107 through R-111.
- Added completeness manifest and end-of-document marker.
v11.5:
- Added asynchronous ingestion backpressure governance.
- Added time-partitioned vector memory governance.
- Added hash-chained audit ledger governance.
- Added dynamic VRAM detection.
- Added two-pass sanitization.
- Added production-hardening templates.
v11.4-complete:
- Added Deployment Readiness & Verification Register.
- Added Inference, Embedding, and VRAM Governance.
- Added Sanitization, Quarantine, and Artifact Reference Governance.
- Added Appendix N and Appendix O.
- Added LAB-VERIFY posture for external integration behavior.
- Added payload_ref canonical URI and integrity metadata.
- Added embedding model pinning and prefix validation.
- Changed pgvector index requirement from fixed IVFFlat to benchmark-selected
HNSW/sequential scan policy.
- Added replay-mix metric and evidence requirements.
- Added canary shadow/limited modes and rollback audit requirements.
v11.3-updated:
- Added Appendix M: Documentation for open source security software and API
documentation.
- Reformatted Appendix M for human readability.
- Added API/documentation link index for Wazuh, Security Onion, Suricata,
TheHive, pfSense, OpenSearch, PostgreSQL, pgvector, SQLite, and
nomic-embed-text.
- Added human-readable integration boundary map and API safety matrix.
- Added credential and access guidance.
- Added documentation mirror recommendations.
- Added endpoint worksheet for lab deployment.
- Completed Section 31 reference structure for replay-mix evaluation,
canary, rollback, and prohibited autonomous online tuning.
v11.3:
- Added Section 30: Orchestration Memory Architecture.
- Added Section 31: Continual Learning & Experience Policy.
- Added Appendix K: Orchestration Memory DDL, retention, and backup.
- Added Appendix L: Adapter routing & continual-learning config.
- Added AMEND-1 through AMEND-12.
- Introduced PostgreSQL + pgvector + SQLite memory model.
- Introduced append-only handoff ledger policy.
- Introduced replay-mix evaluation and atomic adapter promotion.
- Explicitly prohibited autonomous online tuning.

