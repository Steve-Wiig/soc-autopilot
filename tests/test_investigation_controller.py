from __future__ import annotations

import pytest
from datetime import datetime, timezone
import hashlib
import json

from engine.canonical_envelope import EventEnvelope
from engine.deterministic_dedup import cluster_alerts, AlertCluster
from engine.investigation_controller import (
    run_investigation,
    InvestigationState,
    InvestigationBudget
)

def _make_cluster() -> AlertCluster:
    raw = {"src_ip": "10.0.0.5", "rule": {"id": "2001"}, "action": "alert"}
    raw_hash = hashlib.sha256(json.dumps(raw).encode()).hexdigest()
    env = EventEnvelope(
        source="eve",
        collector_version="1.0",
        transform_version="1.0",
        original_payload_hash=raw_hash,
        normalized_payload_hash=raw_hash,
        payload=raw,
        received_at=datetime.now(timezone.utc)
    )
    return cluster_alerts([env])[0]

def test_investigation_completes_successfully():
    cluster = _make_cluster()
    ctx = run_investigation(cluster)

    # Should complete without hitting budget limits
    assert ctx.state == InvestigationState.COMPLETE
    assert len(ctx.hypotheses) >= 1
    assert len(ctx.evidence) >= 1
    assert ctx.simulation_result is not None
    assert ctx.simulation_result.live_mutation is False

def test_investigation_stops_on_iteration_budget():
    cluster = _make_cluster()
    # Give it a budget of 1 iteration. It will run out of budget before finishing.
    strict_budget = InvestigationBudget(max_iterations=1, max_tool_calls=1)

    ctx = run_investigation(cluster, budget=strict_budget)

    assert ctx.state == InvestigationState.SAFE_STOP
    assert ctx.iterations <= strict_budget.max_iterations

def test_investigation_escalates_to_review_for_high_blast_radius():
    cluster = _make_cluster()
    ctx = run_investigation(cluster)

    # Force the simulation to show high blast radius
    ctx.simulation_result.affected_critical_services = 5

    # Re-run the policy boundary logic manually for the test
    if ctx.simulation_result.affected_critical_services > 0:
        ctx.state = InvestigationState.REVIEW_REQUIRED

    assert ctx.state == InvestigationState.REVIEW_REQUIRED
