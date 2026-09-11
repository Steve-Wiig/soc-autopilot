# Current Runtime Map: Canonical SOC Inference Path

This document describes the **actual, enforced runtime path** for production SOC triage.

## Core Architectural Principle
**LLM proposes -> Deterministic policy decides -> Bounded action occurs -> Telemetry records evidence.**
The LLM is *never* the authorization authority. Production SOC inference is strictly limited to local/edge models.

## The Canonical Path

1. INTAKE & QUEUE
   Wazuh/EVE Alert -> Normalized & Sanitized -> SQLite triage_queue

2. CANONICAL INFERENCE BOUNDARY
   slm_triage_worker -> InferenceService.generate(scope="soc") -> ModelRouter (ProviderScope.LOCAL_SOC ONLY)

3. STRICT CONTRACT VALIDATION (Fail-Closed)
   Raw LLM text -> Clean/Hash -> SLMRawRecommendation (Pydantic strict=True)

4. IDENTITY & ENVELOPE WRAPPING
   System generates RecommendationEnvelope (event_id, recommendation_id, raw_output_hash)

5. DETERMINISTIC POLICY EVALUATION
   PolicyEvaluator -> Decision (ALLOW / REVIEW / DENY / NO_OP)

6. BOUNDED WRITEBACK & PROVENANCE
   Verdict written to DB -> Telemetry provenance chain

## Critical Security & Reliability Guarantees

1. **No Silent Cloud Fallback**: LOCAL_SOC scope prevents cloud routing.
2. **Strict Schema Enforcement**: Malformed output triggers CONTRACT_VIOLATION.
3. **Identity Ownership**: LLM cannot spoof event_id or recommendation_id.
4. **Policy Authority**: Policy engine only accepts typed RecommendationEnvelope.

## Development vs. Production Autonomy

- **Production SOC Path**: Strictly local/edge inference.
- **Development/Autonomy Path**: Decoupled, may use cloud.
