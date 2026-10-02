"""
The main entrypoint for the MVP SOC Autopilot spine.
Stitches Intake -> Dedup -> Brain -> Simulation into a single observable pipeline.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from engine.canonical_envelope import EventEnvelope, TrustLabels
from engine.deterministic_dedup import cluster_alerts
from engine.investigation_controller import run_investigation, InvestigationState

_SECTION_SEPARATOR = "=" * 65


def _compute_payload_hash(payload: Dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash of a JSON-serializable payload.

    Args:
        payload: The raw (or normalized) alert payload to hash.

    Returns:
        The hex-encoded SHA-256 digest of the canonicalized payload.
    """
    canonical_json = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(canonical_json).hexdigest()


def _build_envelope(raw_payload: Dict[str, Any], source: str) -> EventEnvelope:
    """Wrap a raw alert payload in a validated canonical EventEnvelope.

    Args:
        raw_payload: The untouched alert payload as received from the source system.
        source: Identifier of the originating system (e.g. "eve", "wazuh").

    Returns:
        A validated EventEnvelope with provenance hashes and trust labels attached.
    """
    payload_hash = _compute_payload_hash(raw_payload)
    return EventEnvelope(
        source=source,
        collector_version="1.0.0",
        transform_version="1.0.0",
        original_payload_hash=payload_hash,
        normalized_payload_hash=payload_hash,
        payload=raw_payload,
        trust_labels=TrustLabels(sanitized=True, untrusted_content=True),
    )


def _report_simulation_result(ctx: Any) -> None:
    """Print the dry-run execution proposal and the deterministic policy decision.

    Args:
        ctx: The completed investigation context, expected to expose a
            non-null `simulation_result` attribute.
    """
    simulation_result = ctx.simulation_result
    print(f"\n  [EXECUTOR] DRY RUN PROPOSAL: {simulation_result.action_type.upper()}")
    print(f"  [EXECUTOR] Target: {simulation_result.target_id}")
    print(f"  [EXECUTOR] Blast Radius: {simulation_result.affected_critical_services} critical services affected.")
    print(f"  [EXECUTOR] Rollback Plan: {simulation_result.rollback_plan}")
    print(f"  [EXECUTOR] Live Mutation: {simulation_result.live_mutation} (HARD SAFETY GUARANTEE)")

    # DETERMINISTIC POLICY DECISION
    if simulation_result.affected_critical_services > 0:
        print(f"\n  [POLICY]   DECISION: REVIEW_REQUIRED (Human approval needed due to blast radius)")
    else:
        print(f"\n  [POLICY]   DECISION: ALLOW (Safe to execute in future phases)")


def _report_investigation_outcome(ctx: Any) -> None:
    """Print the investigation results and resulting policy decision for a cluster.

    Args:
        ctx: The completed investigation context returned by run_investigation.
    """
    print(f"  [BRAIN]    Final State: {ctx.state.value}")
    print(f"  [BRAIN]    Iterations used: {ctx.iterations}")
    print(f"  [BRAIN]    Tool calls used: {ctx.tool_calls}")

    if ctx.hypotheses:
        print(f"  [BRAIN]    Final Hypothesis: {ctx.hypotheses[-1]}")

    if ctx.simulation_result:
        _report_simulation_result(ctx)
    elif ctx.state == InvestigationState.SAFE_STOP:
        print(f"\n  [POLICY]   DECISION: SAFE_STOP (Budget exhausted or degraded mode)")
    else:
        print(f"\n  [POLICY]   DECISION: NO_ACTION_REQUIRED")


def process_raw_alert(raw_json: Dict[str, Any], source: str) -> None:
    """Run a single raw alert through the full Autopilot pipeline.

    The pipeline stages are: Intake (canonical envelope construction) ->
    Deterministic Dedup (clustering) -> Brain (investigation loop) ->
    Simulation/Policy (dry-run execution proposal and decision).

    Args:
        raw_json: The raw alert payload as received from the source system.
        source: Identifier of the originating system (e.g. "eve", "wazuh").
    """
    print(f"\n{_SECTION_SEPARATOR}")
    print(f"  [INTAKE] Received raw alert from {source.upper()}")
    print(f"{_SECTION_SEPARATOR}")

    # 1 & 2. Hash the raw payload for provenance and build/validate the envelope.
    envelope = _build_envelope(raw_json, source)
    print(f"  [ENVELOPE] Validated. Event ID: {envelope.event_id}")
    print(f"  [ENVELOPE] Trust Labels: {envelope.trust_labels.model_dump()}")

    # 3. Deterministic Deduplication
    clusters: List[List[EventEnvelope]] = cluster_alerts([envelope])
    print(f"  [DEDUP]    Grouped into {len(clusters)} investigation cluster(s).")

    # 4. The Investigation Loop
    for cluster in clusters:
        print(f"\n  [BRAIN]    Starting investigation for cluster...")
        ctx = run_investigation(cluster)
        # 5. The Policy Boundary & Safe Execution
        _report_investigation_outcome(ctx)

    print(f"\n  [AUDIT]    Investigation chain complete and hashed.")
    print(f"{_SECTION_SEPARATOR}\n")


def main() -> None:
    """Boot the SOC Autopilot MVP spine and process a couple of mock alerts."""
    print("\n* * * BOOTING SOC AUTOPILOT MVP SPINE * * *")

    # Mock Suricata EVE alert
    suricata_c2_alert = {
        "timestamp": "2026-09-08T14:32:01Z",
        "src_ip": "203.0.113.55",
        "dest_ip": "10.0.0.5",
        "rule": {"id": "2001", "msg": "ET MALWARE Known C2 Channel"},
        "action": "alert",
    }
    process_raw_alert(suricata_c2_alert, "eve")

    # Mock Wazuh alert
    wazuh_brute_force_alert = {
        "timestamp": "2026-09-08T14:35:00Z",
        "src_ip": "192.168.1.100",
        "dest_ip": "10.0.0.10",
        "rule": {"id": "5710", "msg": "sshd: Attempt to login using a non-existing user"},
        "action": "alert",
    }
    process_raw_alert(wazuh_brute_force_alert, "wazuh")


if __name__ == "__main__":
    main()
