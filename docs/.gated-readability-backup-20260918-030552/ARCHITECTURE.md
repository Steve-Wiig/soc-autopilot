# SOC-Autopilot Architecture

**Last updated: September 14, 2026**

## Architectural rule

LLM proposes -> deterministic policy decides -> bounded action occurs -> telemetry records evidence -> humans remain authoritative.

SOC-Autopilot separates production SOC autonomy from development autonomy.

## Production SOC path

Wazuh / EVE
  -> intake / normalization / sanitization
  -> SQLite triage queue
  -> slm_triage_worker
  -> InferenceService(scope="soc")
  -> ModelRouter(LOCAL_SOC)
  -> strict recommendation contract
  -> runtime-owned identity / envelope
  -> deterministic policy
  -> bounded writeback
  -> telemetry / provenance

Production model output is never the final authorization authority.

## Development autonomy

Repository evidence
  -> advisory
  -> provenance validation
  -> baseline / TDD
  -> implementation worker
  -> deterministic patch validation
  -> regression testing
  -> independent verification
  -> canary / promotion
  -> Git checkpoint

## Aider development boundary

Aider is a development implementation worker, not a production SOC component.

Aider requires:
- a clean canonical worktree before execution;
- a disposable isolated worktree;
- explicit authorized files;
- no Git-history mutation;
- unauthorized changed-path rejection;
- deterministic diff materialization;
- existing safety, regression, verification, and promotion gates.

Aider success means a bounded proposal exists. It does not mean approval or promotion.

Cloud development providers may be used in this development plane when explicitly enabled. They are not production SOC inference providers.

## Protected kernel

The autonomous mutation path cannot modify protected control-plane files or tests/.

This includes self-improvement control, safety gates, deterministic policy and queue controls, trust-boundary logic, worker authorization/dispatch/isolation, and the Aider worker itself.

The purpose is to prevent the development worker from weakening the mechanisms that govern and evaluate it.

## Provenance and queues

pending advisory
  -> queue processing
  -> fix backlog
  -> source/provenance validation
  -> validation / implementation
  -> promotion / escalation

Source hashes bind advisories to the source content that was actually reviewed. Changed source invalidates stale advisory evidence.

## Failure behavior

The control plane is intended to fail closed:

- stale or missing provenance -> defer
- protected target -> escalate
- unauthorized changed path -> reject or escalate
- Git-history mutation -> reject or escalate
- invalid patch -> reject
- failed verification -> no promotion
- terminal Aider worker or safety failure -> escalate rather than retry as a generic empty response

Provider or inference failures may be retryable only where the provider-dispatch contract explicitly permits fallback.

## Independent verification

Pi and edge workers plus static-analysis findings provide development verification evidence. They do not become production policy authority merely by returning a positive verdict.

## Status

SOC-Autopilot remains an experimental/research project. Repository components that are isolated or experimental must not be represented as production-authoritative merely because their code exists.
