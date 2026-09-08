# Development Autonomy

## Purpose

The autonomous development system exists to continuously improve the software
without turning the development agent into the runtime SOC authority.

## Loop

```text
audit
  -> diagnose
  -> advisory
  -> test generation
  -> implementation
  -> deterministic verification
  -> independent review
  -> Pi / Bandit verification
  -> canary
  -> Git checkpoint
  -> repeat
```

## Current components

**OBSERVED:** the `overnight/` package contains autonomous review, diagnosis,
patch-generation, telemetry, backlog, defeat/failure learning, safety gates,
canary-related logic, and Git-oriented workflow components.

The repository also contains a Pi patch/finding path that can feed independent
static-analysis findings into the development backlog.

## Authority separation

The development LLM is an engineering tool, not an operational authority.

```text
LLM says "safe"
        !=
policy says "ALLOW"
```

A successful LLM critique or multi-model consensus is still advisory until
accepted by deterministic verification and the relevant human/automated policy.

## Verification roles

### Builder

Generates code/tests/documentation proposals.

### Reviewer

Examines implementation correctness and maintainability.

### Adversarial reviewer

Attempts to find regressions, security flaws, hallucinated APIs, and unsafe
assumptions.

### Deterministic verifier

Runs syntax/AST checks, schema checks, tests, integrity checks, and other
mechanical gates.

### Pi verifier

Provides an independent hardware/context boundary for static analysis and
verification.

### Human

Retains architectural authority where required.

## Autonomous scope

Low-risk maintenance may eventually become capable of automatic promotion when
all relevant gates succeed.

Changes to these areas require elevated review:

- safety gates;
- trust/provenance handling;
- deterministic policy;
- authentication/authorization;
- credentials/secrets;
- network exposure;
- production writeback;
- memory authority;
- verifier bypass behavior.

## Cloud use

Cloud LLMs remain acceptable for development and review. They are not the
production SOC authority.

## Telemetry requirements

Each autonomous iteration should eventually record:

```text
task/advisory
-> source evidence
-> proposed change
-> changed files
-> tests
-> deterministic gates
-> independent verification
-> Pi/Bandit results
-> canary result
-> commit / rollback reference
-> final disposition
```

## Failure handling

Repeatedly unfixable issues should become durable failure knowledge rather than
consume the same resources indefinitely. The defeat/failure ledger pattern is
therefore part of the development architecture.
