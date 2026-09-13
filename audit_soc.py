import os, re
from pathlib import Path

root = Path('.')
print("="*60)
print("SOC-AUTOPILOT READ-ONLY AUDIT (Robust)")
print("="*60)

issues_found = 0

def safe_read(filepath):
    try:
        return filepath.read_text(encoding='utf-8')
    except (UnicodeDecodeError, Exception):
        return None

# P0-1: Cloud in production roles
f = root / "engine" / "model_registry.py"
txt = safe_read(f)
if txt:
    if re.search(r'openrouter|cloud.*triage|triage.*priority.*30', txt, re.I):
        print("[!] P0-1: model_registry.py may allow cloud fallback for triage.")
        issues_found += 1
    else:
        print("[OK] P0-1: model_registry.py looks clean.")

# P0-2: SLM Worker direct DB mutation
f = root / "engine" / "slm_triage_worker.py"
txt = safe_read(f)
if txt:
    if "sqlite" in txt.lower() or "execute(" in txt.lower():
        print("[!] P0-2: slm_triage_worker.py contains direct DB/queue mutation.")
        issues_found += 1
    else:
        print("[OK] P0-2: slm_triage_worker.py looks clean.")

# P0-3: Shadow Canary mixed returns
f = root / "tools" / "shadow_canary.py"
txt = safe_read(f)
if txt:
    if re.search(r'return\s+False\s*$|return\s+\(False', txt, re.M):
        print("[!] P0-3: shadow_canary.py has mixed/ambiguous return types.")
        issues_found += 1
    else:
        print("[OK] P0-3: shadow_canary.py return types look strict.")

# P0-4: Autonomous git push
print("[*] P0-4: Checking for autonomous git push...")
for f in root.rglob("*.py"):
    if "overnight" in str(f) or "engine" in str(f):
        txt = safe_read(f)
        if txt and ("git push" in txt or ("subprocess" in txt and "push" in txt)):
            print(f"  [!] Found potential push in: {f}")
            issues_found += 1

# P1-3: Hardcoded paths
print("[*] P1-3: Checking for hardcoded paths...")
for f in root.rglob("*.py"):
    txt = safe_read(f)
    if txt and "/home/swiig" in txt and f.name != "audit_soc.py":
        print(f"  [!] Hardcoded path in: {f}")
        issues_found += 1

# P1-4: Swallowed exceptions
print("[*] P1-4: Checking for swallowed exceptions...")
for f in root.rglob("*.py"):
    txt = safe_read(f)
    if txt and re.search(r'except\s+Exception\s*:\s*pass', txt):
        print(f"  [!] Swallowed exception in: {f}")
        issues_found += 1

print("="*60)
if issues_found == 0:
    print("RESULT: No obvious vulnerabilities found. System may already be hardened.")
else:
    print(f"RESULT: Found {issues_found} potential issue(s). Review before patching.")
print("="*60)
