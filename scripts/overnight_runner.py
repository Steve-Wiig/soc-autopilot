#!/usr/bin/env python3
"""
Overnight Runner: Uses propose_code.py (the proven path that works with free tier).
Runs through the task list, checking budget and safety gates.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from overnight.budget_manager import APIBudgetManager

TASKS = [
    (
        "engine/alert_correlator.py",
        "Create engine/alert_correlator.py and contracts/incident_models.py. Build an AlertCorrelator that groups alerts into incidents based on time window (5 min), source IP, and user. Incident model must have incident_id (UUID v4), severity (Enum: low, medium, high, critical), correlated_alerts (list), and summary (str). Create tests/test_alert_correlator.py.|engine/alert_correlator.py contracts/incident_models.py tests/test_alert_correlator.py"
    ),
    (
        "engine/wazuh_response.py",
        "Create engine/wazuh_response.py. Build a WazuhActiveResponseGenerator that takes an alert dict with source_ip and generates a safe bash script for Wazuh active response (e.g., adding attacker IP to hosts.deny blocklist). Must validate input, sanitize IPs, and include safety comments. Create tests/test_wazuh_response.py.|engine/wazuh_response.py tests/test_wazuh_response.py"
    ),
    (
        "engine/sigma_generator.py",
        "Create engine/sigma_generator.py. Build a SigmaRuleGenerator that takes an incident summary dict (with fields: source_ip, attack_type, affected_service) and generates a valid Sigma detection rule in YAML format. The rule must include title, description, logsource, detection with selection and condition. Create tests/test_sigma_generator.py.|engine/sigma_generator.py tests/test_sigma_generator.py"
    ),
]

def run_task(task_name: str, prompt: str, files_str: str) -> bool:
    print(f"\n{'='*60}")
    print(f"TASK: {task_name}")
    print(f"{'='*60}")

    # Ensure proposals directory exists
    (ROOT / "proposals").mkdir(parents=True, exist_ok=True)

    run_start = time.time()

    # FIX: Split the files string into a list of arguments
    files_list = files_str.split()
    
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "propose_code.py"),
        "--auto",
        prompt,
        "--files",
    ]
    # Extend command with the list of files (e.g. --files file1 file2)
    cmd.extend(files_list)

    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=700)

        # DEBUG: If propose_code.py failed, show why
        if result.returncode != 0:
            print(f"❌ propose_code.py failed with code {result.returncode}")
            print(f"STDERR: {result.stderr[-500:]}")
            return False

        proposals_dir = ROOT / "proposals"
        new_patches = [p for p in proposals_dir.glob("prop-*.patch") if p.stat().st_mtime > run_start]
        new_patches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if not new_patches:
            print(f"❌ No patch generated")
            print(f"STDOUT tail: {result.stdout[-300:]}")
            return False

        latest_patch = new_patches[0]
        print(f"✅ Patch: {latest_patch.name}")

        apply_result = subprocess.run(
            ["git", "apply", "--ignore-whitespace", str(latest_patch)],
            cwd=ROOT, capture_output=True, text=True,
        )

        if apply_result.returncode != 0:
            print(f"❌ Apply failed: {apply_result.stderr}")
            return False

        # Syntax check
        for f in files_list:
            if f.endswith(".py") and (ROOT / f).exists():
                check = subprocess.run(["python3", "-m", "py_compile", f], cwd=ROOT, capture_output=True)
                if check.returncode != 0:
                    print(f"❌ Syntax error in {f}")
                    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=ROOT, capture_output=True)
                    subprocess.run(["git", "clean", "-fd"], cwd=ROOT, capture_output=True)
                    return False

        # Test check
        test_result = subprocess.run(
            ["python3", "-m", "pytest", "tests/", "-q", "--tb=line", "--ignore=tests/test_cer_critic.py"],
            cwd=ROOT, capture_output=True, text=True,
        )

        if test_result.returncode != 0:
            print(f"❌ Tests failed")
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=ROOT, capture_output=True)
            subprocess.run(["git", "clean", "-fd"], cwd=ROOT, capture_output=True)
            return False

        # Commit
        subprocess.run(["git", "add", "-A"], cwd=ROOT, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"feat: add {task_name}"], cwd=ROOT, capture_output=True)
        print(f"✅ SUCCESS: {task_name}")
        return True

    except subprocess.TimeoutExpired:
        print(f"❌ Timeout")
        return False
    except Exception as e:
        print(f"❌ {e}")
        return False

if __name__ == "__main__":
    budget = APIBudgetManager()
    passed = 0
    failed = 0

    print("🌙 OVERNIGHT RUNNER STARTED")
    print(f"   Model: nemotron-3.5-lightning:free")
    print(f"   Tasks: {len(TASKS)}")
    print(f"   Budget: {budget.get_remaining('openrouter')}")

    for task_name, full_prompt in TASKS:
        # Budget check before each task
        if not budget.can_proceed("openrouter"):
            print("\n🛑 Budget exhausted. Stopping safely.")
            break

        # Split prompt and files
        parts = full_prompt.rsplit("|", 1)
        prompt = parts[0]
        files_str = parts[1] if len(parts) > 1 else task_name

        if run_task(task_name, prompt, files_str):
            passed += 1
        else:
            failed += 1
        
        # Small delay between tasks
        time.sleep(2)

    print(f"\n{'='*60}")
    print(f"🌙 OVERNIGHT RUNNER COMPLETE")
    print(f"   Passed: {passed} | Failed: {failed}")
    print(f"{'='*60}")

    # Write morning report
    report = ROOT / "proposals" / "MORNING_REPORT.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(f"# Morning Report\n- Passed: {passed}\n- Failed: {failed}\n")
    print(f"📋 Report: {report}")
