# Advisory Workflow

## Purpose

The advisory workflow provides a controlled lifecycle for identifying,
evaluating, and tracking potential improvements in the SOC-Autopilot system.

The workflow is designed to maintain a clear separation between:

- automated analysis
- advisory generation
- operator decision making
- remediation execution
- verification

The system does not blindly modify code based on model suggestions.
Advisories are evaluated through safety controls before remediation is
allowed.

---

# Design Principles

The advisory workflow follows these principles:

## Local First

All core operation is designed to function locally.

External model providers and telemetry destinations are optional
extensions and are not required for the workflow to operate.

## Safety Before Automation

Automated analysis may identify potential issues, but remediation requires
validation through existing safety gates.

## Append Only Telemetry

Workflow events are recorded as telemetry events to preserve an audit trail.

## Category Aware Processing

Different advisory categories require different handling.

Examples:

- security issues require elevated review
- correctness issues require validation
- performance issues require impact analysis
- maintainability issues may be deferred or batched

---

# Workflow Overview

```mermaid
flowchart TD

A[Telemetry and Code Analysis] --> B[Issue Detection]

B --> C[Category Aware Triage]

C --> D{Safety and Confidence Evaluation}

D -->|Low Confidence| E[Advisory Queue]

D -->|Approved| F[Remediation Pipeline]

E --> G[Operator Review]

G -->|Approve| F

G -->|Reject| H[Deferred Advisory]

F --> I[Code Generation]

I --> J[AST and Syntax Validation]

J --> K[Pytest Verification]

K -->|Pass| L[Commit Candidate]

K -->|Fail| M[Failure Ledger]

L --> N[Operator Review]

N --> O[Completed Change]a


---

# Queue Lifecycle

Advisories and their derived work products live in overnight/advisory_queue/.

## Directories

    advisory_queue/
      pending/                    queued advisories awaiting review
      failed/
        parse_failed/             provider returned unparseable output
        cooldown_blocked/         death-loop cooldown triggered
        stale_target_changed/     advisory predates current file content
      CLEANUP_MANIFEST_*.json     reversal record for archival operations

## Prefill dedup

prefill_advisory_queue scans both pending/ and failed/ recursively before
paying a cloud provider to analyze a file. If the file current source_hash
matches any queued or archived advisory, the prefill call is skipped.
This prevents re-paying for content already analyzed.

## Archive instead of delete

When an advisory cannot proceed (parse failure, cooldown block, stale
target), it is moved to a failed/ subdirectory with a timestamp suffix
rather than deleted. The prefill dedup set includes these files, so
archived advisories are not re-paid on the next cycle.

## Cooldown key

Death-loop detection uses (file, normalized_advisory_text) as the cooldown
key. The source content hash is deliberately excluded: a repeat of the
same advisory against a patched file is exactly the loop the cooldown is
meant to interrupt. Three failed attempts against the same key within
24 hours blocks further attempts for that advisory.

## Reversal

Archival operations are reversible.

- Restore from failed/<reason>/ back to pending/:
      mv failed/<reason>/*.json pending/
- Un-backfill a source hash: remove the source_hash and
  source_hash_backfilled_at keys from the advisory JSON.
