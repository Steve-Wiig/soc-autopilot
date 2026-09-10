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

NAS_BASE = Path("/mnt/backup-nas/soc-slm-telemetry/oracle_queue")
NAS_PENDING = NAS_BASE / "pending"
NAS_APPROVED = NAS_BASE / "approved"
NAS_REJECTED = NAS_BASE / "rejected"

def evacuate_if_needed():
    """Moves Oracle data to NAS if local pending exceeds 50MB."""
    if not LOCAL_PENDING.exists(): return
    total_size = sum(f.stat().st_size for f in LOCAL_PENDING.rglob("*") if f.is_file())
    
    if total_size > 50 * 1024 * 1024: # 50MB Threshold
        try:
            # NAS Guardrail
            if os.stat("/mnt/backup-nas").st_dev != os.stat("/").st_dev:
                NAS_PENDING.mkdir(parents=True, exist_ok=True)
                count = 0
                for f in LOCAL_PENDING.glob("*.json"):
                    shutil.move(str(f), str(NAS_PENDING / f.name))
                    count += 1
                print(f"🚚 EVACUATED {count} Oracle files ({total_size // (1024*1024)}MB) to NAS.")
        except Exception:
            pass # Fail-open: NAS offline, data stays local

def main():
    LOCAL_PENDING.mkdir(parents=True, exist_ok=True)
    LOCAL_APPROVED.mkdir(exist_ok=True)
    LOCAL_REJECTED.mkdir(exist_ok=True)
    
    evacuate_if_needed()
    
    proposals = list(LOCAL_PENDING.glob("*.json"))
    if NAS_PENDING.exists():
        proposals.extend(list(NAS_PENDING.glob("*.json")))
        
    if not proposals: return
        
    api_keys = load_api_keys()
    
    for p_file in proposals:
        data = json.loads(p_file.read_text())
        proposal_text = data.get("proposal", "")
        print(f"⚖️  Voting on: {p_file.name[:40]}...")
        
        approved, v1, v2 = get_consensus(proposal_text, api_keys)
        data["votes"] = {"judge1": v1, "judge2": v2}
        p_file.write_text(json.dumps(data, indent=2))
        
        if NAS_PENDING in p_file.parents:
            dest_approved = NAS_APPROVED / p_file.name
            dest_rejected = NAS_REJECTED / p_file.name
            NAS_APPROVED.mkdir(parents=True, exist_ok=True)
            NAS_REJECTED.mkdir(exist_ok=True)
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
