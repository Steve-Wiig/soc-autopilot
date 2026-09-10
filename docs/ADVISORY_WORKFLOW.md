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