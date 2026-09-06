# Blueprint Split Manifest
GENERATED FROM: soc-autopilot
MASTER SHA256: (current HEAD: 970f511)
FILES WRITTEN: 25+
TOTAL LINES: 4327+

## Reassembly Rule
The canonical source of truth is now the split file structure.
The master files (historical master files)
have been superseded by v11.11 and are deprecated.

THE SPLIT FILES ARE NOW CANONICAL:
- sections/ (s30-s38)
- amendments/ (AMEND-1 through AMEND-52+)
- appendices/ (M-Q)
- checklists/
- _frontmatter.md
- _changelog.md

- amendments/amend_v11.5.1_037-041.md
- amendments/amend_v11.5.2_042-046.md
- amendments/amend_v11.6.0_047-052.md
- sections/s30_orchestration_memory.md
- sections/s31_continual_learning.md
- sections/s32_deployment_readiness.md
- sections/s33_inference_vram.md
- sections/s34_sanitization_quarantine.md
- sections/s35_async_ingestion_backpressure.md
- sections/s36_vector_memory_lifecycle.md
- sections/s37_hash_chain_audit.md
- sections/s38_knowledge_wiki.md
- appendices/appendix_m_docs_index.md
- appendices/appendix_n_research_register.md
- appendices/appendix_o_ci_tools.md
- appendices/appendix_p_templates.md
- appendices/appendix_q_runbooks.md
- checklists/release_checklist_v11.6.0.md
- checklists/completeness_manifest.md
- _changelog.md

        ## Amendment → Section Cross-Reference
        AMEND-1   → s30 (AMEND-1 goal)
AMEND-2   → s23, s25 (RAM policy)
AMEND-3   → s23, s25 (dual-GPU)
AMEND-4   → s20 (schema)
AMEND-5   → s24 (tool categories)
AMEND-6   → appendix_g (repo skeleton)
AMEND-7   → s26 (memory client)
AMEND-8   → s29 (orchestrator)
AMEND-9   → s25 (defense pipeline)
AMEND-10  → s21 (signed adapter)
AMEND-11  → appendix_i (config)
AMEND-12  → s24 (CI checks)
AMEND-13  → appendix_m
AMEND-14  → s24 (v11.4 CI)
AMEND-15  → s26 (readiness client)
AMEND-16  → s30.2 (vector index)
AMEND-17  → s30.3 (payload_ref)
AMEND-18  → s30.5 (embedding)
AMEND-19  → s31.5 (replay-mix)
AMEND-20  → s31.6 (canary)
AMEND-21  → s32
AMEND-22  → s33
AMEND-23  → s34
AMEND-24  → appendix_m (verification note)
AMEND-25  → appendix_n
AMEND-26  → appendix_o
AMEND-27  → s33.3 (VRAM)
AMEND-28  → s34.1 (sanitization)
AMEND-29  → s35
AMEND-30  → s36
AMEND-31  → s37
AMEND-32  → appendix_n (R-107–R-111)
AMEND-33  → appendix_o
AMEND-34  → appendix_p
AMEND-35  → release_checklist
AMEND-36  → completeness_manifest
AMEND-37  → s35 (stale recovery)
AMEND-38  → s34 (field-aware entropy)
AMEND-39  → s37 (concurrency)
AMEND-40  → s30.5, s33.5 (idempotent prefix)
AMEND-41  → changelog completeness
AMEND-42  → appendix_m (restore)
AMEND-43  → amendments (restore text)
AMEND-44  → appendix_o (restore skeletons)
AMEND-45  → appendix_p (restore templates)
AMEND-46  → completeness_manifest (strengthen)
AMEND-47  → _frontmatter (readability)
AMEND-48  → s38
AMEND-49  → appendix_q
AMEND-50  → appendix_o (O.16, Gate 16)
AMEND-51  → appendix_p (P.12)
AMEND-52  → completeness_manifest, release_checklist

        ## Section → Section Dependencies
        s30 → s20.2, s34, s35, s36, s37, s38
s31 → s20.7, s24.5, s30.5
s32 → s33, s34, s35, s36, s37, s38, appendix_n
s33 → s34, s35
s34 → s20.2, s30
s35 → s33, s34
s36 → s30.2
s37 → s30.2, s30.3
s38 → s30.3, s33, s34, s35

        ## Loading Recipes
        Wiki / Knowledge expansion:
  s38, s34, s35, s30(30.3), appendix_o(O.16), appendix_p(P.12),
  appendix_q(Q.4), amend_v11.6.0

Sanitization deep-dive:
  s34, appendix_o(O.4, O.5), appendix_p(P.9), appendix_n(R-105, R-110, R-113)

Queue / backpressure tuning:
  s35, s33, appendix_p(P.1–P.4), appendix_o(O.10, O.11), appendix_q(Q.1, Q.3)

Hash-chain / audit integrity:
  s37, s30(30.2–30.3), appendix_p(P.6, P.7, P.10), appendix_o(O.8, O.9), appendix_q(Q.2)

Model lifecycle / canary:
  s31, s33, s30(30.6), appendix_n(R-201–R-204)

VRAM / serving:
  s33, s35(35.8), appendix_o(O.6), appendix_n(R-301, R-302), appendix_q(Q.1)

CI pipeline expansion:
  appendix_o, appendix_p(P.11), s32(32.4), amend_v11.4(AMEND-14)

Integration / API surface:
  appendix_m, appendix_n(N.1, R-001–R-006)

Deployment readiness:
  s32, appendix_n, release_checklist

Onboarding / readability:
  _frontmatter, appendix_m(M.8, M.9), appendix_q, _manifest

