# Development Autonomy Pipeline

**Scope:** autonomous software development only.

This pipeline is intentionally separate from SOC alert processing.

## Core loop

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

## What belongs here

- codebase inspection;
- defect diagnosis;
- test generation;
- patch generation;
- code review;
- adversarial review;
- static/security verification;
- canary testing;
- failure-pattern learning;
- Git checkpoints;
- human escalation.

## What does not belong here

The development pipeline is not the production alert-decision authority.
It must not become a direct path from arbitrary telemetry to consequential SOC
writeback.

## Model policy

Cloud providers may be used for development work, including code generation,
review, documentation, and architecture assistance.

Local models may be used for lightweight engineering work and will be the target
for production SOC inference.

## Safety requirements

The development loop should preserve:

- deterministic syntax/AST validation;
- test gates;
- independent verification;
- truncation/output-shape protection;
- canary/rollback behavior;
- defeat/failure knowledge;
- telemetry and provenance;
- human escalation for elevated-risk changes.

## Current-state language

References in historical material to alternate phases, provider topologies,
quota limits, schedules, model names, paths, or deployment manifests must not be
interpreted as current architecture unless independently verified against the
present source.
