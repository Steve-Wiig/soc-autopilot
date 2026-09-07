"""
Canonical telemetry event identity.

All telemetry consumers should use this module
for duplicate detection.
"""


def event_identity(event: dict):

    if event.get("event_type") == "inference_attempt":
        return (
            "inference",
            event.get("provider"),
            event.get("role"),
            event.get("attempt_num"),
            event.get("timestamp") or event.get("ts"),
            event.get("success"),
            event.get("failure_class"),
        )

    # Pi Edge Telemetry (Static Analysis, Bandit, Heartbeats)
    elif event.get("event_type") in ("static_analysis_result", "bandit_inference", "pi_heartbeat", "test_event"):
        return (
            "pi_edge",
            event.get("event_type"),
            event.get("source") or event.get("node_id") or "raspberry_pi",
            event.get("event_id") or event.get("timestamp") or event.get("created_at"),
        )
    return (
        "remediation",
        event.get("remediation_id"),
        event.get("ts"),
        event.get("target_file"),
        event.get("stage"),
        event.get("attempt_num"),
    )


def deduplicate_events(events):

    seen = set()
    output = []

    for event in events:
        identity = event_identity(event)

        if identity in seen:
            continue

        seen.add(identity)
        output.append(event)

    return output
