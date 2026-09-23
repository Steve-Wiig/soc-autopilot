with open("engine/writeback/so_cases.py", "r") as f:
    content = f.read()

# 1. Ensure _HTTP_SESSION is defined at module level
if "_HTTP_SESSION = requests.Session()" not in content:
    content = content.replace(
        "from typing import Dict, Any\n",
        "from typing import Dict, Any\n\n_HTTP_SESSION = requests.Session()\n"
    )

# 2. Replace create_case to use the module-level _HTTP_SESSION
old_create = '''def create_case(api_url: str, api_key: str, data: Dict[str, Any], draft: bool = False, **kwargs) -> str:
    """Create a case in SO Cases via API."""
    if draft:
        return "DRAFT_ID_000"
    try:
        session = requests.Session()
        response = session.post(
            f"{api_url}/cases",
            headers={"Authorization": f"Bearer {api_key}"},
            json=data
        )
        response.raise_for_status()
        return response.json().get("id", "UNKNOWN")
    except Exception as e:
        raise RuntimeError(f"API call failed: {e}")'''

new_create = '''def create_case(api_url: str, api_key: str, data: Dict[str, Any], draft: bool = False, **kwargs) -> str:
    """Create a case in SO Cases via API."""
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

content = content.replace(old_create, new_create)

with open("engine/writeback/so_cases.py", "w") as f:
    f.write(content)

print("✅ Fixed create_case to use module-level _HTTP_SESSION for mock compatibility")
