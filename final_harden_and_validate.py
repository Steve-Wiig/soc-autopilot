import re
from pathlib import Path
import subprocess

print("="*60)
print("STEP 1: STRUCTURAL NEUTRALIZATION (P0-1 & P0-2)")
print("="*60)

# P0-1: Neutralize cloud fallback in model_registry.py
f = Path("engine/model_registry.py")
if f.exists():
    txt = f.read_text()
    if "HARDENED:" not in txt:
        lines = txt.split('\n')
        new_lines = []
        for line in lines:
            # Comment out lines that register openrouter or allow cloud for triage
            if re.search(r'openrouter|cloud.*triage|triage.*cloud|priority.*30.*cloud', line, re.I):
                new_lines.append(f"# HARDENED: Neutralized cloud fallback -> {line}")
            else:
                new_lines.append(line)
        f.write_text('\n'.join(new_lines))
        print("[+] P0-1: Neutralized cloud fallback in model_registry.py")
    else:
        print("[=] P0-1: model_registry.py already hardened.")

# P0-2: Neutralize direct DB mutation in slm_triage_worker.py
f = Path("engine/slm_triage_worker.py")
if f.exists():
    txt = f.read_text()
    if "HARDENED:" not in txt:
        lines = txt.split('\n')
        new_lines = []
        for line in lines:
            # Comment out direct sqlite/DB execution lines
            if re.search(r'sqlite|connect\(|execute\(|commit\(', line, re.I):
                new_lines.append(f"# HARDENED: Neutralized direct DB mutation -> {line}")
            else:
                new_lines.append(line)
        f.write_text('\n'.join(new_lines))
        print("[+] P0-2: Neutralized direct DB mutation in slm_triage_worker.py")
    else:
        print("[=] P0-2: slm_triage_worker.py already hardened.")

print("\n" + "="*60)
print("STEP 2: FINAL VALIDATION SUITE")
print("="*60)

# Run pytest
print("\n[*] Running pytest -q ...")
subprocess.run(["pytest", "-q"])

# Run git checks
print("\n[*] Running git diff --check ...")
subprocess.run(["git", "diff", "--check"])

print("\n[*] Running git status --short ...")
subprocess.run(["git", "status", "--short"])

# Run mission-specific grep checks
print("\n[*] Checking for remaining cloud/openrouter references ...")
subprocess.run('grep -RIn "openrouter\|cloud" engine contracts orchestrator tests || true', shell=True)

print("\n[*] Checking for remaining autonomous git push ...")
subprocess.run('grep -RIn "git push" overnight engine tools tests || true', shell=True)

print("\n[*] Checking for remaining swallowed exceptions ...")
subprocess.run('grep -RIn "except Exception.*pass" overnight engine tools || true', shell=True)

print("\n[*] Checking for remaining hardcoded paths ...")
subprocess.run('grep -RIn "/home/swiig/Documents/soc-autopilot" . || true', shell=True)

print("\n" + "="*60)
print("VALIDATION COMPLETE.")
print("Review the grep output above. Any remaining matches require manual review.")
print("="*60)
