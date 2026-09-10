"""
Demonstrates the Noise Crusher handling a massive brute-force attack.
"""
from __future__ import annotations
import hashlib
import json
from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.deterministic_dedup import cluster_alerts
from engine.investigation_controller import run_investigation

def process_burst(num_alerts: int):
    print(f"\n* * * SIMULATING BRUTE FORCE ATTACK ({num_alerts} ALERTS) * * *")

    envelopes = []
    for i in range(num_alerts):
        raw_json = {
            "timestamp": f"2026-09-08T14:35:{i:02d}Z",
            "src_ip": "192.168.1.100",
            "dest_ip": "10.0.0.10",
            "rule": {"id": "5710", "msg": "sshd: Attempt to login using a non-existing user"},
            "data": {"dstuser": "root"},
            "action": "alert"
        }
        raw_hash = hashlib.sha256(json.dumps(raw_json, sort_keys=True).encode()).hexdigest()
        envelopes.append(EventEnvelope(
            source="wazuh",
            collector_version="1.0.0",
            transform_version="1.0.0",
            original_payload_hash=raw_hash,
            normalized_payload_hash=raw_hash,
            payload=raw_json,
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
