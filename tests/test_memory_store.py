from engine.memory_store import (
    fingerprint_failure,
    append_failure,
    load_failures,
    find_matching_failures,
)


def test_fingerprint_stable():

    a = fingerprint_failure(
        "engine/test.py",
        "AssertionError",
        "bad patch",
    )

    b = fingerprint_failure(
        "engine/test.py",
        "AssertionError",
        "bad patch",
    )

    assert a == b


def test_memory_round_trip(tmp_path):

    path = tmp_path / "failed_patterns.jsonl"

    fp = fingerprint_failure(
        "engine/test.py",
        "pytest failure",
        "avoid repeat",
    )

    append_failure(
        path,
        {
            "fingerprint": fp,
            "lesson": "avoid repeat",
        },
    )

    result = load_failures(path)

    assert len(result) == 1
    assert result[0]["fingerprint"] == fp


def test_lookup(tmp_path):

    path = tmp_path / "failed_patterns.jsonl"

    fp = fingerprint_failure(
        "x.py",
        "failure",
        "lesson",
    )

    append_failure(
        path,
        {
            "fingerprint": fp,
        },
    )

    assert len(
        find_matching_failures(path, fp)
    ) == 1
