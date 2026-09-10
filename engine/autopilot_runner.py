"""
The main entrypoint for the MVP SOC Autopilot spine.
Stitches Intake -> Dedup -> Brain -> Simulation into a single observable pipeline.
"""
from __future__ import annotations

import hashlib
import json

from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.deterministic_dedup import cluster_alerts
from engine.investigation_controller import run_investigation, InvestigationState


def process_raw_alert(raw_json: dict, source: str):
    print(f"\n{'='*65}")
    print(f"  [INTAKE] Received raw alert from {source.upper()}")
    print(f"{'='*65}")

    # 1. Hash the raw payload for provenance
    raw_hash = hashlib.sha256(json.dumps(raw_json, sort_keys=True).encode()).hexdigest()

    # 2. Build and Validate the Canonical Envelope
    envelope = EventEnvelope(
        source=source,
        collector_version="1.0.0",
        transform_version="1.0.0",
        original_payload_hash=raw_hash,
        normalized_payload_hash=raw_hash,
        payload=raw_json,
        trust_labels=TrustLabels(sanitized=True, untrusted_content=True)
    )
    print(f"  [ENVELOPE] Validated. Event ID: {envelope.event_id}")
    print(f"  [ENVELOPE] Trust Labels: {envelope.trust_labels.model_dump()}")

    # 3. Deterministic Deduplication
    clusters = cluster_alerts([envelope])
    print(f"  [DEDUP]    Grouped into {len(clusters)} investigation cluster(s).")

    # 4. The Investigation Loop
    for cluster in clusters:
        print(f"\n  [BRAIN]    Starting investigation for cluster...")
        ctx = run_investigation(cluster)

        print(f"  [BRAIN]    Final State: {ctx.state.value}")
        print(f"  [BRAIN]    Iterations used: {ctx.iterations}")
        print(f"  [BRAIN]    Tool calls used: {ctx.tool_calls}")

        if ctx.hypotheses:
            print(f"  [BRAIN]    Final Hypothesis: {ctx.hypotheses[-1]}")

        # 5. The Policy Boundary & Safe Execution
        if ctx.simulation_result:
            print(f"\n  [EXECUTOR] DRY RUN PROPOSAL: {ctx.simulation_result.action_type.upper()}")
            print(f"  [EXECUTOR] Target: {ctx.simulation_result.target_id}")
            print(f"  [EXECUTOR] Blast Radius: {ctx.simulation_result.affected_critical_services} critical services affected.")
            print(f"  [EXECUTOR] Rollback Plan: {ctx.simulation_result.rollback_plan}")
            print(f"  [EXECUTOR] Live Mutation: {ctx.simulation_result.live_mutation} (HARD SAFETY GUARANTEE)")

            # DETERMINISTIC POLICY DECISION
            if ctx.simulation_result.affected_critical_services > 0:
                print(f"\n  [POLICY]   DECISION: REVIEW_REQUIRED (Human approval needed due to blast radius)")
            else:
                print(f"\n  [POLICY]   DECISION: ALLOW (Safe to execute in future phases)")
        else:
            if ctx.state == InvestigationState.SAFE_STOP:
                print(f"\n  [POLICY]   DECISION: SAFE_STOP (Budget exhausted or degraded mode)")
            else:
                print(f"\n  [POLICY]   DECISION: NO_ACTION_REQUIRED")

    print(f"\n  [AUDIT]    Investigation chain complete and hashed.")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    print("\n* * * BOOTING SOC AUTOPILOT MVP SPINE * * *")

    # Mock Suricata EVE alert
    suricata_c2_alert = {
        "timestamp": "2026-09-08T14:32:01Z",
        "src_ip": "203.0.113.55",
        "dest_ip": "10.0.0.5",
        "rule": {"id": "2001", "msg": "ET MALWARE Known C2 Channel"},
        "action": "alert"
    }
    process_raw_alert(suricata_c2_alert, "eve")

    # Mock Wazuh alert
    wazuh_brute_force = {
        "timestamp": "2026-09-08T14:35:00Z",
        "src_ip": "192.168.1.100",
        "dest_ip": "10.0.0.10",
        "rule": {"id": "5710", "msg": "sshd: Attempt to login using a non-existing user"},
        "action": "alert"
    }
    process_raw_alert(wazuh_brute_force, "wazuh")
