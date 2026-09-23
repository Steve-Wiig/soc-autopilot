import re

with open("engine/deterministic_policy.py", "r") as f:
    content = f.read()

# Replace the evaluate_deterministic_policy function with the exact legacy logic
pattern = r"def evaluate_deterministic_policy\(envelope.*?return PolicyDecision\(\s*incident_id=envelope\.incident_id.*?decision_reason=f\"Policy fail-closed: unrecognized recommendation '\{action\}'\"\s*\)"

new_logic = '''def evaluate_deterministic_policy(envelope: PolicyRecommendationEnvelope, authoritative_trusted_source: bool = False, **kwargs) -> PolicyDecision:
    """Legacy-compatible policy evaluation."""
    action = (envelope.model_recommendation or envelope.recommended_action or "").upper().strip()
    severity = (envelope.model_severity or envelope.severity or "").upper().strip()
    human_review = envelope.requires_human_review
    inc_id = envelope.incident_id or envelope.event_id or "legacy-test"

    # 1. Human review always wins
    if human_review:
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason="Model requested human review")

    # 2. Unknown actions are DENY (mapped to REVIEW_REQUIRED)
    if action not in ["NO_ACTION", "ENRICH", "ESCALATE", "ISOLATE", "BLOCK"]:
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason=f"Policy fail-closed: unrecognized recommendation '{action}'")

    # 3. Destructive actions always REVIEW
    if action in ["ISOLATE", "BLOCK"]:
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason=f"Policy override: action '{action}' requires human authorization")

    # 4. ESCALATE is always REVIEW
    if action == "ESCALATE":
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason="Policy override: ESCALATE requires human authorization")

    # 5. Untrusted source always REVIEW
    if not authoritative_trusted_source:
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason="Policy override: untrusted source requires human review")

    # 6. Severity band: ONLY LOW is allowed
    if severity != "LOW":
        return PolicyDecision(incident_id=inc_id, authorized_action="REVIEW_REQUIRED", decision_reason=f"Policy override: severity={severity} requires human review")

    # 7. Safe action, trusted, LOW severity -> ALLOW
    return PolicyDecision(incident_id=inc_id, authorized_action=action, decision_reason=f"Policy allowed: {action}")'''

content = re.sub(pattern, new_logic, content, flags=re.DOTALL)

with open("engine/deterministic_policy.py", "w") as f:
    f.write(content)

print("✅ Policy logic updated to match legacy expectations.")
