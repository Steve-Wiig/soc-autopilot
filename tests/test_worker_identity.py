import pytest
import time
from contracts.worker_identity import WorkerVote, VoteValidator

def make_vote(**kwargs):
    defaults = {
        "worker_id": "worker-a",
        "worker_class": "Qwen-3B",
        "worker_instance": "inst-1",
        "execution_host": "node-1",
        "software_version": "1.0.0",
        "candidate_hash": "hash123",
        "decision": "APPROVE",
        "timestamp": int(time.time()),
        "signature": "sig123"
    }
    defaults.update(kwargs)
    return WorkerVote(**defaults)

def test_vote_creation_valid():
    vote = make_vote()
    assert vote.worker_id == "worker-a"

def test_vote_creation_missing_field():
    with pytest.raises(ValueError):
        make_vote(worker_id="")

def test_validate_rejects_wrong_candidate_hash():
    validator = VoteValidator()
    vote = make_vote(candidate_hash="hash_wrong")
    with pytest.raises(ValueError, match="Wrong candidate hash"):
        validator.validate(vote, "hash123")

def test_validate_rejects_stale_timestamp():
    validator = VoteValidator(max_clock_skew_seconds=60)
    old_time = int(time.time()) - 3600
    vote = make_vote(timestamp=old_time)
    with pytest.raises(ValueError, match="Stale timestamp"):
        validator.validate(vote, "hash123")

def test_validate_rejects_duplicate_signature():
    validator = VoteValidator()
    vote1 = make_vote(signature="sig1")
    vote2 = make_vote(signature="sig1", worker_id="worker-b")
    validator.validate(vote1, "hash123")
    with pytest.raises(ValueError, match="Duplicate signature"):
        validator.validate(vote2, "hash123")

def test_validate_rejects_duplicate_worker_id():
    validator = VoteValidator()
    vote1 = make_vote(worker_id="worker-a", signature="sig1")
    vote2 = make_vote(worker_id="worker-a", signature="sig2")
    validator.validate(vote1, "hash123")
    with pytest.raises(ValueError, match="Duplicate worker ID"):
        validator.validate(vote2, "hash123")
