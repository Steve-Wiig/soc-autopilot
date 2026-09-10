# Operations Runbook

## Scope

This runbook describes the current evidence-driven operating model for
SOC-Autopilot development and runtime investigation.

It does not reproduce historical deployment manifests, old service schedules,
or speculative production capacities.

## First rule: inspect before acting

Before treating a component as operationally authoritative, establish:

1. who calls it;
2. what enters it;
3. what it emits;
4. what state it persists;
5. who consumes its output;
6. what side effects it can perform.

A file existing in the repository is not evidence that it is on the production
path.

## Baseline verification

From repository root:

```bash
./.venv/bin/python -m pytest tests/ -q
git diff --check
git status --short
```

The documentation checkpoint that preceded this pass recorded 338 passing tests.

## Runtime investigation order

```text
source
  -> queue
  -> worker
  -> model endpoint
  -> result storage
  -> downstream consumer
  -> policy
  -> writeback
```

Capture the observed call chain before making architecture claims.

## SLM triage worker

`engine/slm_triage_worker.py` is currently classified **EXPERIMENTAL / ISOLATED**.

Verify its queue contract, SLM endpoint, verdict schema, persistent state, and
downstream consumers before wiring additional operational behavior around it.

## Model routing

Development may use cloud providers.

Production SOC inference is intended to remain local/edge and should have an
explicit deterministic enforcement boundary preventing accidental cloud
fallback.

## Writeback discipline

Writeback should consume a bounded, schema-validated, policy-authorized action
object rather than arbitrary model text.

```text
model proposal
   -> schema validation
   -> deterministic policy
   -> approval where required
   -> bounded executor
```

## Raspberry Pi

Treat Pi/Bandit results as independent development verification evidence.
They do not replace the runtime policy authority.

## Runtime state and Git

The following are local operational artifacts and are intentionally excluded
from Git:

```text
/runtime/
/docs/archive/
/.env
```

Documentation rebuild backups belong in temporary local storage rather than the
repository history.

## Emergency principle

When a subsystem's authority is uncertain, avoid consequential changes until
its actual call chain and side effects are established.
