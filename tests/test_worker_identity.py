import pytest
import hashlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def make_valid_vote(worker_id: str, candidate_hash: str = "abc123", timestamp: str = "2026-09-11T00:00:00") -> dict:
    """Helper to create a valid vote with correct signature."""
    from engine.worker_vote import WorkerIdentity
    identity = WorkerIdentity(
        worker_id=worker_id,
        worker_class="llm-reviewer",
        worker_instance="instance-1",
        execution_host="host-1",
        software_version="1.0.0",
        candidate_hash=candidate_hash,
        decision="approve",
        timestamp=timestamp
    )
    return {
        "worker_id": worker_id,
        "worker_class": "llm-reviewer",
        "worker_instance": "instance-1",
        "execution_host": "host-1",
        "software_version": "1.0.0",
        "candidate_hash": candidate_hash,
        "decision": "approve",
        "timestamp": timestamp,
        "signature": identity.compute_signature()
    }

def test_duplicate_worker_id_rejected():
    """Same worker_id cannot satisfy quorum twice."""
    from engine.worker_vote import check_quorum_with_identity
    votes = [
        make_valid_vote("worker-a"),
        make_valid_vote("worker-a"),
        make_valid_vote("worker-b"),
    ]
    assert not check_quorum_with_identity(votes, "abc123")

def test_distinct_workers_pass():
    """Three distinct workers satisfy quorum."""
    from engine.worker_vote import check_quorum_with_identity
    votes = [
        make_valid_vote("worker-a"),
        make_valid_vote("worker-b"),
        make_valid_vote("worker-c"),
    ]
    assert check_quorum_with_identity(votes, "abc123")

def test_wrong_candidate_hash_rejected():
    """Vote for different candidate cannot satisfy quorum."""
    from engine.worker_vote import check_quorum_with_identity
    votes = [
        make_valid_vote("worker-a", "abc123"),
        make_valid_vote("worker-b", "def456"),  # Different candidate
        make_valid_vote("worker-c", "abc123"),
    ]
    assert not check_quorum_with_identity(votes, "abc123")

def test_replayed_approval_rejected():
    """Same approval cannot be reused."""
    from engine.worker_vote import check_quorum_with_identity
    vote1 = make_valid_vote("worker-a")
    votes = [
        vote1,
        make_valid_vote("worker-b"),
        vote1,  # Replay
    ]
    assert not check_quorum_with_identity(votes, "abc123")

def test_malformed_identity_rejected():
    """Missing fields cause rejection."""
    from engine.worker_vote import check_quorum_with_identity
    votes = [
        make_valid_vote("worker-a"),
        {"worker_id": "worker-b"},  # Missing fields
        make_valid_vote("worker-c"),
    ]
    assert not check_quorum_with_identity(votes, "abc123")

def test_invalid_signature_rejected():
    """Tampered signature causes rejection."""
    from engine.worker_vote import check_quorum_with_identity
    vote = make_valid_vote("worker-a")
    vote["signature"] = "invalid"
    votes = [
        vote,
        make_valid_vote("worker-b"),
        make_valid_vote("worker-c"),
    ]
    assert not check_quorum_with_identity(votes, "abc123")
