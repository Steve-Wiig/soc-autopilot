from engine.memory_store import append_record, load_records


def test_append_record_preserves_events(tmp_path):
    path = tmp_path / "events.jsonl"

    event = {
        "memory_type": "DEFEAT_ATTEMPT",
        "signature": "abc",
        "attempt": 1,
    }

    append_record(path, event)
    append_record(path, event)

    records = load_records(path)

    assert len(records) == 2
    assert records[0]["signature"] == "abc"
    assert records[1]["signature"] == "abc"
