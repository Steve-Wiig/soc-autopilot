from pathlib import Path

from engine.memory_store import append_unique, load_records


def test_defeat_signature_is_unique(tmp_path):
    path = tmp_path / "defeat.jsonl"

    first = {
        "memory_type": "DEFEAT",
        "signature": "abc123",
        "ast_hash": "ast1",
        "tb_hash": "tb1",
        "attempts": 1,
    }

    second = {
        "memory_type": "DEFEAT",
        "signature": "abc123",
        "ast_hash": "ast1",
        "tb_hash": "tb1",
        "attempts": 2,
    }

    assert append_unique(path, first) is True

    # Same failure identity should deduplicate.
    assert append_unique(path, second) is False

    records = load_records(path)

    assert len(records) == 1
    assert records[0]["signature"] == "abc123"
