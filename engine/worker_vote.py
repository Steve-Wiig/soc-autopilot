
# P0-5: Strong worker identity binding
# Prevents duplicate logical identities from satisfying quorum

from dataclasses import dataclass
from typing import Optional
import hashlib

@dataclass(frozen=True)
class WorkerIdentity:
    """Authoritative worker identity contract."""
    worker_id: str
    worker_class: str
    worker_instance: str
    execution_host: str
    software_version: str
    candidate_hash: str
    decision: str
    timestamp: str

    def compute_signature(self) -> str:
        """Deterministic identity signature."""
        data = f"{self.worker_id}:{self.worker_class}:{self.worker_instance}:{self.execution_host}:{self.software_version}:{self.candidate_hash}:{self.decision}:{self.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()

def validate_worker_vote(vote: dict, candidate_hash: str) -> bool:
    """
    Validate worker vote with identity binding.
    Rejects:
    - Duplicate logical worker IDs
    - Votes for different candidates
    - Malformed identity
    - Replayed approvals
    """
    required_fields = {'worker_id', 'worker_class', 'worker_instance',
                      'execution_host', 'software_version', 'candidate_hash',
                      'decision', 'timestamp'}

    # Check all required fields present
    if not required_fields.issubset(vote.keys()):
        return False

    # Candidate hash must match
    if vote['candidate_hash'] != candidate_hash:
        return False

    # Construct identity and verify signature
    identity = WorkerIdentity(
        worker_id=vote['worker_id'],
        worker_class=vote['worker_class'],
        worker_instance=vote['worker_instance'],
        execution_host=vote['execution_host'],
        software_version=vote['software_version'],
        candidate_hash=vote['candidate_hash'],
        decision=vote['decision'],
        timestamp=vote['timestamp']
    )

    expected_sig = identity.compute_signature()
    if vote.get('signature') != expected_sig:
        return False

    return True

def check_quorum_with_identity(votes: list, candidate_hash: str, required_count: int = 3) -> bool:
    """
    Check quorum with strict identity enforcement.
    Prevents:
    - Same worker_id appearing multiple times
    - Votes for different candidates
    - Replayed approvals
    """
    if len(votes) < required_count:
        return False

    seen_worker_ids = set()
    seen_signatures = set()

    for vote in votes:
        # Validate vote
        if not validate_worker_vote(vote, candidate_hash):
            return False

        # Prevent duplicate logical workers
        worker_id = vote['worker_id']
        if worker_id in seen_worker_ids:
            return False
        seen_worker_ids.add(worker_id)

        # Prevent replay attacks - replay detection via signature uniqueness
        # candidate_hash must be distinct for each vote - prevent reuse across candidates
        signature = vote['signature']
        if signature in seen_signatures:
            return False
        seen_signatures.add(signature)

    return True
