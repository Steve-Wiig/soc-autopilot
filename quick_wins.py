import re
from pathlib import Path

print("="*60)
print("5-MINUTE QUICK WINS")
print("="*60)

# 1. Delete backup files created during our patching
print("\n[*] Cleaning up backup files...")
deleted = 0
for pattern in ["*.bak*", "*.gated-backup", "*.backup-*"]:
    for f in Path(".").rglob(pattern):
        if f.is_file():
            f.unlink()
            deleted += 1
print(f"  Deleted {deleted} backup files.")

# 2. Fix hardcoded paths in remaining Python source files
print("\n[*] Fixing hardcoded paths in Python source...")
path_fixes = {
    "engine/telemetry.py": ('Path("/home/swiig/Documents/soc-autopilot/overnight/.telemetry_buffer")', 'Path(__file__).resolve().parent.parent / "overnight" / ".telemetry_buffer"'),
    "tools/sync_telemetry.py": ('Path("/home/swiig/Documents/soc-autopilot")', 'Path(__file__).resolve().parent.parent'),
    "tools/telemetry_report.py": ('Path("/home/swiig/Documents/soc-autopilot/overnight/.telemetry_buffer")', 'Path(__file__).resolve().parent.parent / "overnight" / ".telemetry_buffer"'),
    "engine/defeat_ledger.py": ("Path('/home/swiig/Documents/soc-autopilot/overnight/defeat_ledger.jsonl')", "Path(__file__).resolve().parent.parent / 'overnight' / 'defeat_ledger.jsonl'"),
}
for file_path, (old, new) in path_fixes.items():
    f = Path(file_path)
    if f.exists():
        txt = f.read_text()
        if old in txt:
            txt = txt.replace(old, new)
            f.write_text(txt)
            print(f"  [+] Fixed path in {file_path}")

# 3. Nuke remaining `except Exception: pass` in active source
print("\n[*] Nuking remaining swallowed exceptions in active source...")
active_dirs = ["engine", "tools", "overnight", "orchestrator", "contracts"]
for d in active_dirs:
    for f in Path(d).rglob("*.py"):
        txt = f.read_text()
        # Match single line or multi-line
        pattern = re.compile(r'([ \t]*)except\s+Exception\s*:\s*\n?[ \t]*pass\b')
        if pattern.search(txt):
            def replacer(match):
                indent = match.group(1)
                return f"{indent}except Exception as e:\n{indent}    import logging\n{indent}    logging.error(f'CONTROL-PLANE FAILURE in {f.name}: {{e}}')\n{indent}    raise"
            
            new_txt = pattern.sub(replacer, txt)
            if new_txt != txt:
                f.write_text(new_txt)
                print(f"  [+] Fixed swallowed exception in {f}")

# 4. Fix trailing whitespace reported by git diff --check
print("\n[*] Fixing trailing whitespace...")
for f in [Path("overnight/self_improver.py"), Path("tools/dashboard.py")]:
    if f.exists():
        txt = f.read_text()
        new_txt = re.sub(r'[ \t]+$', '', txt, flags=re.MULTILINE)
        if new_txt != txt:
            f.write_text(new_txt)
            print(f"  [+] Stripped trailing whitespace in {f}")

print("\n" + "="*60)
print("QUICK WINS COMPLETE.")
print("Run: git status --short")
print("Run: pytest -q")
print("="*60)
