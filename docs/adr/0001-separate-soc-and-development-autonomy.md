# ADR-0001 — Separate SOC Operational Autonomy from Development Autonomy

## Status

Accepted architectural direction.

## Decision

SOC operational autonomy and autonomous software development remain separate
systems with separate authorities.

## SOC operational domain

```text
telemetry
 -> normalize / sanitize
 -> provenance / trust
 -> context / enrichment
 -> local LLM
 -> structured proposal
 -> deterministic policy
 -> approval where required
 -> bounded writeback
```

## Development domain

```text
audit
 -> diagnose
 -> LLM engineering
 -> tests
 -> deterministic verification
 -> independent verification
 -> Pi / Bandit
 -> canary
 -> Git
 -> repeat
```

## Rationale

The distinction prevents engineering automation from being mistaken for
operational authorization and allows cloud LLMs to remain useful for development
without making them production SOC dependencies.

## Consequences

The codebase can evolve autonomously while preserving deterministic operational
authority, independent verification, rollback, auditability, and a local-first
production target.

## Follow-on requirements

1. Define the canonical alert envelope.
2. Define the canonical model-proposal schema.
3. Define deterministic action policy and decision schema.
4. Enforce local-only production inference.
5. Establish the actual end-to-end call chain.
6. Integrate or retire isolated components based on evidence.
