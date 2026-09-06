import json
from pathlib import Path
from unittest.mock import patch

import tools.telemetry_report as report


def test_load_events_deduplicates_locations(tmp_path):

    event = {
        "remediation_id": "abc",
        "ts": 12345,
        "target_file": "example.py",
        "stage": "generation",
        "attempt_num": 1
    }

    nas = tmp_path / "nas"
    local = tmp_path / "local"

    nas.mkdir()
    local.mkdir()
    (local / "outbox").mkdir()

    for path in [
        nas / "flush.jsonl",
        nas / "overnight.jsonl",
        local / "current.jsonl",
        local / "outbox" / "pending.jsonl",
    ]:
        path.write_text(json.dumps(event)+"\n")

    with patch.object(report, "NAS_DIR", nas), \
         patch.object(report, "LOCAL_DIR", local):

        events = report.load_events()

    assert len(events) == 1
    assert events[0]["remediation_id"] == "abc"
