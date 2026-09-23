# 1. Update engine/soc_pipeline.py to pass authoritative_trusted_source=True
with open("engine/soc_pipeline.py", "r") as f:
    content = f.read()

content = content.replace(
    "decision = evaluate_deterministic_policy(envelope)",
    "decision = evaluate_deterministic_policy(envelope, authoritative_trusted_source=True)"
)

with open("engine/soc_pipeline.py", "w") as f:
    f.write(content)

# 2. Update tests/test_telemetry_and_policy.py to pass authoritative_trusted_source=True
with open("tests/test_telemetry_and_policy.py", "r") as f:
    content = f.read()

content = content.replace(
    "decision = evaluate_deterministic_policy(envelope)",
    "decision = evaluate_deterministic_policy(envelope, authoritative_trusted_source=True)"
)

with open("tests/test_telemetry_and_policy.py", "w") as f:
    f.write(content)

# 3. Fix engine/writeback/so_cases.py to use requests.post directly for mocking
with open("engine/writeback/so_cases.py", "r") as f:
    content = f.read()

# Replace the Session logic with direct requests.post
old_create_case = '''def create_case(api_url: str, api_key: str, data: Dict[str, Any], draft: bool = False) -> str:
    """Create a case in SO Cases via API."""
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        import requests
        _HTTP_SESSION = requests.Session()

    if draft:
        return "DRAFT_ID_000"

    try:
        response = _HTTP_SESSION.post(
            f"{api_url}/cases",
            headers={"Authorization": f"Bearer {api_key}"},
            json=data
        )
        response.raise_for_status()
        return response.json().get("id", "UNKNOWN")
    except Exception as e:
        raise RuntimeError(f"API call failed: {e}")'''

new_create_case = '''def create_case(api_url: str, api_key: str, data: Dict[str, Any], draft: bool = False) -> str:
    """Create a case in SO Cases via API."""
    if draft:
        return "DRAFT_ID_000"

    try:
        response = requests.post(
            f"{api_url}/cases",
            headers={"Authorization": f"Bearer {api_key}"},
            json=data
        )
        response.raise_for_status()
        return response.json().get("id", "UNKNOWN")
    except Exception as e:
        raise RuntimeError(f"API call failed: {e}")'''

content = content.replace(old_create_case, new_create_case)

# Remove _HTTP_SESSION references
content = content.replace("global _HTTP_SESSION\n", "")
content = content.replace("_HTTP_SESSION = None\n", "")

with open("engine/writeback/so_cases.py", "w") as f:
    f.write(content)

print("✅ Final 5 test fixes applied.")
