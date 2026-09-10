"""
tools/build_efficacy_matrix.py
------------------------------
Parses JSONL telemetry to calculate Model Efficacy Scores.
Outputs a ranked priority list to engine/model_priority.json.
"""
import json
from pathlib import Path
from collections import defaultdict

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.telemetry_identity import deduplicate_events


ROOT = Path(__file__).parent.parent

NAS_DIR = Path("/mnt/backup-nas/soc-slm-telemetry")
BUFFER_DIR = ROOT / "overnight" / ".telemetry_buffer"
OUTBOX_DIR = BUFFER_DIR / "outbox"
PRIORITY_FILE = ROOT / "engine" / "model_priority.json"

def gather_events():
    events = []
    for p in [NAS_DIR, BUFFER_DIR]:
        if p.exists():
            for f in p.rglob("*.jsonl"):
                for line in f.read_text().splitlines():
                    if line.strip():
                        try: events.append(json.loads(line))
                        except: pass
    return deduplicate_events(events)

def calculate_metrics(events):
    remeds = defaultdict(list)
    for e in events:
        if "remediation_id" in e and e.get("model") and e.get("model") != "unknown":
            remeds[e["remediation_id"]].append(e)
            
    model_stats = defaultdict(lambda: {
        "calls": 0, "gen_fails": 0, 
        "attempt1_calls": 0, "attempt1_commits": 0,
        "total_commits": 0
    })
    
    for rid, evts in remeds.items():
        evts.sort(key=lambda x: x.get("ts", 0))
        
        for e in evts:
            if e.get("stage") == "generation":
                model = e["model"]
                stats = model_stats[model]
                stats["calls"] += 1
                
                outcome = e.get("attempt_outcome", "")
                attempt = e.get("attempt_num", 1)
                
                if outcome == "generation_fail":
                    stats["gen_fails"] += 1
                elif attempt == 1:
                    stats["attempt1_calls"] += 1
                    
        # Credit the winning model
        final_outcome = any(e.get("issue_final_outcome") == "committed" for e in evts)
        if final_outcome:
            for e in evts:
                if e.get("stage") == "generation" and e.get("attempt_outcome") in ["syntax_success", "repaired"]:
                    model = e["model"]
                    model_stats[model]["total_commits"] += 1
                    if e.get("attempt_num") == 1:
                        model_stats[model]["attempt1_commits"] += 1
                    break 
                    
    return model_stats

def score_and_rank(stats):
    rankings = []
    for model, s in stats.items():
        if s["calls"] < 3: continue 
        
        availability = (s["calls"] - s["gen_fails"]) / s["calls"]
        first_pass = (s["attempt1_commits"] / s["attempt1_calls"]) if s["attempt1_calls"] > 0 else 0
        overall = s["total_commits"] / s["calls"]
        
        # Score: 40% Availability, 40% First-Pass, 20% Overall Success
        score = (availability * 0.4) + (first_pass * 0.4) + (overall * 0.2)
        rankings.append({
            "model": model,
            "score": round(score, 3),
            "calls": s["calls"],
            "availability": round(availability, 2),
            "first_pass": round(first_pass, 2)
        })
        
    rankings.sort(key=lambda x: x["score"], reverse=True)
    return rankings

def main():
    events = gather_events()
    if not events:
        print("⚠️ No telemetry events found yet. Let the loop run for a bit.")
        return
        
    stats = calculate_metrics(events)
    rankings = score_and_rank(stats)
    
    print("\n=== MODEL EFFICACY MATRIX ===")
    print(f"{'Model':<45} | {'Score':<6} | {'Calls':<6} | {'Avail':<6} | {'1st-Pass':<8}")
    print("-" * 85)
    for r in rankings:
        print(f"{r['model']:<45} | {r['score']:<6} | {r['calls']:<6} | {r['availability']:<6} | {r['first_pass']:<8}")
        
    if rankings:
        priority_list = [r["model"] for r in rankings]
        PRIORITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        PRIORITY_FILE.write_text(json.dumps({"models": priority_list, "matrix": rankings}, indent=2))
        print(f"\n✅ Priority list updated in {PRIORITY_FILE}")

if __name__ == "__main__":
    main()
