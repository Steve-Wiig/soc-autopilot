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
