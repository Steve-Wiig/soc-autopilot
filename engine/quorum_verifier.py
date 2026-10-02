import time
from typing import Set

from contracts.worker_identity import WorkerVote


class QuorumVerifier:
    """
    Verifies that a quorum of votes meets requirements:
    - All votes are for the same candidate hash
    - Votes are from unique workers
    - Votes are recent (within max_age_seconds)
    - Minimum number of votes is met
    """

    def __init__(self, max_age_seconds: int = 300) -> None:
        """
        Args:
            max_age_seconds: Maximum allowed age (in seconds) for a vote's
                timestamp to still be considered valid.
        """
        self.max_age_seconds = max_age_seconds

    def verify_quorum(self, votes: Set[WorkerVote], min_votes: int) -> bool:
        """
        Determine whether the given set of votes forms a valid quorum.

        Args:
            votes: The set of worker votes to verify.
            min_votes: The minimum number of votes required for quorum.

        Returns:
            True if the votes satisfy all quorum requirements, False otherwise.
        """
        if not votes:
            return False

        if len(votes) < min_votes:
            return False

        if not self._all_votes_for_same_candidate(votes):
            return False

        if not self._all_workers_unique(votes):
            return False

        if not self._all_votes_recent(votes):
            return False

        return True

    @staticmethod
    def _all_votes_for_same_candidate(votes: Set[WorkerVote]) -> bool:
        """Check that every vote in the set targets the same candidate hash."""
        candidate_hashes = {vote.candidate_hash for vote in votes}
        return len(candidate_hashes) == 1

    @staticmethod
    def _all_workers_unique(votes: Set[WorkerVote]) -> bool:
        """Check that each vote comes from a distinct worker."""
        worker_ids = {vote.worker_id for vote in votes}
        return len(worker_ids) == len(votes)

    def _all_votes_recent(self, votes: Set[WorkerVote]) -> bool:
        """Check that every vote's timestamp is within the allowed age."""
        current_time = time.time()
        return all(
            current_time - vote.timestamp <= self.max_age_seconds
            for vote in votes
        )
