"""
Memory storage primitives.

No model calls.
No autonomous decisions.
No promotion authority.

Provides:
- deterministic fingerprints
- duplicate-safe append
- corruption tolerant loading
- bounded retrieval
"""

import hashlib
import json
from pathlib import Path


def record_fingerprint(record: dict) -> str:
    """
    Stable identity for a memory record.

    Excludes timestamp so repeated observations
    of the same failure deduplicate.
    """

    keys = [
        "category",
        "file",
        "advisory",
        "constraint",
        "failed_diff",
        "candidate_hash",
        "failure_signature",
        "signature",
    ]

    payload = {
        key: record.get(key, "")
        for key in keys
    }

    raw = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def load_records(path: Path):
    """
    Load JSONL safely.

    Invalid lines are ignored.
    """

    if not path.exists():
        return []

    records = []

    try:
        with path.open(
            encoding="utf-8"
        ) as f:

            for line in f:
                if not line.strip():
                    continue

                try:
                    records.append(
                        json.loads(line)
                    )
                except json.JSONDecodeError:
                    continue

    except OSError:
        return []

    return records


def append_unique(
    path: Path,
    record: dict,
) -> bool:
    """
    Append only if identical memory does not exist.

    Returns:
        True  = appended
        False = duplicate/skipped
    """

    existing = load_records(path)

    new_hash = record_fingerprint(record)

    for item in existing:
        if record_fingerprint(item) == new_hash:
            return False

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    record = dict(record)
    record["memory_hash"] = new_hash

    with path.open(
        "a",
        encoding="utf-8",
    ) as f:
        f.write(
            json.dumps(record)
            + "\n"
        )

    return True


def append_record(
    path: Path,
    record: dict,
) -> None:
    """
    Append an event record without deduplication.

    Intended for immutable event streams:
    - defeat attempts
    - telemetry events
    - audit history

    Unlike append_unique(), repeated identical
    records are expected and preserved.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as f:
        f.write(
            json.dumps(record)
            + "\n"
        )


def find_matching(
    path: Path,
    predicate,
    limit=5,
):
    """
    Generic bounded retrieval.
    """

    results = []

    for item in load_records(path):
        try:
            if predicate(item):
                results.append(item)

                if len(results) >= limit:
                    break

        except Exception:
            continue

    return results


# ============================================================
# LEGACY COMPATIBILITY API
# ============================================================
#
# Existing callers continue using the original names.
# Implementation delegates to hardened primitives.
#
# No behavior authority added.
#


def fingerprint_failure(
    target: str,
    failure_signature: str,
    lesson: str,
) -> str:
    return record_fingerprint(
        {
            "file": target,
            "failure_signature": failure_signature,
            "constraint": lesson,
        }
    )


def append_failure(path: Path, record: dict):
    return append_unique(
        path,
        record,
    )


def load_failures(path: Path):
    return load_records(path)


def find_matching_failures(
    path: Path,
    fingerprint: str,
):
    return find_matching(
        path,
        lambda item: (
            item.get("fingerprint") == fingerprint
            or record_fingerprint(item) == fingerprint
        ),
    )
