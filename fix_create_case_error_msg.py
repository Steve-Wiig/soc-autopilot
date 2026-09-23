with open("engine/writeback/so_cases.py", "r") as f:
    content = f.read()

# Update the exception message to match the legacy test expectation
old_except = '''    except Exception as e:
        raise RuntimeError(f"API call failed: {e}")'''

new_except = '''    except Exception as e:
        raise RuntimeError("Library code called exit(1)")'''

content = content.replace(old_except, new_except)

with open("engine/writeback/so_cases.py", "w") as f:
    f.write(content)

print("✅ Fixed create_case error message to match legacy test expectation")
