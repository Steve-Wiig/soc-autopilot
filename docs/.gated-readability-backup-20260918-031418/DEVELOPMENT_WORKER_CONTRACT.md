# Development Worker Contract

## Purpose

The SOC-Autopilot engineering loop may use different implementation workers to
produce proposed source-code changes.

A development worker is an implementation mechanism, not a governance authority.

Workers may propose code changes.

Workers MUST NOT:

- approve their own changes
- merge their own changes
- bypass repository safety gates
- bypass tests
- bypass shadow/canary validation
- modify governance records to hide failures
- expand their allowed scope without explicit orchestration authorization

## Architectural Boundary

The engineering pipeline is:

    task / advisory
        |
        v
    orchestration + routing
        |
        v
    development worker
        |
        v
    proposed change
        |
        v
    pre-flight safety gates
        |
        v
    patch validation / application
        |
        v
    regression and acceptance tests
        |
        v
    shadow canary
        |
        v
    Git / human governance

The development worker owns only the implementation step.

## Current Worker

The current autonomous implementation path is the LLM patch-generation flow
inside `overnight/self_improver.py`.

It requests machine-readable Aider-style SEARCH/REPLACE blocks and passes those
through the existing patch application and verification machinery.

The worker implementation must remain replaceable.

## Proposed Worker: Aider

Aider may be introduced as another implementation worker.

Aider MUST be treated as a replaceable worker and NOT as the system's safety,
routing, verification, or governance layer.

The intended future relationship is:

    SOC-Autopilot
         |
         +--> existing LLM patch worker
         |
         +--> Aider worker
         |
         +--> other workers
                 |
                 v
          proposed change
                 |
                 v
          existing gates

## Worker Output Contract

A worker must return a proposed change in a form that the existing engineering
pipeline can validate.

At minimum the result must preserve:

- target file path(s)
- proposed source change
- worker identity
- success/failure state
- error information when generation fails

The worker MUST NOT directly perform final repository approval or merge.

## Scope

The orchestrator, not the worker, defines:

- allowed files
- task description
- acceptance criteria
- risk classification
- required tests
- required safety checks
- whether human review is required

A worker must operate within that scope.

## Verification Ownership

Verification remains outside the worker.

The canonical verification chain remains:

1. pre-flight safety checks
2. patch validation
3. path containment
4. ghost-name / hallucination checks
5. TDD / acceptance validation where applicable
6. pytest
7. shadow canary
8. Git recording
9. human governance decision where required

A worker reporting "success" does not constitute engineering success.

## Git Ownership

Workers do not own the final Git decision.

Branch creation, commit policy, canary handling, merge policy, and final approval
remain under the existing orchestration/governance system.

## Design Principle

LLMs propose.
Workers implement.
Deterministic gates validate.
Tests verify.
Git records.
Humans decide.
