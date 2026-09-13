#!/usr/bin/env python3
import json, shutil, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.consensus_gate import get_consensus
from overnight.llm_client import load_api_keys

ROOT = Path(__file__).parent.parent
LOCAL_PENDING = ROOT / "overnight/oracle_queue/pending"
LOCAL_APPROVED = ROOT / "overnight/oracle_queue/approved"
LOCAL_REJECTED = ROOT / "overnight/oracle_queue/rejected"
BACKLOG = ROOT / "overnight/fix_backlog.json"

def main():
    LOCAL_PENDING.mkdir(parents=True, exist_ok=True)
    LOCAL_APPROVED.mkdir(exist_ok=True)
    LOCAL_REJECTED.mkdir(exist_ok=True)
    
    
    proposals = list(LOCAL_PENDING.glob("*.json"))
    if LOCAL_PENDING.exists():
        proposals.extend(list(LOCAL_PENDING.glob("*.json")))
        
    if not proposals: return
        
    api_keys = load_api_keys()
    
    seen_paths = set()

    for p_file in proposals:
        # Queue enumeration can observe the same path more than once,
        # or a file may disappear between enumeration and processing.
        # Treat that as an idempotent/stale queue observation.
        try:
            path_key = p_file.resolve()
        except OSError:
            path_key = p_file.absolute()

        if path_key in seen_paths:
            continue

        seen_paths.add(path_key)

        if not p_file.is_file():
            continue

        try:
            data = json.loads(p_file.read_text())
        except FileNotFoundError:
            # Another queue transition won the race.
            continue
        proposal_text = data.get("proposal", "")
        print(f"⚖️  Voting on: {p_file.name[:40]}...")
        
        approved, v1, v2 = get_consensus(proposal_text, api_keys)
        data["votes"] = {"judge1": v1, "judge2": v2}
        p_file.write_text(json.dumps(data, indent=2))
        
        if LOCAL_PENDING in p_file.parents:
            dest_approved = LOCAL_APPROVED / p_file.name
            dest_rejected = LOCAL_REJECTED / p_file.name
            LOCAL_APPROVED.mkdir(parents=True, exist_ok=True)
            LOCAL_REJECTED.mkdir(exist_ok=True)
        else:
            dest_approved = LOCAL_APPROVED / p_file.name
            dest_rejected = LOCAL_REJECTED / p_file.name

        if approved:
            shutil.move(str(p_file), str(dest_approved))
            backlog = json.loads(BACKLOG.read_text()) if BACKLOG.exists() else []
            backlog.append({"file": data.get("target_file", ""), "issue": {"description": proposal_text, "category": "performance"}})
            BACKLOG.write_text(json.dumps(backlog, indent=2))
            print(f"   ✅ Promoted to backlog!")
        else:
            shutil.move(str(p_file), str(dest_rejected))
            print(f"   ❌ Rejected: {v1.get('reason', 'Unknown')[:50]}")

if __name__ == "__main__":
    main()
