from engine.telemetry_identity import deduplicate_events


def test_duplicate_inference_events_removed():

    event = {
        "event_type": "inference_attempt",
        "provider": "android_qwen",
        "role": "coder",
        "attempt_num": 1,
        "timestamp": "2026-09-06T00:00:00",
        "success": True,
    }

    assert len(
        deduplicate_events([event, event.copy()])
    ) == 1


def test_duplicate_remediation_events_removed():

    event = {
        "remediation_id": "abc",
        "ts": "2026-09-06T00:00:00",
        "target_file": "test.py",
        "stage": "generation",
        "attempt_num": 1,
    }

    assert len(
        deduplicate_events([event, event.copy()])
    ) == 1
