"""
Compatibility adapter.

Legacy engine.worker_vote_contract.WorkerVote
is normalized into the hardened identity contract.

No validation bypass.
No automatic trust escalation.
"""

from datetime import datetime, timezone

from contracts.worker_identity import WorkerVote as IdentityWorkerVote


def _timestamp(value):
    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        try:
            return int(
                datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).timestamp()
            )
        except Exception:
            pass

    return int(datetime.now(timezone.utc).timestamp())


def normalize_worker_vote(old_vote):
    """
    Convert legacy WorkerVote into hardened WorkerVote.
    """

    return IdentityWorkerVote(
        worker_id=old_vote.worker_id,
        worker_class=getattr(old_vote, "worker_class", "unknown"),
        worker_instance=getattr(old_vote, "worker_instance", "unknown"),
        execution_host=(
            getattr(old_vote, "execution_host", None)
            or "legacy-host"
        ),
        software_version=(
            getattr(old_vote, "worker_software_version", None)
            or "legacy-version"
        ),
        candidate_hash=old_vote.proposal_sha256,
        decision=str(old_vote.decision).upper(),
        timestamp=_timestamp(old_vote.timestamp),
        signature=getattr(old_vote, "signature", "") or
                  f"legacy-migration:{old_vote.worker_id}"
    )
