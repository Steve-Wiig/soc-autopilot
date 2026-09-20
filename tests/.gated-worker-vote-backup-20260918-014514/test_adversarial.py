import pytest
import time
import json
from contracts.worker_identity import WorkerVote, VoteValidator
from engine.ledger import parse_ledger_event

# ==========================================
# Adversarial Replay Tests
# ==========================================
def test_replay_attack_old_signature():
    """An attacker tries to reuse an old signature for a new candidate."""
    validator = VoteValidator()
    old_vote = WorkerVote(
        worker_id="attacker", worker_class="Qwen-3B", worker_instance="inst-1",
        execution_host="node-1", software_version="1.0.0", candidate_hash="old_hash",
        decision="APPROVE", timestamp=int(time.time()), signature="old_sig"
    )
    validator.validate(old_vote, "old_hash")

    # Attacker reuses the signature for a new candidate
    replayed_vote = WorkerVote(
        worker_id="attacker", worker_class="Qwen-3B", worker_instance="inst-1",
        execution_host="node-1", software_version="1.0.0", candidate_hash="new_hash",
        decision="APPROVE", timestamp=int(time.time()), signature="old_sig"
    )
    with pytest.raises(ValueError, match="Duplicate signature"):
        validator.validate(replayed_vote, "new_hash")

# ==========================================
# Adversarial Duplicate Worker Tests
# ==========================================
def test_duplicate_worker_same_candidate():
    """A worker tries to vote twice on the same candidate to skew consensus."""
    validator = VoteValidator()
    vote1 = WorkerVote(
        worker_id="worker-a", worker_class="Qwen-3B", worker_instance="inst-1",
        execution_host="node-1", software_version="1.0.0", candidate_hash="hash1",
        decision="APPROVE", timestamp=int(time.time()), signature="sig1"
    )
    validator.validate(vote1, "hash1")

    vote2 = WorkerVote(
        worker_id="worker-a", worker_class="Qwen-3B", worker_instance="inst-1",
        execution_host="node-1", software_version="1.0.0", candidate_hash="hash1",
        decision="REJECT", timestamp=int(time.time()), signature="sig2"
    )
    with pytest.raises(ValueError, match="Duplicate worker ID"):
        validator.validate(vote2, "hash1")

# ==========================================
# Adversarial Ledger Corruption Tests
# ==========================================
def test_ledger_corruption_invalid_json():
    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_ledger_event("{this is not json")

def test_ledger_corruption_missing_type():
    with pytest.raises(ValueError, match="Missing 'type'"):
        parse_ledger_event('{"schema_version": 2, "advisory_id": "123"}')

def test_ledger_corruption_future_schema():
    future_event = json.dumps({"type": "OBSERVATION", "schema_version": 999})
    with pytest.raises(ValueError, match="Unsupported future schema"):
        parse_ledger_event(future_event)

def test_ledger_corruption_non_object():
    with pytest.raises(ValueError, match="Event must be a JSON object"):
        parse_ledger_event('"just a string"')
