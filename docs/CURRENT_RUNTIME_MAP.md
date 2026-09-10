# Current Runtime Map

**Authority:** current-state repository documentation.

This document records what can be supported from current implementation
traces. It deliberately does not promote intended architecture to implemented
status.

## Operational target

```text
+------------------+
| Security Sources |
| Wazuh / EVE / ...|
+---------+--------+
          |
          v
+------------------+
| Intake            |  OBSERVED
+---------+--------+
          |
          v
+------------------+
| Normalize /       |  OBSERVED / PARTIAL
| Sanitize          |
+---------+--------+
          |
          v
+------------------+
| Context /         |  OBSERVED / PARTIAL
| Enrichment        |
+---------+--------+
          |
          v
+------------------+
| Local / Edge LLM  |  TARGET
+---------+--------+
          |
          v
+------------------+
| Structured        |  PLANNED CONTRACT
| Recommendation    |
+---------+--------+
          |
          v
+------------------+
| Deterministic     |  PLANNED AUTHORITY
| Policy            |
+----+---------+----+
     |         |
   DENY     REVIEW / ALLOW
               |
               v
       +---------------+
       | Bounded       |
       | Writeback     |  CAPABILITY EXISTS
       +-------+-------+
               |
               v
       Audit / Telemetry
```

## Intake

### Wazuh

**OBSERVED:** `engine/intake_wazuh.py` sanitizes/normalizes incoming alert data
and inserts triage records.

### Suricata / EVE

**OBSERVED:** `engine/intake_eve.py` sanitizes selected event content and inserts
triage records.

## Queueing

**OBSERVED:** queue-management code handles lifecycle, priority ordering,
leasing/backpressure, and stale work handling. `engine/queue_priority.py` is the
shared severity-to-priority policy used by queue consumers.

## Sanitization and trust

**OBSERVED:** the repository contains secret-pattern redaction,
field-level filtering, entropy-based detection/quarantine, and sanitizer
checks.

**IMPORTANT:** sanitization is not equivalent to authorization or proof that
external text is a trusted instruction. A first-class data-versus-instruction
trust boundary remains a design requirement.

## SLM triage worker

`engine/slm_triage_worker.py` currently implements a path equivalent to:

```text
triage_queue
  -> SLM HTTP endpoint
  -> verdict JSON
  -> verdicts table
```

**EXPERIMENTAL / ISOLATED:** current evidence does not establish a canonical
downstream production consumer of `verdicts` that performs policy and writeback.

The correct future disposition is integration, replacement, or retirement based
on evidence rather than assumption.

## Model routing

**OBSERVED:** the repository contains local/edge and cloud provider integrations
behind model/provider abstractions.

The current registry uses priority-ordered provider selection, with an observed
cloud candidate still structurally present in the provider set. This is not yet
a sufficient production-local authorization boundary.

**TARGET:**

```text
production SOC request
        |
        v
local / edge provider set only
        |
        v
structured model proposal
```

Development tooling may retain cloud access independently.

## Context and enrichment

**OBSERVED / PARTIAL:** context stitching, IOC extraction, enrichment scheduling,
historical retrieval, and model metadata exist in separate components.

**UNKNOWN:** the single canonical end-to-end production ordering among these
components.

## Writeback capabilities

**OBSERVED:** adapters/capabilities exist for Wazuh proposals, pfSense-related
proposals, TheHive cases, and Security Onion integration.

**UNKNOWN:** a canonical production path from model recommendation through
deterministic policy to each writeback adapter.

## Telemetry and provenance

**OBSERVED / EXPANDING:** telemetry identity, inference-attempt logging, scorecard
metrics, audit/hash-chain infrastructure, and development ledgers exist.

Target provenance chain:

```text
source
 -> transformation
 -> normalized evidence
 -> enrichment
 -> model + model version
 -> proposal
 -> policy version
 -> approval / denial
 -> execution
 -> result
```

## Raspberry Pi verification

**OBSERVED / DEVELOPMENT DOMAIN:** the Pi can provide independent static analysis,
Bandit/Pylint findings, constrained verification, and a separate audit
perspective for autonomous development.

The Pi is not the SOC authorization authority.

## Current unknowns

1. Final canonical alert-to-decision path.
2. Final post-intake trust contract.
3. Final structured recommendation schema.
4. Final deterministic policy schema.
5. Final disposition of `slm_triage_worker`.
6. Production enforcement preventing cloud inference fallback.
7. Final distributed multi-host topology.
