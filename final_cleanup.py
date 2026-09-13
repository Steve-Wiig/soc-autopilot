import re
from pathlib import Path
import subprocess

print("="*60)
print("FINAL CLEANUP & SYNTAX REPAIR")
print("="*60)

# 1. Fix slm_triage_worker.py
print("\n[*] Repairing engine/slm_triage_worker.py...")
# Restore the file first to fix the broken syntax
subprocess.run(["git", "checkout", "engine/slm_triage_worker.py"], check=True)

f = Path("engine/slm_triage_worker.py")
if f.exists():
    txt = f.read_text()
    # Monkey-patch sqlite3.connect to raise an error. 
    # This neutralizes DB authority without breaking multi-line string syntax.
    if "import sqlite3" in txt and "_neutralized_db" not in txt:
        txt = txt.replace(
            "import sqlite3", 
            "import sqlite3\ndef _neutralized_db(*args, **kwargs):\n    raise RuntimeError('Neutralized: Direct DB mutation not allowed')\nsqlite3.connect = _neutralized_db"
        )
        f.write_text(txt)
        print("[+] slm_triage_worker.py repaired and DB authority neutralized.")

# 2. Fix remaining swallowed exceptions
print("\n[*] Fixing remaining swallowed exceptions...")
files_to_fix = [
    "overnight/self_improver.py",
    "engine/consensus_gate.py",
    "engine/telemetry.py",
    "tools/sync_telemetry.py",
    "tools/build_efficacy_matrix.py"
]

for file_path in files_to_fix:
    f = Path(file_path)
    if not f.exists():
        continue
    txt = f.read_text()
    
    # Match `except Exception: pass` (single line) or `except Exception:\n    pass`
    pattern = re.compile(r'^([ \t]*)except\s+Exception\s*(?::\s*pass\b|\s*:\s*\n[ \t]*pass\b)', re.MULTILINE)
    
    def replacer(match):
        indent = match.group(1)
        return (
            f"{indent}except Exception as e:\n"
            f"{indent}    # HARDENED: Fail closed with telemetry\n"
            f"{indent}    import logging\n"
            f"{indent}    logging.error(f'CONTROL-PLANE FAILURE in {f.name}: {{e}}')\n"
            f"{indent}    raise"
        )
        
    if pattern.search(txt):
        txt = pattern.sub(replacer, txt)
        f.write_text(txt)
        print(f"  [+] Fixed swallowed exceptions in {file_path}")

# 3. Fix hardcoded paths in shell scripts
print("\n[*] Fixing hardcoded paths in overnight shell scripts...")
sh_files = list(Path("overnight").glob("*.sh"))
for f in sh_files:
    txt = f.read_text()
    if "/home/swiig/Documents/soc-autopilot" in txt:
        # Replace the hardcoded cd with a portable relative cd
        txt = txt.replace("cd /home/swiig/Documents/soc-autopilot", 'cd "$(dirname "$0")/.."')
        f.write_text(txt)
        print(f"  [+] Fixed hardcoded path in {f.name}")

print("\n" + "="*60)
print("CLEANUP COMPLETE. Running final validation...")
print("="*60)

# Run pytest collection to ensure syntax is valid
print("\n[*] Verifying pytest collection...")
subprocess.run(["pytest", "-q", "--collect-only"])

# Final grep checks
print("\n[*] Final check for hardcoded paths in source...")
subprocess.run('grep -RIn "/home/swiig/Documents/soc-autopilot" engine tools overnight orchestrator contracts tests || echo "CLEAN"', shell=True)

print("\n[*] Final check for swallowed exceptions in source...")
subprocess.run('grep -RIn "except Exception.*pass" engine tools overnight orchestrator contracts tests || echo "CLEAN"', shell=True)

