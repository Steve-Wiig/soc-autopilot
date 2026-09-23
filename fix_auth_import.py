with open("engine/writeback/authorization.py", "r") as f:
    content = f.read()

# Add backward compatibility alias at the end of the file
if "issue_writeback_authorization" not in content:
    content += '''

# Backward compatibility alias for existing test suite
def issue_writeback_authorization(
    decision_id: str,
    incident_id: str,
    action: str,
    target: str,
    parameters: dict,
    ttl_minutes: int = 5
) -> Authorization:
    """Alias for create_authorization to maintain compatibility with existing imports."""
    return create_authorization(decision_id, incident_id, action, target, parameters, ttl_minutes)
'''
    with open("engine/writeback/authorization.py", "w") as f:
        f.write(content)

print("✅ issue_writeback_authorization alias added.")
