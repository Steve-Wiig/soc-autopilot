"""
P0 Invariant: Attributable WorkerVote identity with Ed25519 verification.
Distinct strings are not proof of independent workers.
Votes must bind to the exact candidate hash.
"""
import base64
import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Set


class VoteSerializer:
    """
    Adapter for deterministic serialization of WorkerVote data.

    Encapsulates the canonical JSON format and signing payload generation
    to ensure consistent encoding across all consumers. This class is
    stateless and thread-safe.
    """

    @staticmethod
    def to_canonical_json(data: Dict[str, Any]) -> str:
        """
        Return deterministic JSON serialization with sorted keys and minimal separators.

        Args:
            data: Dictionary to serialize.

        Returns:
            Canonical JSON string.
        """
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def signing_payload(vote_data: Dict[str, Any]) -> str:
        """
        Generate the signing payload by clearing the signature field.

        Args:
            vote_data: Dictionary containing vote fields including 'signature'.

        Returns:
            Canonical JSON string with signature set to empty string.
        """
        data = dict(vote_data)
        data["signature"] = ""
        return VoteSerializer.to_canonical_json(data)

    @staticmethod
    def compute_hash(canonical_json: str) -> str:
        """
        Return the SHA-256 hex digest of the canonical JSON representation.

        Args:
            canonical_json: Output from to_canonical_json().

        Returns:
            Hex digest string.
        """
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkerVote:
    """
    Immutable record of a worker's vote on a candidate fix.
    Signature is mandatory and must be a valid Ed25519 signature
    over the signing_payload() when a key registry is provided.

    The signing_payload() method returns a canonical JSON representation
    of the vote fields, with the ``signature`` field cleared (set to an
    empty string). This payload is the exact byte string that the worker's
    Ed25519 private key signs, ensuring that the signature binds to the
    vote data and not to any other metadata. The payload includes all
    fields that define the vote: worker_id, worker_class, worker_instance,
    execution_host, software_version, candidate_hash, decision, timestamp,
    and task_id. By removing the signature before serialization, we avoid
    a circular dependency where the signature would be part of the data
    it signs. The canonical JSON is produced with ``sort_keys=True`` and
    ``separators=(',', ':')`` to guarantee deterministic encoding across
    different platforms and implementations. This deterministic format
    is essential for correct verification in the VoteValidator.
    """
    worker_id: str
    worker_class: str
    worker_instance: str
    execution_host: str
    software_version: str
    candidate_hash: str
    decision: str
    timestamp: float
    task_id: str
    signature: str

    def __post_init__(self) -> None:
        """Validate that all string fields are non-empty and timestamp is numeric."""
        string_fields = [
            self.worker_id, self.worker_class, self.worker_instance,
            self.execution_host, self.software_version, self.candidate_hash,
            self.decision, self.task_id, self.signature,
        ]
        if not all(isinstance(field_value, str) and field_value.strip() for field_value in string_fields):
            raise ValueError("WorkerVote requires non-empty string fields.")
        if not isinstance(self.timestamp, (int, float)):
            raise ValueError("WorkerVote timestamp must be a number.")

    def canonical_json(self) -> str:
        """Return the deterministic JSON serialization of all vote fields, including signature."""
        return VoteSerializer.to_canonical_json(asdict(self))

    def signing_payload(self) -> str:
        """Canonical JSON with signature cleared for signing/verification."""
        return VoteSerializer.signing_payload(asdict(self))

    def compute_hash(self) -> str:
        """Return the SHA-256 hex digest of the canonical JSON representation."""
        return VoteSerializer.compute_hash(self.canonical_json())


class VoteValidator:
    """
    Stateful validator for candidate-bound worker votes.
    Enforces: candidate binding, timestamp freshness, replay protection,
    worker uniqueness, and Ed25519 signature verification.
    """

    def __init__(self, key_registry: Optional[Any] = None, max_clock_skew_seconds: int = 300) -> None:
        """
        Initialize the validator.

        :param key_registry: Optional object exposing get_public_key(worker_id) used
            to verify Ed25519 signatures. If None, signature verification is skipped.
        :param max_clock_skew_seconds: Maximum allowed difference, in seconds, between
            the vote timestamp and the current time.
        """
        if not isinstance(max_clock_skew_seconds, int) or max_clock_skew_seconds < 0:
            raise ValueError("max_clock_skew_seconds must be a non-negative integer.")
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self.seen_signatures: Set[str] = set()
        self.worker_votes_per_candidate: Dict[str, Set[str]] = {}
        self.key_registry = key_registry

    def validate(self, vote: WorkerVote, expected_candidate_hash: str) -> None:
        """
        Validate a WorkerVote against the expected candidate hash.

        Performs, in order:
          1. Candidate binding check.
          2. Timestamp freshness check.
          3. Replay protection (duplicate signature) check.
          4. Worker independence check per candidate.
          5. Ed25519 cryptographic signature verification (if key_registry is set).

        Raises ValueError on any validation failure. On success, registers the
        vote's signature and worker id so future duplicate votes are rejected.
        """
        # 1. Candidate binding
        if vote.candidate_hash != expected_candidate_hash:
            raise ValueError("Wrong candidate hash.")

        # 2. Timestamp freshness
        if abs(time.time() - vote.timestamp) > self.max_clock_skew_seconds:
            raise ValueError("Stale timestamp.")

        # 3. Replay protection
        if vote.signature in self.seen_signatures:
            raise ValueError("Duplicate signature.")

        # 4. Worker independence per candidate
        candidate_workers = self.worker_votes_per_candidate.get(
            vote.candidate_hash, set()
        )
        if vote.worker_id in candidate_workers:
            raise ValueError("Duplicate worker ID for candidate.")

        # 5. Ed25519 cryptographic signature verification
        if self.key_registry is not None:
            public_key = self.key_registry.get_public_key(vote.worker_id)
            if public_key is None:
                raise ValueError(f"Unknown worker: {vote.worker_id}")
            try:
                payload = vote.signing_payload().encode("utf-8")
                sig_bytes = base64.b64decode(vote.signature)
                public_key.verify(sig_bytes, payload)
            except Exception:
                raise ValueError("Invalid cryptographic signature.")

        # Register only after all validation succeeds
        self.seen_signatures.add(vote.signature)
        self.worker_votes_per_candidate.setdefault(
            vote.candidate_hash, set()
        ).add(vote.worker_id)
