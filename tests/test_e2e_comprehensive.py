"""
Comprehensive End-to-End Adversarial Test Suite.
Proves the complete 12-stage boundary: alert -> correlation -> context -> enrichment -> 
bounded model context -> LLM recommendation -> schema validation -> deterministic policy -> 
authorization -> bounded action -> writeback -> audit telemetry.
"""
import pytest
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.soc_pipeline import SOCPipeline
from engine.deterministic_policy import PolicyEnvelope, evaluate_deterministic_policy, PolicyDecision
from contracts.slm_recommendation import SLMRawRecommendation
from engine.audit_telemetry import MandatoryTelemetryFailure

def _make_envelope(src_ip="1.1.1.1", dst_ip=None, timestamp=None, event_id=None) -> EventEnvelope:
    if not timestamp: timestamp = datetime.now(timezone.utc)
    if not event_id: event_id = uuid4()
    payload = {"rule": {"id": "500", "description": "Test Alert"}}
    if src_ip: payload["src_ip"] = src_ip
    if dst_ip: payload["dst_ip"] = dst_ip
    return EventEnvelope(
        source="wazuh", collector_version="1.0", transform_version="1.0",
        original_payload_hash="abc", normalized_payload_hash="def",
        trust_labels=TrustLabels(),
        payload=payload,
        received_at=timestamp, event_id=event_id
    )

def test_e2e_happy_path_full_boundary():
    """Proves the complete successful flow from alert to writeback with full telemetry."""
    pipeline = SOCPipeline()
    env = _make_envelope(src_ip="192.168.1.100")
    
    results = pipeline.process_alerts([env])
    assert len(results) == 1
    incident, decision, writeback_result = results[0]
    
    # 1. Correlation worked
    assert len(incident.alerts) == 1
    # 2. Enrichment occurred
    assert len(incident.enrichment) > 0
    # 3. Bounded context generated
    assert "### SYSTEM INSTRUCTIONS" in incident.model_context
    assert "### UNTRUSTED EXTERNAL EVIDENCE" in incident.model_context
    # 4. Policy evaluated
    assert decision.authorized_action in ["ESCALATE", "REVIEW_REQUIRED"]
    # 5. Writeback executed or safely handled
    assert "CASE-" in writeback_result or "REVIEW_REQUIRED" in writeback_result
    # 6. Telemetry recorded (check mock storage)
    events = [r["event_type"] for r in pipeline.telemetry._mock_storage]
    assert "correlation_complete" in events
    assert "enrichment_complete" in events
    assert "policy_decision" in events
    assert "authorization_created" in events or "writeback_skipped" in events

def test_e2e_malformed_llm_response_fails_closed():
    """If the LLM returns unparseable output, the pipeline must fail closed."""
    pipeline = SOCPipeline()
    env = _make_envelope(src_ip="10.0.0.5")
    
    # Simulate LLM parsing failure
    results = pipeline.process_alerts([env], mock_llm_override={"raise_parse_error": True})
    
    incident, decision, writeback_result = results[0]
    assert decision.authorized_action == "REVIEW_REQUIRED"
    assert "PIPELINE ERROR" in decision.decision_reason or "MANDATORY TELEMETRY" in decision.decision_reason
    assert "FAIL_CLOSED" in writeback_result

def test_e2e_unknown_llm_action_fails_closed():
    """If the LLM recommends an unknown/unsupported action, policy must fail closed."""
    pipeline = SOCPipeline()
    env = _make_envelope(src_ip="10.0.0.5")
    
    # Simulate LLM recommending an invalid action
    results = pipeline.process_alerts([env], mock_llm_override={
        "recommendation": "DELETE_SYSTEM32",
        "severity": "LOW",
        "confidence": 0.99
    })
    
    incident, decision, writeback_result = results[0]
    # Policy should reject unknown actions and force review
    assert decision.authorized_action == "REVIEW_REQUIRED"
    assert "unrecognized recommendation" in decision.decision_reason

