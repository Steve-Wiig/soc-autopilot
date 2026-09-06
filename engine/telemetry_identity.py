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
