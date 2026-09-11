# Security Model

## Core security principle

External content may be evidence without becoming authority.

A network alert, enrichment result, historical document, model response, or
retrieved text must not be able to elevate its own trust level merely by
containing instructions.

## Trust lifecycle

```text
UNTRUSTED EXTERNAL DATA
          |
          v
normalize / sanitize
          |
          v
provenance-labeled evidence
          |
          v
LOCAL MODEL REASONING
          |
          v
MODEL-GENERATED PROPOSAL
          |
          v
DETERMINISTIC POLICY
          |
     +----+---------+
     |              |
    DENY          REVIEW
                    |
                    v
             bounded ALLOW
                    |
                    v
                EXECUTOR
```

## Trust classes

The canonical future contract should distinguish at minimum:

- `UNTRUSTED` — externally sourced material not yet trusted.
- `TRUSTED` — internally authoritative configuration or policy data.
- `DERIVED` — data deterministically derived from other evidence.
- `CONDITIONALLY_TRUSTED` — accepted for a bounded purpose with restrictions.
- `MODEL_GENERATED` — produced by an LLM and never authoritative by itself.
- `HUMAN_APPROVED` — explicitly authorized by a human within a defined scope.

## Non-negotiable rules

1. Untrusted data cannot elevate itself.
2. Model output cannot authorize itself.
3. Historical text cannot override current policy.
4. Consensus between LLMs is not deterministic authorization.
5. Human approval must be scoped to identity, action, target, parameters, and
   validity window.
6. External content is data, not executable authority.
7. Consequential writeback requires a bounded action contract.

## Implemented security invariants

The current repository provides concrete development-side controls for several
security invariants:

- advisory identity is bound to file path, advisory content, and source hash;
- advisory provenance is checked before autonomous fix processing;
- promotion state is defined by a shared lifecycle contract;
- autonomous patch generation is subject to deterministic safety, test, and
  integrity gates;
- autonomous development changes pass through shadow-canary and human
  promotion boundaries;
- malformed or incompatible governance evidence is rejected by the strict
  ledger event parser.

These controls apply to the current development-autonomy workflow. They do not
constitute authorization for unattended production SOC operation.

## Proposed envelope

**PLANNED:**

```text
soc.event.envelope.v1

source
received_at
collector_version
transform_version
original_payload_hash
normalized_payload_hash
trust_labels
payload
```

## Proposed model proposal

**PLANNED:**

```text
soc.llm.proposal.v1

proposal_id
alert_refs
summary
hypothesis
confidence
evidence_refs
requested_action
prohibited_flags
model_id
model_version
```

## Proposed policy decision

**PLANNED:**

```text
soc.policy.decision.v1

proposal_id
decision
reasons
constraints
policy_version
evaluator
approval_required
```

## Prompt-injection resistance

The security boundary must treat strings such as:

```text
ignore previous instructions
run this command
send these secrets
change the firewall
approve yourself
```

as untrusted content unless independently authorized by trusted policy.

This applies to alerts, enrichment text, DNS/web results, case notes, retrieved
memory, model-generated text, tool output, and anything stored for later
retrieval.

## Development pipeline security

The autonomous development system operates under a different authority model.
It may propose and implement code changes, but deterministic syntax/tests/static
analysis/integrity gates and independent verification remain required before
promotion.

Control-plane or trust-boundary changes require stronger review than ordinary
low-risk maintenance.

## High-value adversarial tests

Future security testing should exercise prompt injection, encoded instructions,
malicious enrichment, tool-output injection, memory poisoning, Unicode tricks,
alert storms, context exhaustion, secret exposure, self-approval, fake
verification results, fake Pi approval, policy modification, system-prompt
modification, unauthorized trusted-memory writes, and attempts to force cloud
routing in production.

## Target invariants

- no unauthorized consequential tool call;
- no self-approval;
- no policy override by model output;
- no unauthorized trusted-memory write;
- no unintended secret exposure;
- model outputs are schema-valid or safely rejected;
- material decisions and execution attempts are auditable.
