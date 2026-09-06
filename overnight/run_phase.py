#!/usr/bin/env python3
"""
Wrapper to run different task phases without modifying phase6_generate.py.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(str(ROOT))
TASKS_BACKUP = ROOT / "overnight" / "tasks_phase6.json.backup"

def run_phase(phase_file):
    """Temporarily swap task files and run phase6_generate.py"""
    tasks_file = ROOT / "overnight" / "tasks_phase6.json"
    target_file = ROOT / "overnight" / phase_file
    
    if not target_file.exists():
        print(f"ERROR: {phase_file} not found")
        return False
    
    # Backup current tasks
    if tasks_file.exists():
        shutil.copy(tasks_file, TASKS_BACKUP)
    
    # Swap in the target tasks
    shutil.copy(target_file, tasks_file)
    print(f"Using tasks from: {phase_file}")
    
    # Run the generator
    import subprocess
    result = subprocess.run(
        [sys.executable, "overnight/phase6_generate.py"],
        cwd=str(ROOT)
    )
    
    # Restore original tasks
    if TASKS_BACKUP.exists():
        shutil.copy(TASKS_BACKUP, tasks_file)
    
    return result.returncode == 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 overnight/run_phase.py <phase_file>")
        print("Examples:")
        print("  python3 overnight/run_phase.py tasks_phase8.json")
        print("  python3 overnight/run_phase.py tasks_phase10.json")
        print("  python3 overnight/run_phase.py tasks_phase11.json")
        sys.exit(1)
    
    phase_file = sys.argv[1]
    success = run_phase(phase_file)
    sys.exit(0 if success else 1)
