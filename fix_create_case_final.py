import re

with open("engine/writeback/so_cases.py", "r") as f:
    content = f.read()

# Find and replace the create_case function using regex
pattern = r'def create_case\(.*?\n(?:.*?\n)*?raise RuntimeError\(f"API call failed: \{e\}"\)'

new_func = '''def create_case(api_url: str, api_key: str, data: Dict[str, Any], draft: bool = False, **kwargs) -> str:
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

content = re.sub(pattern, new_func, content, flags=re.MULTILINE)

with open("engine/writeback/so_cases.py", "w") as f:
    f.write(content)

print("✅ Fixed create_case to accept **kwargs using regex")
