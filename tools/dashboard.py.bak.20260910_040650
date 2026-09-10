#!/usr/bin/env python3
import argparse
import subprocess, json, sys, os
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
NAS_BASE = Path("/mnt/backup-nas/soc-slm-telemetry/oracle_queue")

def h1(text): print(f"\n=== {text} ===")
def run(cmd): return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

def count_dir(path): return len(list(path.glob("*.json"))) if path.exists() else 0
def get_size_mb(path): return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) // (1024*1024) if path.exists() else 0

def _print_scorecard(label, scorecard, category=False):
    print(f"   [{label}]")
    for key, icon in (
        ("applied", "🟢"),
        ("stale", "⚪"),
        ("escalated", "🟡"),
        ("rejected", "🔴"),
    ):
        print(f"   {icon} {key.upper():10s}: {scorecard[key]}")
    print(f"   Total decisions: {scorecard['total_decisions']}")
    print(f"   Success rate:    {scorecard['success_rate']}%")
    print(f"   Proven patterns: {scorecard['proven_fix_count']} stored")
    print(f"   Trend:           {scorecard['trend']}")

    malformed = scorecard.get("malformed_timestamps", 0)
    if malformed:
        print(f"   ⚠️ Malformed timestamps skipped: {malformed}")

    if category:
        print("   By category:")
        for cat, stats in sorted(scorecard["category_breakdown"].items()):
            total = sum(stats.get(k, 0) for k in (
                "applied", "rejected", "escalated", "stale"
            ))
            print(
                f"     {cat:20s}: "
                f"{stats.get('applied', 0)}✅ "
                f"{stats.get('rejected', 0)}❌ "
                f"{stats.get('escalated', 0)}🟡 "
                f"({total} total)"
            )


def main():
    parser = argparse.ArgumentParser(
        description="soc-autopilot unified system dashboard"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Recent scorecard window in days (default: 7)",
    )
    args = parser.parse_args()

    if args.days < 0:
        parser.error("--days must be >= 0")

    print("=== 📊 UNIFIED SYSTEM DASHBOARD ===")
    
    # 1. ORACLE SWARM
    h1("🧠 ORACLE SWARM CONSENSUS GATE")
    local_p = count_dir(ROOT / "overnight/oracle_queue/pending")
    nas_p = count_dir(NAS_BASE / "pending")
    local_a = count_dir(ROOT / "overnight/oracle_queue/approved")
    local_r = count_dir(ROOT / "overnight/oracle_queue/rejected")
    local_size = get_size_mb(ROOT / "overnight/oracle_queue/pending")
    
    print(f"⏳ Pending 2-LLM Vote: {local_p + nas_p} (Local: {local_p} [{local_size}MB], NAS: {nas_p})")
    print(f"✅ Unanimously Approved: {local_a + count_dir(NAS_BASE / 'approved')}")
    print(f"❌ Rejected by Supreme Court: {local_r + count_dir(NAS_BASE / 'rejected')}")

    if (local_p + nas_p) > 0:
        print("\n⚖️  Running Consensus Gate...")
        subprocess.run([sys.executable, str(ROOT / "tools/process_oracle.py")])

    # 1b. IMPROVEMENT LEDGER (Decision Provenance)
    h1("📊 IMPROVEMENT LEDGER")
    ledger_path = ROOT / "overnight" / "improvement_ledger.jsonl"
    if ledger_path.exists():
        import json
        from collections import Counter
        statuses = Counter()
        for line in ledger_path.read_text().strip().split("\n"):
            if line.strip():
                try:
                    entry = json.loads(line)
                    statuses[entry.get("status", "UNKNOWN")] += 1
                except:
                    pass
        total = sum(statuses.values())
        print(f"   Total decisions: {total}")
        for status in ["APPLIED", "STALE", "ESCALATED", "REJECTED"]:
            count = statuses.get(status, 0)
            icon = {"APPLIED": "🟢", "STALE": "⚪", "ESCALATED": "🟡", "REJECTED": "🔴"}.get(status, "❓")
            print(f"   {icon} {status:10s}: {count}")
    else:
        print("   No ledger entries yet.")

    # 1c. SELF-IMPROVEMENT SCORECARD
    h1("📈 SELF-IMPROVEMENT SCORECARD")

    from overnight.self_improver import compute_scorecard

    lifetime = compute_scorecard()
    recent = compute_scorecard(days=args.days)

    _print_scorecard(
        "LIFETIME",
        lifetime,
        category=True,
    )
    print("")
    _print_scorecard(
        f"LAST {args.days} DAYS",
        recent,
    )

    # 2. DRAIN PROCESS
    h1("🔄 DRAIN PROCESS")
    pids = run("pgrep -f 'self_improver.py'").split('\n')
    pids = [p for p in pids if p]
    if pids: print(f"   🟢 RUNNING (PIDs: {', '.join(pids)})")
    else: print("   🔴 STOPPED")
    
    # 3. QUEUE STATUS
    # 🍓 EDGE WORKER STATUS
    h1("🍓 EDGE WORKER STATUS")
    try:
        gen_status = subprocess.run(["systemctl", "is-active", "pi-generator"], capture_output=True, text=True).stdout.strip()
        gen_icon = "🟢" if gen_status == "active" else "🔴"
        print(f"   {gen_icon} Generator: {gen_status}")
        
        crit_status = subprocess.run(["systemctl", "is-active", "pi-worker"], capture_output=True, text=True).stdout.strip()
        crit_icon = "🟢" if crit_status == "active" else "🔴"
        print(f"   {crit_icon} Critic:    {crit_status}")
        
        pi_patches = ROOT / "overnight" / "pi_patches.jsonl"
        if pi_patches.exists():
            count = sum(1 for l in pi_patches.read_text().strip().split('\n') if l.strip())
            print(f"   📦 Pending Pi Patches: {count}")
        else:
            print("   📦 Pending Pi Patches: 0")
    except Exception as e:
        print(f"   ⚠️ Could not check Pi status: {e}")
    

    h1("📥 QUEUE STATUS")
    backlog = json.loads((ROOT / "overnight/fix_backlog.json").read_text()) if (ROOT / "overnight/fix_backlog.json").exists() else []
    deferred = json.loads((ROOT / "overnight/fix_backlog_deferred.json").read_text()) if (ROOT / "overnight/fix_backlog_deferred.json").exists() else []
    print(f"   Active    : {len(backlog)}")
    print(f"   Deferred  : {len(deferred)}")

    # 4. LIVE ACTIVITY
    h1("📈 LIVE ACTIVITY (Last 10 lines)")
    print(run("tail -n 10 overnight/drun_continuous.log 2>/dev/null"))
    
    # 5. DISK HEALTH
    h1("💾 DISK HEALTH (NAS Check)")
    print(run("df -h / /mnt/docker-data /mnt/backup-nas 2>/dev/null | grep -v tmpfs"))
    
    # 6. RECENT FIXES
    h1("🛠️ RECENT FIXES")
    print(run("git log -5 --oneline"))
    
    # 7. TEST SUITE
    h1("🧪 TEST SUITE (Post-Consensus)")
    res = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=line", "tests/"], cwd=ROOT, capture_output=True, text=True)
    lines = res.stdout.strip().split('\n')
    print('\n'.join(lines[-3:]) if len(lines) >= 3 else res.stdout)

if __name__ == "__main__":
    main()
