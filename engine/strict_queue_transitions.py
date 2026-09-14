"""
P1-4 Queue Authority: Strict State Machine.
Makes status transitions impossible to bypass.
No caller should have to remember to call a safety gate first.
"""

class StateTransitionViolation(Exception):
    pass

VALID_TRANSITIONS = {
    "pending": {"processing", "failed", "cancelled"},
    "processing": {"completed", "failed", "pending"}, # pending = retry
    "completed": set(), # Terminal
    "failed": set(),    # Terminal
    "cancelled": set(), # Terminal
}

def authorize_transition(current_state: str, target_state: str, job_record: dict) -> bool:
    """
    Structurally enforces queue invariants.
    Raises StateTransitionViolation if the transition is illegal.
    """
    current = current_state.lower()
    target = target_state.lower()
    
    # 1. Check basic state machine validity
    if target not in VALID_TRANSITIONS.get(current, set()):
        raise StateTransitionViolation(
            f"Illegal transition: {current} -> {target}"
        )
        
    # 2. Enforce P1-4 Invariant: CRITICAL jobs cannot reach terminal states without approval
    if target in ("completed", "failed"):
        priority = str(job_record.get("priority", "normal")).upper()
        approved = job_record.get("approval", {}).get("approved", False)
        
        if priority == "CRITICAL" and not approved:
            raise StateTransitionViolation(
                f"CRITICAL job cannot transition to '{target}' without explicit approval. "
                f"Current approval state: {job_record.get('approval')}"
            )
            
    return True


def transition_queue_state(conn, job_id: int, new_status: str, failure_reason: str = None, expected_lease_expires_at: str = None):
    """P1-1: Single authoritative queue transition mechanism.

    Authority chain (each step must succeed; anything else fails closed):

        read current DB state
            -> read DB-backed approval
            -> authorize_transition(current, target, authoritative_record)
            -> UPDATE ... WHERE id = ? AND status = ?
            -> require rowcount == 1
            -> return

    Never trusts caller-supplied current state or approval.
    Raises StateTransitionViolation on any failure.
    """
    target = str(new_status).lower()

    row = conn.execute(
        "SELECT status, severity FROM triage_queue WHERE id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        raise StateTransitionViolation(
            f"Cannot transition unknown job {job_id} to {target!r}"
        )

    current = str(row[0]).lower()
    severity = str(row[1]).lower() if row[1] is not None else "normal"

    approved = conn.execute(
        "SELECT 1 FROM triage_queue_approvals "
        "WHERE job_id = ? AND target_status = ?",
        (job_id, target),
    ).fetchone() is not None

    authorize_transition(
        current,
        target,
        {"priority": severity, "approval": {"approved": approved}},
    )

    if expected_lease_expires_at is not None:
        lease_guard = conn.execute(
            "UPDATE triage_queue "
            "SET lease_expires_at = lease_expires_at "
            "WHERE id = ? AND status = ? AND lease_expires_at = ?",
            (job_id, current, expected_lease_expires_at),
        )

        if lease_guard.rowcount != 1:
            raise StateTransitionViolation(
                f"Lease changed before transition for job {job_id}; "
                "stale reaper operation rejected"
            )

    if target == "completed":
        cur = conn.execute(
            "UPDATE triage_queue SET status = 'completed' "
            "WHERE id = ? AND status = ?",
            (job_id, current),
        )
    elif target == "failed":
        cur = conn.execute(
            "UPDATE triage_queue SET status = 'failed', failure_reason = ? "
            "WHERE id = ? AND status = ?",
            (failure_reason or "UNKNOWN", job_id, current),
        )
    elif target == "pending":
        # Retry reset: only valid from processing; clears lease state.
        cur = conn.execute(
            "UPDATE triage_queue SET status = 'pending', "
            "started_at = NULL, lease_expires_at = NULL, "
            "last_heartbeat_at = NULL "
            "WHERE id = ? AND status = ?",
            (job_id, current),
        )
    else:
        raise StateTransitionViolation(
            f"Unsupported target {target!r}"
        )

    if cur.rowcount != 1:
        raise StateTransitionViolation(
            f"Transition {current}->{target} for job {job_id} "
            f"affected {cur.rowcount} rows; failing closed"
        )

    return cur.rowcount
