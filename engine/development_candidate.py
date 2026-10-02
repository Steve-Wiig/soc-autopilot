"""
P0 Invariant: First-class DevelopmentCandidate identity.
Every stage of the pipeline must consume the SAME candidate identity.
A diff modified after review invalidates all approvals.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


@dataclass
class DevelopmentCandidate:
    """
    Represents a single, immutable-by-identity development candidate as it
    flows through the review/test/canary pipeline.

    Invariant: `diff_sha256` is the source of truth for the candidate's
    content. Any stage that needs to trust the candidate's diff MUST call
    `verify_diff_integrity` with the current diff text before acting on
    prior approvals (e.g. reviewer_votes, deterministic_gates).
    """

    candidate_id: str  # Unique identifier for this candidate.
    base_commit: str  # Commit SHA the diff is based on.
    diff_sha256: str  # SHA-256 hex digest of the diff text at creation time.
    changed_files: List[str]  # Paths of files touched by the diff.
    generator_worker_id: str  # Identifier of the worker that produced the diff.
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # ISO-8601 UTC timestamp of when this candidate was created.

    # Pipeline results
    worker_result: Optional[str] = None  # Outcome reported by the worker stage.
    test_result: Optional[bool] = None  # Whether automated tests passed.
    deterministic_gates: Dict[str, bool] = field(default_factory=dict)
    # Map of deterministic gate name -> pass/fail.
    reviewer_votes: List[Any] = field(default_factory=list)
    # Votes/approvals collected from reviewers.
    canary_result: Optional[bool] = None  # Whether the canary deployment succeeded.
    final_disposition: Optional[str] = None  # Final decision for this candidate.

    @classmethod
    def from_diff(
        cls,
        candidate_id: str,
        base_commit: str,
        diff_text: str,
        changed_files: List[str],
        generator_worker_id: str,
    ) -> "DevelopmentCandidate":
        """
        Construct a DevelopmentCandidate from raw diff text, computing and
        storing its SHA-256 digest as the immutable content identity.

        Args:
            candidate_id: Unique identifier for the new candidate.
            base_commit: Commit SHA the diff is based on.
            diff_text: The raw diff content used to derive `diff_sha256`.
            changed_files: Paths of files touched by the diff.
            generator_worker_id: Identifier of the worker that produced the diff.

        Returns:
            A new DevelopmentCandidate instance with `diff_sha256` set to the
            SHA-256 hex digest of `diff_text`.
        """
        computed_diff_sha256 = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
        return cls(
            candidate_id=candidate_id,
            base_commit=base_commit,
            diff_sha256=computed_diff_sha256,
            changed_files=changed_files,
            generator_worker_id=generator_worker_id
        )

    def verify_diff_integrity(self, current_diff_text: str) -> bool:
        """
        Verify that `current_diff_text` matches the diff this candidate was
        originally created from.

        Invariant: A diff modified after review invalidates all approvals.
        Callers MUST invoke this before trusting any prior approvals
        (e.g. reviewer_votes, deterministic_gates) tied to this candidate.

        Args:
            current_diff_text: The diff text to check against the stored
                `diff_sha256`.

        Returns:
            True if `current_diff_text` hashes to the same value as
            `diff_sha256`, False otherwise.
        """
        current_hash = hashlib.sha256(current_diff_text.encode("utf-8")).hexdigest()
        return current_hash == self.diff_sha256
