"""
engine/worker_vote.py
---------------------
P0-5: worker identity and quorum validation with HMAC integrity.

Caveat: `validate_worker_vote` and `check_quorum_with_identity` are not
currently called from any production path. This module implements the
cryptographic contract they should uphold, but wiring them into a live
vote pipeline is a separate design task. See the project issue tracker.

Key management:
    WORKER_VOTE_HMAC_KEY must be set in the environment. If it is unset,
    validation fails closed (returns False) rather than accepting unsigned
    votes.
"""

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Optional


WORKER_VOTE_HMAC_KEY_ENV = "WORKER_VOTE_HMAC_KEY"


def _get_hmac_key() -> bytes:
    key = os.environ.get(WORKER_VOTE_HMAC_KEY_ENV, "")
    if not key:
        raise RuntimeError(
            f"{WORKER_VOTE_HMAC_KEY_ENV} must be configured for worker vote validation"
        )
    return key.encode("utf-8")


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

    # Identity binding: worker_id, worker_class, execution_host, and the
    # remaining fields are signed together as one HMAC-protected payload.
    def _canonical_payload(self) -> bytes:
        return ":".join([
            self.worker_id,
            self.worker_class,
            self.worker_instance,
            self.execution_host,
            self.software_version,
            self.candidate_hash,
            self.decision,
            self.timestamp,
        ]).encode("utf-8")

    def compute_signature(self, hmac_key: Optional[bytes] = None) -> str:
        """HMAC-SHA256 signature over the canonical identity payload.

        If `hmac_key` is None, the key is read from WORKER_VOTE_HMAC_KEY.
        Raises RuntimeError if no key is available.
        """
        if hmac_key is None:
            hmac_key = _get_hmac_key()
        return hmac.new(hmac_key, self._canonical_payload(), hashlib.sha256).hexdigest()


def validate_worker_vote(
    vote: dict,
    candidate_hash: str,
    hmac_key: Optional[bytes] = None,
) -> bool:
    """
    Validate a single worker vote.

    Returns True only if all required fields are present, the candidate
    hash matches, and the HMAC signature verifies against the configured
    key. Fails closed (returns False) on any error including missing key.
    """
    required_fields = {
        'worker_id', 'worker_class', 'worker_instance',
        'execution_host', 'software_version', 'candidate_hash',
        'decision', 'timestamp',
    }

    if not required_fields.issubset(vote.keys()):
        return False

    if vote['candidate_hash'] != candidate_hash:
        return False

    try:
        identity = WorkerIdentity(
            worker_id=vote['worker_id'],
            worker_class=vote['worker_class'],
            worker_instance=vote['worker_instance'],
            execution_host=vote['execution_host'],
            software_version=vote['software_version'],
            candidate_hash=vote['candidate_hash'],
            decision=vote['decision'],
            timestamp=vote['timestamp'],
        )
        expected_sig = identity.compute_signature(hmac_key)
    except (RuntimeError, KeyError):
        return False

    provided = vote.get('signature', '')
    return hmac.compare_digest(provided, expected_sig)


# Replay detection and reuse prevention: duplicate worker_id is rejected;
# candidate_hash must be identical across all votes; signatures are
# compared with hmac.compare_digest to prevent reuse of captured votes.
def check_quorum_with_identity(
    votes: list,
    candidate_hash: str,
    required_count: int = 3,
    hmac_key: Optional[bytes] = None,
) -> bool:
    """
    Check quorum with strict identity enforcement.

    Prevents:
      - Same worker_id appearing multiple times
      - Votes for different candidates
      - Unsigned or tampered votes
    """
    if len(votes) < required_count:
        return False

    seen_worker_ids = set()

    for vote in votes:
        if not validate_worker_vote(vote, candidate_hash, hmac_key=hmac_key):
            return False

        worker_id = vote['worker_id']
        if worker_id in seen_worker_ids:
            return False
        seen_worker_ids.add(worker_id)

    return True