def test_e2e_extra_model_fields_rejected():
    """Proves that Pydantic strict validation rejects extra fields injected by the model."""
    from contracts.slm_recommendation import Classification, Severity, RecommendedAction

    valid_payload = {
        "schema_version": "1.0",
        "classification": Classification.BENIGN,
        "confidence": 0.9,
        "severity": Severity.LOW,
        "recommended_action": RecommendedAction.NO_ACTION,
        "reasoning_summary": "This is a valid reasoning summary.",
        "indicators": [],
        "evidence_refs": [],
        "requires_human_review": False
    }

    # Valid payload should parse
    SLMRawRecommendation.model_validate(valid_payload)

    # Payload with extra injected field should FAIL
    invalid_payload = valid_payload.copy()
    invalid_payload["system_override"] = "BYPASS_POLICY"

    with pytest.raises(Exception):  # Pydantic ValidationError
        SLMRawRecommendation.model_validate(invalid_payload)


def test_e2e_malicious_enrichment_encapsulated():
    """Malicious enrichment data is preserved as evidence but does not break the pipeline."""
    pipeline = SOCPipeline()
    # 10.0.0.5 is our mock IP that returns prompt injection payloads
    env = _make_envelope(src_ip="10.0.0.5")
    
    results = pipeline.process_alerts([env])
    incident, decision, writeback_result = results[0]
    
    # Pipeline must not crash
    assert decision is not None
    # Injection payload must be present in the context
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in incident.model_context
    # But it must be clearly labeled as untrusted
    assert "### UNTRUSTED EXTERNAL EVIDENCE" in incident.model_context
    assert "UNTRUSTED_EXTERNAL" in incident.model_context

def test_e2e_duplicate_alerts_handled():
    """Submitting the exact same alert twice should not create duplicate incidents."""
    pipeline = SOCPipeline()
    t1 = datetime.now(timezone.utc)
    eid = uuid4()
    
    env1 = _make_envelope(src_ip="1.1.1.1", timestamp=t1, event_id=eid)
    env2 = _make_envelope(src_ip="1.1.1.1", timestamp=t1, event_id=eid) # Exact duplicate
    
    results = pipeline.process_alerts([env1, env2])
    
    # Should only result in 1 incident containing 1 alert (deduped) or 1 incident with 1 alert 
    # depending on exact dedup logic, but definitely not 2 separate incidents for the same event_id
    assert len(results) == 1
    assert len(results[0][0].alerts) == 1

def test_e2e_telemetry_failure_forces_review():
    """If telemetry fails at any point, the entire decision must be REVIEW_REQUIRED."""
    pipeline = SOCPipeline()
    env = _make_envelope(src_ip="1.1.1.1")
    
    # Force telemetry to fail
    original_log = pipeline.telemetry.log_mandatory_event
    def failing_log(event_type, payload):
        payload["_simulate_telemetry_failure"] = True
        original_log(event_type, payload)
    
    pipeline.telemetry.log_mandatory_event = failing_log
    
    results = pipeline.process_alerts([env])
    incident, decision, writeback_result = results[0]
    
    assert decision.authorized_action == "REVIEW_REQUIRED"
    assert "MANDATORY TELEMETRY FAILURE" in decision.decision_reason
    assert writeback_result == "TELEMETRY_FAIL_CLOSED"

def test_e2e_out_of_order_correlation():
    """Alerts arriving out of chronological order must still correlate correctly."""
    pipeline = SOCPipeline()
    t1 = datetime.now(timezone.utc)
    
    # Alert 2 arrives first (later timestamp)
    env2 = _make_envelope(src_ip="2.2.2.2", dst_ip="3.3.3.3", timestamp=t1 + timedelta(minutes=5))
    # Alert 1 arrives second (earlier timestamp)
    env1 = _make_envelope(src_ip="1.1.1.1", dst_ip="2.2.2.2", timestamp=t1)
    
    results = pipeline.process_alerts([env2, env1])
    
    # Should correlate into 1 incident due to transitive overlap (2.2.2.2)
    assert len(results) == 1
    assert len(results[0][0].alerts) == 2
