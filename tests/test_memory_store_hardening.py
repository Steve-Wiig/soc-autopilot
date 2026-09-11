from pathlib import Path

from engine.memory_store import (
    record_fingerprint,
    append_unique,
    load_records,
    find_matching,
)


def test_fingerprint_ignores_timestamp():

    a = {
        "file": "x.py",
        "category": "security",
        "timestamp": "one",
    }

    b = {
        "file": "x.py",
        "category": "security",
        "timestamp": "two",
    }

    assert record_fingerprint(a) == record_fingerprint(b)


def test_duplicate_memory_not_written(tmp_path):

    path = tmp_path / "memory.jsonl"

    record = {
        "file": "x.py",
        "category": "security",
        "constraint": "bad patch",
    }

    assert append_unique(path, record)
    assert not append_unique(path, record)

    assert len(load_records(path)) == 1


def test_corrupt_lines_ignored(tmp_path):

    path = tmp_path / "memory.jsonl"

    path.write_text(
        '{"file":"ok"}\n'
        'broken json\n'
    )

    assert len(load_records(path)) == 1


def test_bounded_lookup(tmp_path):

    path = tmp_path / "memory.jsonl"

    append_unique(
        path,
        {"category": "security"}
    )

    result = find_matching(
        path,
        lambda x: x.get("category") == "security",
    )

    assert len(result) == 1
