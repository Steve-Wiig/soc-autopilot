"""
P0 Invariant: Attributable WorkerVote identity.
Distinct strings are not proof of independent workers. 
Votes must bind to the exact candidate hash.
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class WorkerVote:
    proposal_id: str
    proposal_sha256: str
    worker_id: str
    worker_class: str
    worker_instance: str
    timestamp: str
    decision: str  # "approve" | "reject" | "veto"
    reason: str
    evidence_hash: str
    signature: Optional[str] = None
    worker_software_version: Optional[str] = None
    execution_host: Optional[str] = None

    def is_valid_for_candidate(self, candidate_diff_sha256: str) -> bool:
        """Ensures this vote was cast for the exact current diff."""
        return self.proposal_sha256 == candidate_diff_sha256
