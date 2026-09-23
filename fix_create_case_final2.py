with open("engine/writeback/so_cases.py", "r") as f:
    lines = f.readlines()

new_lines = []
in_create_case = False
skip_until_next_def = False

for i, line in enumerate(lines):
    if line.strip().startswith("def create_case("):
        in_create_case = True
        # Replace the signature to include **kwargs
        new_lines.append("def create_case(api_url: str, api_key: str, data: Dict[str, Any], draft: bool = False, **kwargs) -> str:\n")
        continue
    
    if in_create_case:
        if line.strip().startswith("def ") or (line.strip() and not line.startswith(" ") and not line.startswith("\t") and not line.startswith("#")):
            in_create_case = False
            new_lines.append(line)
        else:
            # Skip the old body, we'll add the new one
            pass
    else:
        new_lines.append(line)

# Now we need to insert the new body right after the new signature
final_lines = []
for i, line in enumerate(new_lines):
    final_lines.append(line)
    if line.strip().startswith("def create_case("):
        final_lines.append('    """Create a case in SO Cases via API."""\n')
        final_lines.append('    if draft:\n')
        final_lines.append('        return "DRAFT_ID_000"\n')
        final_lines.append('    try:\n')
        final_lines.append('        session = requests.Session()\n')
        final_lines.append('        response = session.post(\n')
        final_lines.append('            f"{api_url}/cases",\n')
        final_lines.append('            headers={"Authorization": f"Bearer {api_key}"},\n')
        final_lines.append('            json=data\n')
        final_lines.append('        )\n')
        final_lines.append('        response.raise_for_status()\n')
        final_lines.append('        return response.json().get("id", "UNKNOWN")\n')
        final_lines.append('    except Exception as e:\n')
        final_lines.append('        raise RuntimeError(f"API call failed: {e}")\n')
        final_lines.append('\n')

with open("engine/writeback/so_cases.py", "w") as f:
    f.writelines(final_lines)

print("✅ Fixed create_case to accept **kwargs")
