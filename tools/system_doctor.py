#!/usr/bin/env python3
"""
tools/system_doctor.py
----------------------
Comprehensive read-only diagnostic dashboard for soc-autopilot.
"""
import sys, json, os, subprocess, time
from pathlib import Path
from datetime import datetime
from collections import Counter

ROOT = Path(__file__).parent.parent

def h1(text): print(f"\n{'='*60}\n🔍 {text}\n{'='*60}")

def main():
    print("🏥 soc-autopilot: SYSTEM DIAGNOSTIC REPORT")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. Process State
    h1("PROCESS STATE")
    try:
        pids = subprocess.check_output(["pgrep", "-f", "self_improver.py"], text=True).strip().split('\n')
        if pids and pids[0]:
            print(f"✅ Engine is RUNNING (PIDs: {', '.join(pids)})")
        else:
            print("⚠️ Engine is STOPPED.")
    except Exception:
        print("⚠️ Engine is STOPPED.")

    # 2. Git State
    h1("GIT STATE")
    try:
        branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True).strip()
        last_commit = subprocess.check_output(["git", "log", "-1", "--pretty=format:%h %s"], cwd=ROOT, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        print(f"Branch: {branch}")
        print(f"Last Commit: {last_commit}")
        if dirty:
            print(f"⚠️ Working tree is DIRTY:\n{dirty}")
        else:
            print("✅ Working tree is clean.")
    except Exception as e:
        print(f"Error: {e}")

    # 3. Queue State
    h1("QUEUE STATE")
    backlog = ROOT / "overnight/fix_backlog.json"
    deferred = ROOT / "overnight/fix_backlog_deferred.json"
    pending = ROOT / "overnight/advisory_queue/pending"
    
    try:
        b_count = len(json.loads(backlog.read_text())) if backlog.exists() else 0
        print(f"Fix Backlog: {b_count} items")
    except Exception: print("Fix Backlog: Error reading")
        
    try:
        d_count = len(json.loads(deferred.read_text())) if deferred.exists() else 0
        print(f"Deferred (Poison Pills): {d_count} items")
    except Exception: print("Deferred: Error reading")

    p_count = len(list(pending.glob("*.json"))) if pending.exists() else 0
    print(f"Pending Advisories (Gemini Queue): {p_count} items")

    # 4. Defeat Ledger
    h1("DEFEAT LEDGER (Poison Pills)")
    ledger = ROOT / "overnight/defeat_ledger.jsonl"
    if ledger.exists() and ledger.stat().st_size > 0:
        try:
            counts = Counter()
            for line in ledger.read_text().splitlines():
                if line.strip():
                    evt = json.loads(line)
                    counts[evt.get("file", "unknown")] += 1
            print(f"Total Defeats Recorded: {sum(counts.values())}")
            if counts:
                print("Top 3 Defeated Files:")
                for f, c in counts.most_common(3):
                    print(f"  - {f}: {c} strikes")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("✅ Ledger is empty (No defeats).")

    # 5. Budget State
    h1("API BUDGET STATE")
    try:
        sys.path.insert(0, str(ROOT))
        from overnight.budget_manager import APIBudgetManager
        budget = APIBudgetManager()
        print(budget.report())
    except Exception as e:
        print(f"Error loading budget: {e}")

    # 6. Reasoning Ledger (Black Box)
    h1("REASONING LEDGER (Black Box)")
    local_ledger = ROOT / "overnight/.reasoning_buffer/current.jsonl"
    nas_ledger = Path("/mnt/backup-nas/soc-slm-telemetry/reasoning/reasoning.jsonl")
    
    l_count = len(local_ledger.read_text().splitlines()) if local_ledger.exists() else 0
    print(f"Local Buffer: {l_count} events")
    
    try:
        if nas_ledger.exists() and os.stat("/mnt/backup-nas").st_dev != os.stat("/").st_dev:
            n_count = len(nas_ledger.read_text().splitlines())
            print(f"NAS Archive (/dev/sdc): {n_count} events")
        else:
            print("NAS Archive: Offline or unmounted.")
    except Exception:
        print("NAS Archive: Offline or unmounted.")

    # 7. Recent Logs
    h1("RECENT LOGS (Last 15 lines)")
    log = ROOT / "overnight/drun_continuous.log"
    if log.exists():
        lines = log.read_text().splitlines()
        print("\n".join(lines[-15:]))
    else:
        print("No log file found.")

if __name__ == "__main__":
    main()
