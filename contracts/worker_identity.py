import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import Dict, Set

@dataclass(frozen=True)
class WorkerVote:
    """
    Immutable record of a worker's vote on a candidate fix.
    """
    worker_id: str
    worker_class: str
    worker_instance: str
    execution_host: str
    software_version: str
    candidate_hash: str
    decision: str
    timestamp: int  # Unix timestamp
    signature: str

    def __post_init__(self):
        # Strict validation to reject malformed votes at the boundary
        fields = [
            self.worker_id, self.worker_class, self.worker_instance,
            self.execution_host, self.software_version, self.candidate_hash,
            self.decision, self.signature
        ]
        if not all(isinstance(f, str) and f.strip() for f in fields):
            raise ValueError("WorkerVote requires non-empty string fields.")
        if not isinstance(self.timestamp, (int, float)):
            raise ValueError("WorkerVote timestamp must be a number.")

    def canonical_json(self) -> str:
        """Deterministic JSON serialization for signature."""
        return json.dumps(asdict(self), sort_keys=True, separators=(',', ':'))

    def compute_hash(self) -> str:
        """SHA-256 hash of the canonical vote."""
        return hashlib.sha256(self.canonical_json().encode('utf-8')).hexdigest()

class VoteValidator:
    """
    Stateful validator that enforces strict voting invariants.
    Rejects: duplicate signatures, duplicate worker IDs per candidate,
    stale timestamps, and wrong candidate hashes.
    """
    def __init__(self, max_clock_skew_seconds: int = 300):
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self.seen_signatures: Set[str] = set()
        # Track worker_id per candidate_hash to prevent duplicate workers for same candidate
        self.worker_votes_per_candidate: Dict[str, Set[str]] = {}

    def validate(self, vote: WorkerVote, expected_candidate_hash: str) -> None:
        # 1. Reject wrong candidate hash
        if vote.candidate_hash != expected_candidate_hash:
            raise ValueError("Wrong candidate hash.")

        # 2. Reject stale timestamp
        current_time = int(time.time())
        if abs(current_time - vote.timestamp) > self.max_clock_skew_seconds:
            raise ValueError("Stale timestamp.")

        # 3. Reject duplicate signature (replay attack)
        if vote.signature in self.seen_signatures:
            raise ValueError("Duplicate signature.")

        # 4. Reject duplicate worker ID for the same candidate
        candidate_workers = self.worker_votes_per_candidate.get(vote.candidate_hash, set())
        if vote.worker_id in candidate_workers:
            raise ValueError("Duplicate worker ID for candidate.")

        # Register the valid vote
        self.seen_signatures.add(vote.signature)
        if vote.candidate_hash not in self.worker_votes_per_candidate:
            self.worker_votes_per_candidate[vote.candidate_hash] = set()
        self.worker_votes_per_candidate[vote.candidate_hash].add(vote.worker_id)
