with open("engine/writeback/authorization.py", "r") as f:
    content = f.read()

# Ensure WritebackAuthorization alias exists
if "WritebackAuthorization = Authorization" not in content:
    content += "\n\n# Backward compatibility alias for thehive module\nWritebackAuthorization = Authorization\n"

# Ensure parse_writeback_authorization function exists
if "def parse_writeback_authorization" not in content:
    content += '''
def parse_writeback_authorization(data: dict) -> Authorization:
    """Parse and validate writeback authorization from dict."""
    return Authorization(**data)
'''

with open("engine/writeback/authorization.py", "w") as f:
    f.write(content)

print("✅ Fixed WritebackAuthorization exports for thehive module")
