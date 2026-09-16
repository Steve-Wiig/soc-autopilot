import time
from typing import Dict, Set
from contracts.worker_identity import WorkerVote

class QuorumVerifier:
    """
    Verifies that a quorum of votes meets requirements:
    - All votes are for the same candidate hash
    - Votes are from unique workers
    - Votes are recent (within max_age_seconds)
    - Minimum number of votes is met
    """
    
    def __init__(self, max_age_seconds: int = 300):
        self.max_age_seconds = max_age_seconds
        
    def verify_quorum(self, votes: Set[WorkerVote], min_votes: int) -> bool:
        if not votes:
            return False
            
        if len(votes) < min_votes:
            return False
            
        # Check all votes are for same candidate
        candidate_hashes = {vote.candidate_hash for vote in votes}
        if len(candidate_hashes) != 1:
            return False
            
        # Check for unique workers
        worker_ids = {vote.worker_id for vote in votes}
        if len(worker_ids) != len(votes):
            return False
            
        # Check timestamps are recent
        current_time = time.time()
        for vote in votes:
            if current_time - vote.timestamp > self.max_age_seconds:
                return False
                
        return True
