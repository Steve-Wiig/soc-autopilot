"""
Tests for Telemetry Security Boundary and Policy Binding.
"""
import pytest
from datetime import datetime, timezone
from uuid import uuid4
from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.soc_pipeline import SOCPipeline
from engine.deterministic_policy import PolicyEnvelope, evaluate_deterministic_policy
from engine.audit_telemetry import AuditTelemetryWriter, MandatoryTelemetryFailure

def _make_envelope(src_ip="1.1.1.1", timestamp=None) -> EventEnvelope:
    if not timestamp: timestamp = datetime.now(timezone.utc)
    return EventEnvelope(
        source="wazuh", collector_version="1.0", transform_version="1.0",
        original_payload_hash="abc", normalized_payload_hash="def",
        trust_labels=TrustLabels(),
        payload={"rule": {"id": "500", "description": "Test"}, "src_ip": src_ip},
        received_at=timestamp, event_id=uuid4()
    )

def test_policy_allows_safe_actions():
    envelope = PolicyEnvelope(
        incident_id="test-1", model_recommendation="NO_ACTION",
        model_severity="LOW", model_confidence=0.95, requires_human_review=False
    )
    decision = evaluate_deterministic_policy(envelope, authoritative_trusted_source=True)
    assert decision.authorized_action == "NO_ACTION"
    assert decision.incident_id == "test-1"
    assert decision.decision_id is not None  # Proves unique binding

def test_policy_fails_closed_on_high_severity():
    envelope = PolicyEnvelope(
        incident_id="test-2", model_recommendation="NO_ACTION",
        model_severity="HIGH", model_confidence=0.95, requires_human_review=False
    )
    decision = evaluate_deterministic_policy(envelope, authoritative_trusted_source=True)
    assert decision.authorized_action == "REVIEW_REQUIRED"
    assert "severity=HIGH" in decision.decision_reason

def test_policy_blocks_high_impact_actions():
    envelope = PolicyEnvelope(
        incident_id="test-3", model_recommendation="ISOLATE",
        model_severity="LOW", model_confidence=0.99, requires_human_review=False
    )
    decision = evaluate_deterministic_policy(envelope, authoritative_trusted_source=True)
    assert decision.authorized_action == "REVIEW_REQUIRED"
    assert "requires human authorization" in decision.decision_reason

def test_telemetry_failure_forces_fail_closed():
    """If mandatory telemetry fails, the pipeline must return REVIEW_REQUIRED."""
    pipeline = SOCPipeline()
    env = _make_envelope(src_ip="10.0.0.5")
    
    # Inject a flag to simulate telemetry failure in the mock writer
    # We do this by patching the log_mandatory_event to raise
    original_log = pipeline.telemetry.log_mandatory_event
    def failing_log(event_type, payload):
        payload["_simulate_telemetry_failure"] = True
        original_log(event_type, payload)
    
    pipeline.telemetry.log_mandatory_event = failing_log
    
    results = pipeline.process_alerts([env])
    assert len(results) == 1
    incident, decision, _ = results[0]
    
    assert decision.authorized_action == "REVIEW_REQUIRED"
    assert "MANDATORY TELEMETRY FAILURE" in decision.decision_reason

def test_policy_decision_is_uniquely_bound():
    """Two evaluations of the same input must produce different decision_ids."""
    envelope = PolicyEnvelope(
        incident_id="test-4", model_recommendation="ENRICH",
        model_severity="LOW", model_confidence=0.95, requires_human_review=False
    )
    decision1 = evaluate_deterministic_policy(envelope)
    decision2 = evaluate_deterministic_policy(envelope)
    
    assert decision1.decision_id != decision2.decision_id
    assert decision1.incident_id == decision2.incident_id
