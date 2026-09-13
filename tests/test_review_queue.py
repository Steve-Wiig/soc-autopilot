"""Tests for tools/review_queue.py: read-only by default, append-only on confirm."""
import json
from pathlib import Path

import pytest

import tools.review_queue as rq


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point the tool at temp files so tests never touch overnight/."""
    queue_path = tmp_path / "needs_manual_review.json"
    decisions_path = tmp_path / "manual_review_decisions.jsonl"
    monkeypatch.setattr(rq, "QUEUE_PATH", queue_path)
    monkeypatch.setattr(rq, "DECISIONS_PATH", decisions_path)
    monkeypatch.setattr(rq, "REPO_ROOT", tmp_path)
    return queue_path, decisions_path


def _seed_queue(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps(items))


def _sample_items() -> list[dict]:
    return [
        {
            "file": "engine/defeat_ledger.py",
            "issue": {
                "category": "performance",
                "severity": "medium",
                "description": "is_ast_defeated reads entire ledger file",
            },
            "deferred_reason": "Routing policy requires review for performance advisory.",
            "escalated_at": "2026-09-12T23:40:17",
        },
        {
            "file": "engine/hash_chain_sealer.py",
            "issue": {
                "category": "maintainability",
                "severity": "high",
                "description": "hardcoded column names in INSERT",
            },
            "deferred_reason": "High-risk maintainability advisory requires manual/Oracle review.",
            "escalated_at": "2026-09-12T23:40:18",
        },
    ]


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def test_item_id_is_stable_and_short():
    item = _sample_items()[0]
    a = rq.item_id(item)
    b = rq.item_id(item)
    assert a == b
    assert a.startswith("mr-")
    assert len(a) == 13


def test_item_id_differs_for_different_items():
    a = rq.item_id(_sample_items()[0])
    b = rq.item_id(_sample_items()[1])
    assert a != b


# ---------------------------------------------------------------------------
# Read-only behavior
# ---------------------------------------------------------------------------
def test_summary_writes_nothing(isolated, capsys):
    queue_path, decisions_path = isolated
    _seed_queue(queue_path, _sample_items())
    before = queue_path.read_text()

    rc = rq.main([])
    assert rc == 0
    assert queue_path.read_text() == before
    assert not decisions_path.exists()

    out = capsys.readouterr().out
    assert "MANUAL REVIEW QUEUE" in out
    assert "Total in queue:  2" in out


def test_list_writes_nothing(isolated, capsys):
    queue_path, decisions_path = isolated
    _seed_queue(queue_path, _sample_items())
    before = queue_path.read_text()

    rc = rq.main(["--list"])
    assert rc == 0
    assert queue_path.read_text() == before
    assert not decisions_path.exists()
    assert "engine/defeat_ledger.py" in capsys.readouterr().out


def test_show_writes_nothing(isolated, capsys):
    queue_path, decisions_path = isolated
    items = _sample_items()
    _seed_queue(queue_path, items)
    iid = rq.item_id(items[0])
    before = queue_path.read_text()

    rc = rq.main(["--show", iid])
    assert rc == 0
    assert queue_path.read_text() == before
    assert not decisions_path.exists()
    out = capsys.readouterr().out
    assert iid in out
    assert "performance" in out


# ---------------------------------------------------------------------------
# Write gate
# ---------------------------------------------------------------------------
def test_approve_without_confirm_writes_nothing(isolated, capsys):
    queue_path, decisions_path = isolated
    items = _sample_items()
    _seed_queue(queue_path, items)
    iid = rq.item_id(items[0])

    rc = rq.main(["--approve", iid])
    assert rc == 0
    assert not decisions_path.exists()
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_reject_without_confirm_writes_nothing(isolated, capsys):
    queue_path, decisions_path = isolated
    items = _sample_items()
    _seed_queue(queue_path, items)
    iid = rq.item_id(items[0])

    rc = rq.main(["--reject", iid, "--reason", "needs more context"])
    assert rc == 0
    assert not decisions_path.exists()
    assert "DRY RUN" in capsys.readouterr().out


def test_approve_with_confirm_writes_one_decision(isolated):
    queue_path, decisions_path = isolated
    items = _sample_items()
    _seed_queue(queue_path, items)
    iid = rq.item_id(items[0])
    before_queue = queue_path.read_text()

    rc = rq.main(["--approve", iid, "--confirm"])
    assert rc == 0

    # queue file untouched
    assert queue_path.read_text() == before_queue

    # decisions file has exactly one record
    lines = decisions_path.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["id"] == iid
    assert rec["decision"] == "approve"
    assert rec["file"] == items[0]["file"]


def test_reject_with_confirm_stores_reason(isolated):
    queue_path, decisions_path = isolated
    items = _sample_items()
    _seed_queue(queue_path, items)
    iid = rq.item_id(items[0])

    rc = rq.main(["--reject", iid, "--reason", "not worth the risk", "--confirm"])
    assert rc == 0

    rec = json.loads(decisions_path.read_text().strip())
    assert rec["decision"] == "reject"
    assert rec["reason"] == "not worth the risk"


# ---------------------------------------------------------------------------
# Pending filter
# ---------------------------------------------------------------------------
def test_decided_items_are_filtered_from_list(isolated, capsys):
    queue_path, decisions_path = isolated
    items = _sample_items()
    _seed_queue(queue_path, items)
    a = rq.item_id(items[0])
    b = rq.item_id(items[1])

    rq.main(["--approve", a, "--confirm"])

    capsys.readouterr()  # discard
    rq.main(["--list"])
    out = capsys.readouterr().out
    assert a not in out
    assert b in out

    capsys.readouterr()
    rq.main(["--list", "--all"])
    out_all = capsys.readouterr().out
    assert a in out_all
    assert b in out_all


def test_decided_items_not_overwritten(isolated, capsys):
    queue_path, decisions_path = isolated
    items = _sample_items()
    _seed_queue(queue_path, items)
    iid = rq.item_id(items[0])

    rq.main(["--approve", iid, "--confirm"])
    capsys.readouterr()

    rc = rq.main(["--reject", iid, "--confirm"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "already has a decision" in out

    # decisions file still has exactly one line
    lines = decisions_path.read_text().strip().splitlines()
    assert len(lines) == 1


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------
def test_unknown_id_aborts(isolated, capsys):
    queue_path, _decisions = isolated
    _seed_queue(queue_path, _sample_items())

    rc = rq.main(["--show", "mr-0000000000"])
    assert rc == 1

    rc = rq.main(["--approve", "mr-0000000000", "--confirm"])
    assert rc == 1


def test_missing_queue_returns_empty(isolated, capsys):
    _queue_path, decisions_path = isolated
    rc = rq.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Total in queue:  0" in out
    assert not decisions_path.exists()
