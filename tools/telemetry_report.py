#!/usr/bin/env python3
import json
from pathlib import Path
from collections import defaultdict

NAS_DIR = Path("/mnt/backup-nas/soc-slm-telemetry")
LOCAL_DIR = ROOT / "overnight/.telemetry_buffer"

def load_events():
    events = []
    for d in [NAS_DIR, LOCAL_DIR / "outbox", LOCAL_DIR]:
        if d.exists():
            for f in d.rglob("*.jsonl"):
                try:
                    with open(f) as fp:
                        for line in fp:
                            if line.strip(): events.append(json.loads(line))
                except Exception: pass
    return events

def generate_report(events):
    if not events:
        print("No telemetry data found yet.")
        return

    models = defaultdict(lambda: {"attempts": 0, "first_pass": 0, "repaired": 0, "pytest_pass": 0, "committed": 0})
    runs = defaultdict(list)
    for e in events: runs[e.get("remediation_id", "unknown")].append(e)
        
    for run_id, run_events in runs.items():
        run_events.sort(key=lambda x: x.get("ts", 0))
        model = run_events[0].get("model", "unknown")
        models[model]["attempts"] += len(run_events)
        for e in run_events:
            if e.get("attempt_num") == 1 and e.get("syntax_valid"): models[model]["first_pass"] += 1
            if e.get("attempt_outcome") == "repaired": models[model]["repaired"] += 1
            if e.get("pytest_passed"): models[model]["pytest_pass"] += 1
            if e.get("issue_final_outcome") == "committed": models[model]["committed"] += 1

    print("\n" + "="*75)
    print("soc-autopilot MODEL EFFICACY REPORT")
    print("="*75)
    print(f"{'Model':<25} | {'Attempts':<8} | {'1st-Pass':<8} | {'Repaired':<8} | {'Pytest':<8} | {'Committed':<9}")
    print("-" * 75)
    for model, stats in sorted(models.items()):
        att = stats["attempts"]
        fp = f"{(stats['first_pass']/att)*100:.1f}%" if att else "0%"
        rp = f"{(stats['repaired']/att)*100:.1f}%" if att else "0%"
        pt = f"{(stats['pytest_pass']/att)*100:.1f}%" if att else "0%"
        cm = f"{(stats['committed']/att)*100:.1f}%" if att else "0%"
        print(f"{model:<25} | {att:<8} | {fp:<8} | {rp:<8} | {pt:<8} | {cm:<9}")
    print("="*75 + "\n")

if __name__ == "__main__":
    generate_report(load_events())
