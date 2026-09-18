# SOC Autopilot: Open-Source XSIAM

## The Vision
Building an intelligent, open-source SOAR platform that makes the sum of its parts greater than the whole. We orchestrate Wazuh, Security Onion, Sigma, and YARA into a cohesive, AI-powered defense system.

## Core Capabilities
1. **Alert Enrichment**: LLM-generated context, MITRE mapping, and false-positive analysis with strict 30s timeouts.
2. **Alert Correlation**: Grouping noisy alerts into coherent incidents based on time, IP, and user.
3. **Automated Response**: Generating safe Wazuh Active Response scripts, Sigma rules, and YARA rules.

## Architecture Principles
- **Cryptographic Verification**: AI changes are signed by a 3-judge quorum.
- **Strict Contracts**: Pydantic models enforce data integrity (UUID v4, Enums).
- **Fail-Safe Defaults**: If the LLM fails, the system rolls back to a known-good state.
- **Zero Cost**: Hardlocked to free-tier Nemotron 120B model.

## How to read this repository

For the shortest path through the project:

1. `docs/ARCHITECTURE.md` — system boundaries and authority separation.
2. `docs/SECURITY_MODEL.md` — trust model and non-negotiable security rules.
3. `docs/CURRENT_RUNTIME_MAP.md` — implementation-backed runtime path.
4. `docs/DEVELOPMENT_AUTONOMY.md` — bounded autonomous development workflow.
5. `docs/DEVELOPMENT_WORKER_CONTRACT.md` — development-worker authority and scope.
6. `docs/OPERATIONS_RUNBOOK.md` — evidence-first operating guidance.

The repository intentionally distinguishes observed implementation from experimental and planned design.

## Validation checkpoint

The latest local regression-suite checkpoint recorded 870 passing tests and 1 skipped test. This is a test-suite checkpoint, not a production-readiness claim.
