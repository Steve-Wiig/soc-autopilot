import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.correlation_engine import CorrelationState

def _make_envelope(src_ip=None, dst_ip=None, hostname=None, rule_id="500", timestamp=None, event_id=None) -> EventEnvelope:
    if not timestamp: timestamp = datetime.now(timezone.utc)
    if not event_id: event_id = uuid4()
    payload = {"rule": {"id": rule_id, "description": "Suspicious Activity"}}
    if src_ip: payload["src_ip"] = src_ip
    if dst_ip: payload["dst_ip"] = dst_ip
    if hostname: payload["hostname"] = hostname
    return EventEnvelope(
        source="wazuh", collector_version="1.0", transform_version="1.0",
        original_payload_hash="abc", normalized_payload_hash="def",
        trust_labels=TrustLabels(),
        payload=payload,
        received_at=timestamp, event_id=event_id
    )

def test_transitive_correlation():
    """A shares dst_ip with B. B shares src_ip with C. A and C do NOT directly overlap.
    The engine accumulates entities into the incident, so C matches on B's entity."""
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    env_a = _make_envelope(src_ip="1.1.1.1", dst_ip="2.2.2.2", timestamp=t1)
    env_b = _make_envelope(src_ip="2.2.2.2", dst_ip="3.3.3.3", timestamp=t1 + timedelta(seconds=10))
    env_c = _make_envelope(src_ip="3.3.3.3", timestamp=t1 + timedelta(seconds=20))

    state.add_events([env_a])
    state.add_events([env_b])
    state.add_events([env_c])
    incidents = state.add_events([])
    assert len(incidents) == 1, f"Expected 1 incident, got {len(incidents)}"
    assert len(incidents[0].alerts) == 3
    # Verify all 3 IPs are in the incident's entity set (proves transitive accumulation)
    ips = set(incidents[0].entities.ips)
    assert ips == {"1.1.1.1", "2.2.2.2", "3.3.3.3"}, f"Expected all 3 IPs, got {ips}"

def test_transitive_correlation_merge():
    """Two independent incidents that later share an entity must merge."""
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    # Incident 1: A only has 1.1.1.1
    env_a = _make_envelope(src_ip="1.1.1.1", timestamp=t1)
    # Incident 2: B only has 2.2.2.2
    env_b = _make_envelope(src_ip="2.2.2.2", timestamp=t1 + timedelta(seconds=10))
    # Bridge: C has BOTH 1.1.1.1 and 2.2.2.2, forcing the two incidents to merge
    env_c = _make_envelope(src_ip="1.1.1.1", dst_ip="2.2.2.2", timestamp=t1 + timedelta(seconds=20))

    state.add_events([env_a])
    state.add_events([env_b])
    state.add_events([env_c])
    incidents = state.add_events([])
    assert len(incidents) == 1, f"Expected 1 incident after merge, got {len(incidents)}"
    assert len(incidents[0].alerts) == 3
    reasons = incidents[0].correlation_reasons
    assert any("Merged incident" in r for r in reasons), f"Expected merge reason, got: {reasons}"

def test_out_of_order_alerts():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    env_c = _make_envelope(src_ip="3.3.3.3", timestamp=t1 + timedelta(minutes=5))
    env_a = _make_envelope(src_ip="3.3.3.3", timestamp=t1)
    state.add_events([env_c])
    state.add_events([env_a])
    incidents = state.add_events([])
    assert len(incidents) == 1
    assert len(incidents[0].alerts) == 2

def test_expired_incidents():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc) - timedelta(hours=3)
    env_old = _make_envelope(src_ip="4.4.4.4", timestamp=t1)
    state.add_events([env_old])
    incidents = state.add_events([])
    assert len(incidents) == 0

def test_max_incident_size():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    events = [_make_envelope(src_ip="5.5.5.5", timestamp=t1 + timedelta(seconds=i)) for i in range(55)]
    state.add_events(events)
    incidents = state.add_events([])
    assert len(incidents) == 2
    assert len(incidents[0].alerts) == 50
    assert len(incidents[1].alerts) == 5

def test_unrelated_alerts():
    state = CorrelationState()
    t1 = datetime.now(timezone.utc)
    env_a = _make_envelope(src_ip="6.6.6.6", timestamp=t1)
    env_b = _make_envelope(src_ip="7.7.7.7", timestamp=t1)
    state.add_events([env_a, env_b])
    incidents = state.add_events([])
    assert len(incidents) == 2
