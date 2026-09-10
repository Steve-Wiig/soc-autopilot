from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json

from engine.canonical_envelope import EventEnvelope
from engine.deterministic_dedup import cluster_alerts, generate_alert_signature

def _make_envelope(src_ip: str, rule_id: str, minutes_ago: int = 0):
    raw = {"src_ip": src_ip, "rule": {"id": rule_id}, "action": "alert"}
    raw_hash = hashlib.sha256(json.dumps(raw).encode()).hexdigest()

    return EventEnvelope(
        source="eve",
        collector_version="1.0.0",
        transform_version="1.0.0",
        original_payload_hash=raw_hash,
        normalized_payload_hash=raw_hash,
        payload=raw,
        received_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    )

def test_identical_alerts_cluster_together():
    # 5 identical port scans
    alerts = [_make_envelope("10.0.0.5", "2001", minutes_ago=i) for i in range(5)]
    # 1 different alert
    alerts.append(_make_envelope("192.168.1.1", "4004"))

    clusters = cluster_alerts(alerts)

    assert len(clusters) == 2

    # Find the port scan cluster
    scan_cluster = next(c for c in clusters if c.event_count == 5)
    assert scan_cluster.events.__len__() == 5

    # Find the single alert
    single_cluster = next(c for c in clusters if c.event_count == 1)
    assert single_cluster.events.__len__() == 1

def test_timestamps_do_not_break_clustering():
    a1 = _make_envelope("10.0.0.5", "2001", minutes_ago=10)
    a2 = _make_envelope("10.0.0.5", "2001", minutes_ago=0)

    sig1 = generate_alert_signature(a1)
    sig2 = generate_alert_signature(a2)

    # Timestamps are ignored in the signature
    assert sig1 == sig2
