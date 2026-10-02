"""
Demonstrates the Noise Crusher handling a massive brute-force attack.

This script simulates a burst of near-identical SSH brute-force alerts
being ingested from WAZUH, shows how the deterministic dedup layer
collapses them into a small number of investigation clusters, and then
runs each cluster through the investigation controller to observe the
resulting hypothesis, simulated remediation action, and policy decision.
"""
from __future__ import annotations

import hashlib
import json
from typing import List

from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.deterministic_dedup import cluster_alerts
from engine.investigation_controller import run_investigation


# Simulated attack characteristics (kept identical across the burst so the
# dedup layer has something meaningful to collapse).
SOURCE_IP = "192.168.1.100"
DEST_IP = "10.0.0.10"
WAZUH_RULE_ID = "5710"
WAZUH_RULE_MESSAGE = "sshd: Attempt to login using a non-existing user"
TARGET_USER = "root"
ALERT_ACTION = "alert"

# Envelope/collector metadata for the simulated ingestion source.
ENVELOPE_SOURCE = "wazuh"
COLLECTOR_VERSION = "1.0.0"
TRANSFORM_VERSION = "1.0.0"


def process_burst(num_alerts: int) -> None:
    """Simulate a burst of brute-force alerts and run them through the pipeline.

    Builds ``num_alerts`` near-duplicate SSH brute-force alert envelopes,
    feeds them through deterministic dedup to collapse them into
    investigation clusters, and then runs each resulting cluster through
    the investigation controller, printing the intake, dedup, brain,
    executor, and policy outcomes along the way.

    Args:
        num_alerts: The number of raw alerts to simulate in the burst.
    """
    print(f"\n* * * SIMULATING BRUTE FORCE ATTACK ({num_alerts} ALERTS) * * *")

    envelopes: List[EventEnvelope] = []
    for alert_index in range(num_alerts):
        alert_payload = {
            "timestamp": f"2026-09-08T14:35:{alert_index:02d}Z",
            "src_ip": SOURCE_IP,
            "dest_ip": DEST_IP,
            "rule": {"id": WAZUH_RULE_ID, "msg": WAZUH_RULE_MESSAGE},
            "data": {"dstuser": TARGET_USER},
            "action": ALERT_ACTION,
        }
        payload_hash = hashlib.sha256(
            json.dumps(alert_payload, sort_keys=True).encode()
        ).hexdigest()
        envelopes.append(EventEnvelope(
            source=ENVELOPE_SOURCE,
            collector_version=COLLECTOR_VERSION,
            transform_version=TRANSFORM_VERSION,
            original_payload_hash=payload_hash,
            normalized_payload_hash=payload_hash,
            payload=alert_payload,
            trust_labels=TrustLabels(sanitized=True, untrusted_content=True)
        ))

    print(f"  [INTAKE]  Received {len(envelopes)} raw alerts from WAZUH.")

    clusters = cluster_alerts(envelopes)
    print(f"  [DEDUP]   CRUSHED NOISE: {len(envelopes)} alerts collapsed into {len(clusters)} investigation cluster(s).")
    print(f"            Saved {len(envelopes) - len(clusters)} expensive LLM investigations!\n")

    for cluster in clusters:
        print(f"  [BRAIN]   Investigating cluster with {cluster.event_count} events...")
        ctx = run_investigation(cluster)

        print(f"  [BRAIN]   Final Hypothesis: {ctx.hypotheses[-1]}")

        if ctx.simulation_result:
            print(f"  [EXECUTOR] DRY RUN: {ctx.simulation_result.action_type.upper()} target={ctx.simulation_result.target_id}")
            print(f"  [EXECUTOR] Rollback: {ctx.simulation_result.rollback_plan}")
            print(f"  [EXECUTOR] Live Mutation: {ctx.simulation_result.live_mutation}")

            if ctx.simulation_result.affected_critical_services > 0:
                print(f"  [POLICY]  DECISION: REVIEW_REQUIRED")
            else:
                print(f"  [POLICY]  DECISION: ALLOW")

    print(f"\n* * * SPINE STRESS TEST COMPLETE * * *\n")


if __name__ == "__main__":
    process_burst(50)
