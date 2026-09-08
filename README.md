# SOC-Autopilot

Local-first, evidence-driven security orchestration and autonomous software
maintenance.

## What this project is

SOC-Autopilot is being built around two separate autonomy domains that share
verification discipline but have different authorities.

### 1. SOC operational autonomy

```text
telemetry
  -> intake
  -> normalize / sanitize
  -> provenance + trust handling
  -> context / enrichment
  -> local/edge LLM
  -> structured recommendation
  -> deterministic policy
  -> ALLOW / DENY / REVIEW
  -> bounded writeback
  -> audit / telemetry
```

The LLM is the reasoning and proposal layer. It is not the final authority for
consequential actions.

### 2. Development autonomy

```text
audit
  -> diagnose
  -> advisory
  -> LLM engineering
  -> tests
  -> deterministic gates
  -> independent verification
  -> Pi / Bandit
  -> canary
  -> Git
  -> repeat
```

The development loop may continuously improve the codebase, but it is not the
SOC runtime and does not directly authorize SOC actions.

## Local-first LLM policy

Cloud LLMs remain useful for development, code generation, code review,
adversarial review, testing, documentation, and architecture work.

Production SOC inference is intended to remain operator-controlled local/edge
inference. A future distributed deployment may separate ingestion, inference,
orchestration, enrichment, telemetry, and verification across hosts using
stable authenticated interfaces.

A deterministic policy layer is intended to stand between model-generated
recommendations and consequential operational actions.

## Engineering philosophy

> LLMs propose -> safety gates validate -> tests verify -> independent
> verification audits -> Git records -> humans decide where required.

The project deliberately favors reproducibility, evidence, explicit trust
boundaries, bounded autonomy, rollback, and observable failure handling.

## Current-state terminology

- **OBSERVED** — supported by current repository evidence.
- **EXPERIMENTAL** — implemented or partially implemented, but isolated or not
  proven as the canonical production path.
- **PLANNED** — intended design not yet fully implemented.
- **UNKNOWN** — requires additional repository or runtime evidence.

## Canonical documentation

- `docs/ARCHITECTURE.md`
- `docs/CURRENT_RUNTIME_MAP.md`
- `docs/SECURITY_MODEL.md`
- `docs/DEVELOPMENT_AUTONOMY.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/adr/0001-separate-soc-and-development-autonomy.md`

Historical and generated documents are not architectural authority unless they
are explicitly identified as current evidence.
