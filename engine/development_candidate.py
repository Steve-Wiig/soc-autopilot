"""
P0 Invariant: First-class DevelopmentCandidate identity.
Every stage of the pipeline must consume the SAME candidate identity.
A diff modified after review invalidates all approvals.
"""
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime

@dataclass
class DevelopmentCandidate:
    candidate_id: str
    base_commit: str
    diff_sha256: str
    changed_files: List[str]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Pipeline results
    worker_result: Optional[str] = None
    test_result: Optional[bool] = None
    deterministic_gates: Dict[str, bool] = field(default_factory=dict)
    reviewer_votes: List[Any] = field(default_factory=list)
    canary_result: Optional[bool] = None
    final_disposition: Optional[str] = None

    @classmethod
    def from_diff(cls, candidate_id: str, base_commit: str, diff_text: str, changed_files: List[str]):
        diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
        return cls(
            candidate_id=candidate_id,
            base_commit=base_commit,
            diff_sha256=diff_hash,
            changed_files=changed_files
        )

    def verify_diff_integrity(self, current_diff_text: str) -> bool:
        """Invariant: A diff modified after review invalidates all approvals."""
        current_hash = hashlib.sha256(current_diff_text.encode("utf-8")).hexdigest()
        return current_hash == self.diff_sha256
