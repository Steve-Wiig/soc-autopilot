# Architecture

SOC-Autopilot is a local-first security automation system with a separate
autonomous software-maintenance system.

## SOC operational architecture

```text
telemetry
  -> intake
  -> normalize/sanitize
  -> context/enrichment
  -> local LLM
  -> structured recommendation
  -> deterministic policy
  -> approval / bounded action
  -> writeback
  -> audit/telemetry
```

## Production inference

Production SOC inference is intended to use operator-controlled local/edge
models.

Cloud models remain useful for development and review.

A future distributed deployment may separate inference, ingestion,
orchestration, enrichment, telemetry, and verification across hosts.

## Deterministic policy

Operational authorization belongs to deterministic policy.

LLM confidence, LLM consensus, model voting, historical assertions, or
external textual instructions do not replace that policy.

## Writeback

Writeback adapters are capabilities. They should eventually receive
policy-authorized action objects rather than free-form LLM output.

## Development autonomy

```text
repository
  -> audit
  -> LLM engineering
  -> tests/implementation
  -> deterministic verification
  -> Pi/Bandit
  -> canary
  -> Git
  -> repeat
```

## Experimental component

`engine/slm_triage_worker.py` is experimental/isolated until its role in the
end-to-end operational path is demonstrated.

## Architectural authority

Current authority:

- this document
- `docs/CURRENT_RUNTIME_MAP.md`
- `docs/DEVELOPMENT_AUTONOMY.md`
- `docs/SECURITY_MODEL.md`
- ADRs under `docs/adr/`

Historical documents are not architectural authority.
