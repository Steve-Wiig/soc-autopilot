"""
Compatibility adapter.

Legacy engine.worker_vote_contract.WorkerVote
is normalized into the hardened identity contract.

No validation bypass.
No automatic trust escalation.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Union

from contracts.worker_identity import WorkerVote as IdentityWorkerVote

logger = logging.getLogger(__name__)


def _normalize_timestamp(value: Optional[Union[int, float, str]]) -> int:
    """
    Normalize a legacy timestamp value into a Unix epoch integer.

    Accepts:
      - int/float: treated as an already-valid epoch timestamp.
      - str: parsed as an ISO 8601 timestamp (with optional trailing "Z").
      - None or anything else: falls back to the current UTC time.

    Raises:
      Exception: re-raised after logging if an ISO 8601 string fails to
      parse. This is intentional fail-closed behavior; malformed
      timestamps must not be silently coerced.
    """
    if isinstance(value, (int, float)):
        return int(value)

    if isinstance(value, str):
        try:
            return int(
                datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).timestamp()
            )
        except Exception as e:
            # HARDENED: Fail closed with telemetry
            logger.error(
                "CONTROL-PLANE FAILURE in worker_vote_adapter.py: %s", e
            )
            raise

    return int(datetime.now(timezone.utc).timestamp())


def normalize_worker_vote(legacy_vote) -> IdentityWorkerVote:
    """
    Convert a legacy WorkerVote into the hardened identity WorkerVote.

    This performs field-level normalization only. It does not perform
    any trust escalation or validation bypass; missing optional fields
    are filled with explicit "legacy-*" sentinel values so downstream
    consumers can distinguish migrated votes from natively hardened
    ones.

    Args:
        legacy_vote: An instance of the legacy
            engine.worker_vote_contract.WorkerVote (or compatible
            duck-typed object).

    Returns:
        IdentityWorkerVote: The normalized, hardened vote contract.
    """
    return IdentityWorkerVote(
        worker_id=legacy_vote.worker_id,
        worker_class=getattr(legacy_vote, "worker_class", "unknown"),
        worker_instance=getattr(legacy_vote, "worker_instance", "unknown"),
        execution_host=(
            getattr(legacy_vote, "execution_host", None)
            or "legacy-host"
        ),
        software_version=(
            getattr(legacy_vote, "worker_software_version", None)
            or "legacy-version"
        ),
        candidate_hash=legacy_vote.proposal_sha256,
        decision=str(legacy_vote.decision).upper(),
        timestamp=_normalize_timestamp(legacy_vote.timestamp),
        signature=getattr(legacy_vote, "signature", "") or
                  f"legacy-migration:{legacy_vote.worker_id}"
    )
