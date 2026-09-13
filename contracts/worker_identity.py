import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import Dict, Set


@dataclass(frozen=True)
class WorkerVote:
    """
    Immutable record of a worker's vote on a candidate fix.

    This is the hardened identity contract consumed by strict quorum
    validation. It is intentionally independent of model/provider type.
    """

    worker_id: str
    worker_class: str
    worker_instance: str
    execution_host: str
    software_version: str
    candidate_hash: str
    decision: str
    timestamp: int
    signature: str

    def __post_init__(self):
        fields = [
            self.worker_id,
            self.worker_class,
            self.worker_instance,
            self.execution_host,
            self.software_version,
            self.candidate_hash,
            self.decision,
            self.signature,
        ]

        if not all(
            isinstance(field, str) and field.strip()
            for field in fields
        ):
            raise ValueError(
                "WorkerVote requires non-empty string fields."
            )

        if not isinstance(self.timestamp, (int, float)):
            raise ValueError(
                "WorkerVote timestamp must be a number."
            )

    def canonical_json(self) -> str:
        """Deterministic serialization of the complete vote identity."""
        return json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
        )

    def compute_hash(self) -> str:
        """Deterministic SHA-256 identity hash of the vote."""
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()


class VoteValidator:
    """
    Stateful validator for candidate-bound worker votes.

    Enforces:
      - exact candidate binding
      - timestamp freshness
      - signature replay protection
      - worker uniqueness per candidate
    """

    def __init__(self, max_clock_skew_seconds: int = 300):
        if (
            not isinstance(max_clock_skew_seconds, int)
            or max_clock_skew_seconds < 0
        ):
            raise ValueError(
                "max_clock_skew_seconds must be a non-negative integer."
            )

        self.max_clock_skew_seconds = max_clock_skew_seconds
        self.seen_signatures: Set[str] = set()
        self.worker_votes_per_candidate: Dict[str, Set[str]] = {}

    def validate(
        self,
        vote: WorkerVote,
        expected_candidate_hash: str,
    ) -> None:
        # 1. Candidate identity is the first authorization check.
        if vote.candidate_hash != expected_candidate_hash:
            raise ValueError("Wrong candidate hash.")

        # 2. Timestamp freshness.
        current_time = int(time.time())

        if abs(current_time - int(vote.timestamp)) > self.max_clock_skew_seconds:
            raise ValueError("Stale timestamp.")

        # 3. Replay protection.
        if vote.signature in self.seen_signatures:
            raise ValueError("Duplicate signature.")

        # 4. Worker independence per candidate.
        candidate_workers = self.worker_votes_per_candidate.get(
            vote.candidate_hash,
            set(),
        )

        if vote.worker_id in candidate_workers:
            raise ValueError("Duplicate worker ID for candidate.")

        # Register only after all validation succeeds.
        self.seen_signatures.add(vote.signature)

        self.worker_votes_per_candidate.setdefault(
            vote.candidate_hash,
            set(),
        ).add(vote.worker_id)
