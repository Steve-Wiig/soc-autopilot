with open("engine/writeback/so_cases.py", "r") as f:
    content = f.read()

# Replace None initialization with actual Session at module level
content = content.replace(
    "_HTTP_SESSION = None",
    "_HTTP_SESSION = requests.Session()"
)

# Remove lazy initialization from inside create_case
old_lazy = '''    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        _HTTP_SESSION = requests.Session()
'''
content = content.replace(old_lazy, "")

with open("engine/writeback/so_cases.py", "w") as f:
    f.write(content)

print("✅ Fixed _HTTP_SESSION initialization")
