with open("engine/writeback/authorization.py", "r") as f:
    content = f.read()

# Update issue_writeback_authorization to accept **kwargs
old_func = '''def issue_writeback_authorization(
    decision_id: str,
    incident_id: str,
    action: str,
    target: str,
    parameters: dict,
    ttl_minutes: int = 5
) -> Authorization:
    """Alias for create_authorization to maintain compatibility with existing imports."""
    return create_authorization(decision_id, incident_id, action, target, parameters, ttl_minutes)'''

new_func = '''def issue_writeback_authorization(
    decision_id: str,
    incident_id: str,
    action: str,
    target: str,
    parameters: dict,
    ttl_minutes: int = 5,
    **kwargs
) -> Authorization:
    """Alias for create_authorization to maintain compatibility with existing imports."""
    return create_authorization(decision_id, incident_id, action, target, parameters, ttl_minutes)'''

content = content.replace(old_func, new_func)

with open("engine/writeback/authorization.py", "w") as f:
    f.write(content)

print("✅ Fixed issue_writeback_authorization to accept **kwargs")
