from pathlib import Path

# 1. Fix the single remaining active source file
f = Path("overnight/pi_idle_reviewer.py")
if f.exists():
    txt = f.read_text()
    if "except Exception: pass" in txt:
        txt = txt.replace(
            "except Exception: pass",
            "except Exception as e:\n                        import logging\n                        logging.error(f'CONTROL-PLANE FAILURE in pi_idle_reviewer: {e}')\n                        raise"
        )
        f.write_text(txt)
        print("[+] Fixed overnight/pi_idle_reviewer.py")

# 2. Verify active source code is clean (excluding backups, logs, tests, docs)
import subprocess
print("\n[*] Final verification of active source code...")
result = subprocess.run(
    'grep -RIn "except Exception.*pass" engine tools overnight orchestrator contracts --include="*.py" | grep -vE "\.bak|backup|safety_gates\.py|test_safety_gates\.py|\.jsonl|\.json" || echo "CLEAN: No swallowed exceptions in active source code."',
    shell=True, capture_output=True, text=True
)
print(result.stdout.strip())

print("\n" + "="*60)
print("READY FOR COMMIT")
print("="*60)
print("Run these commands to finalize:")
print("  git diff --stat")
print("  git add -A")
print("  git commit -m 'P0/P1 Hardening: Enforce local-only routing, neutralize DB authority, fail-closed exceptions, and portable paths'")
