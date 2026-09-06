import json
from pathlib import Path
from unittest.mock import patch

import tools.telemetry_report as report


def test_inference_events_do_not_collide_during_dedup(tmp_path):

    events = [
        {
            "event_type": "inference_attempt",
            "provider": "android_qwen",
            "attempt_num": 1,
            "success": False
        },
        {
            "event_type": "inference_attempt",
            "provider": "local_ollama",
            "attempt_num": 1,
            "success": True
        }
    ]

    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(x) for x in events)
    )

    with patch.object(report, "NAS_DIR", tmp_path), \
         patch.object(report, "LOCAL_DIR", tmp_path):

        loaded = report.load_events()

    assert len(loaded) == 2
