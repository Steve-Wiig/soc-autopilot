#!/usr/bin/env python3
import argparse
import subprocess, json, sys, os, signal
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
NAS_BASE = Path("/mnt/backup-nas/soc-slm-telemetry/oracle_queue")

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def h1(text): print(f"\n=== {text} ===")

def run(cmd, timeout=10):
    """Run a shell command with a timeout to prevent hangs."""
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()
    except subprocess.TimeoutExpired:
        return f"(timeout after {timeout}s)"
    except Exception as e:
        return f"(error: {e})"

def is_nas_mounted():
    """Check /proc/mounts to see if NAS is actually mounted. Never blocks."""
    try:
        with open("/proc/mounts", "r") as f:
            return "/mnt/backup-nas" in f.read()
    except Exception:
        return False

def nas_aware_count(path):
    """Count .json files, but skip NAS if it's not mounted."""
    if "backup-nas" in str(path) and not is_nas_mounted():
        return 0
    try:
        return len(list(path.glob("*.json"))) if path.exists() else 0
    except OSError:
        return 0

def nas_aware_size(path):
    """Get directory size in MB, but skip NAS if it's not mounted."""
    if "backup-nas" in str(path) and not is_nas_mounted():
        return 0
    try:
        return sum(
            f.stat().st_size for f in path.rglob("*") if f.is_file()
        ) // (1024 * 1024) if path.exists() else 0
    except OSError:
        return 0

def health_bar(val, max_val, length=15):
    """Draw a simple ASCII progress bar."""
    filled = int((val / max_val) * length) if max_val > 0 else 0
    filled = max(0, min(filled, length))
    return f"[{'█' * filled}{' ' * (length - filled)}] {val}"

# ──────────────────────────────────────────────
# SCORECARD PRINTER
# ──────────────────────────────────────────────
def _print_scorecard(label, scorecard, category=False):
    print(f"   [{label}]")

    applied   = scorecard.get("applied", 0)
    stale     = scorecard.get("stale", 0)
    escalated = scorecard.get("escalated", 0)
    rejected  = scorecard.get("rejected", 0)
    total     = scorecard.get("total_decisions", 0) or 1

    print(f"   🟢 APPLIED  : {health_bar(applied, total)}")
    print(f"   ⚪ STALE    : {health_bar(stale, total)}")
    print(f"   🟡 ESCALATED: {health_bar(escalated, total)}")
    print(f"   🔴 REJECTED : {health_bar(rejected, total)}")

    print(f"   Total decisions: {scorecard.get('total_decisions', 0)}")
    print(f"   Success rate:    {scorecard.get('success_rate', 0)}%")
    print(f"   Proven patterns: {scorecard.get('proven_fix_count', 0)} stored")
    print(f"   Trend:           {scorecard.get('trend', 'N/A')}")

    malformed = scorecard.get("malformed_timestamps", 0)
    if malformed:
        print(f"   ⚠️ Malformed timestamps skipped: {malformed}")

    if category:
        print("   By category:")
        for cat, stats in sorted(scorecard.get("category_breakdown", {}).items()):
            cat_total = sum(stats.get(k, 0) for k in (
                "applied", "rejected", "escalated", "stale"
            ))
            print(
                f"     {cat:20s}: "
                f"{stats.get('applied', 0)}✅ "
                f"{stats.get('rejected', 0)}❌ "
                f"{stats.get('escalated', 0)}🟡 "
                f"({cat_total} total)"
            )

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="soc-autopilot unified system dashboard"
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Recent scorecard window in days (default: 7)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip test suite",
    )
    args = parser.parse_args()

    if args.days < 0:
        parser.error("--days must be >= 0")

    print("=== 📊 UNIFIED SYSTEM DASHBOARD ===")

    # ── 1. ORACLE SWARM ──
    h1("🧠 ORACLE SWARM CONSENSUS GATE")

    nas_online = is_nas_mounted()
    if not nas_online:
        print("   ⚠️ NAS is not mounted – NAS queues will show as 0.")

    local_p = nas_aware_count(ROOT / "overnight/oracle_queue/pending")
    nas_p   = nas_aware_count(NAS_BASE / "pending") if nas_online else 0
    local_a = nas_aware_count(ROOT / "overnight/oracle_queue/approved")
    local_r = nas_aware_count(ROOT / "overnight/oracle_queue/rejected")
    local_size = nas_aware_size(ROOT / "overnight/oracle_queue/pending")

    print(f"⏳ Pending 2-LLM Vote: {local_p + nas_p} (Local: {local_p} [{local_size}MB], NAS: {nas_p})")
    print(f"✅ Unanimously Approved: {local_a + (nas_aware_count(NAS_BASE / 'approved') if nas_online else 0)}")
    print(f"❌ Rejected by Supreme Court: {local_r + (nas_aware_count(NAS_BASE / 'rejected') if nas_online else 0)}")

    if (local_p + nas_p) > 0:
        print("\n⚖️  Running Consensus Gate (60s timeout)...")
        try:
            subprocess.run(
                [sys.executable, str(ROOT / "tools/process_oracle.py")],
                timeout=60,
            )
            print("   ✅ Consensus Gate completed.")
        except subprocess.TimeoutExpired:
            print("   ⚠️ Consensus Gate timed out after 60s. Skipping.")
        except Exception as e:
            print(f"   ❌ Consensus Gate error: {e}")

    # ── 1b. IMPROVEMENT LEDGER ──
    h1("📊 IMPROVEMENT LEDGER")
    ledger_path = ROOT / "overnight" / "improvement_ledger.jsonl"
    if ledger_path.exists():
        statuses = Counter()
        try:
            for line in ledger_path.read_text().strip().split("\n"):
                if line.strip():
                    try:
                        entry = json.loads(line)
                        statuses[entry.get("status", "UNKNOWN")] += 1
                    except json.JSONDecodeError:
                        pass
        except OSError as e:
            print(f"   ⚠️ Could not read ledger: {e}")
            statuses = Counter()

        total = sum(statuses.values())
        print(f"   Total decisions: {total}")
        for status in ["APPLIED", "STALE", "ESCALATED", "REJECTED"]:
            count = statuses.get(status, 0)
            icon = {
                "APPLIED": "🟢", "STALE": "⚪",
                "ESCALATED": "🟡", "REJECTED": "🔴",
            }.get(status, "❓")
            print(f"   {icon} {status:10s}: {health_bar(count, total, 10)}")
    else:
        print("   No ledger entries yet.")

    # ── 1c. SELF-IMPROVEMENT SCORECARD ──
    h1("📈 SELF-IMPROVEMENT SCORECARD")
    try:
        from overnight.self_improver import compute_scorecard
        lifetime = compute_scorecard()
        recent   = compute_scorecard(days=args.days)
        _print_scorecard("LIFETIME", lifetime, category=True)
        print("")
        _print_scorecard(f"LAST {args.days} DAYS", recent)
    except ImportError as e:
        print(f"   ⚠️ Could not import self_improver: {e}")
    except Exception as e:
        print(f"   ⚠️ Scorecard error: {e}")

    # ── 2. DRAIN PROCESS ──
    h1("🔄 DRAIN PROCESS")
    pids = run("pgrep -f 'self_improver.py'").split('\n')
    pids = [p for p in pids if p]
    if pids:
        print(f"   🟢 RUNNING (PIDs: {', '.join(pids)})")
    else:
        print("   🔴 STOPPED")

    # ── 3. QUEUE STATUS ──
    h1("🍓 EDGE WORKER STATUS")
    try:
        gen_status = subprocess.run(
            ["systemctl", "is-active", "pi-generator"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        gen_icon = "🟢" if gen_status == "active" else "🔴"
        print(f"   {gen_icon} Generator: {gen_status}")

        try:
            import redis
            redis_pwd = os.environ.get("REDIS_PASSWORD")
            if not redis_pwd or redis_pwd == "CHANGE_ME":
                raise RuntimeError("Fatal: REDIS_PASSWORD must be explicitly configured")
            r = redis.Redis(password=redis_pwd, host="192.168.1.31", port=6379, db=0, socket_connect_timeout=2)
            q_len = r.llen("pi_critic_queue")
            res_len = r.llen("pi_critic_results")
            print(f"   🟢 Critic:    Active (Queue: {q_len} pending, Results: {res_len})")
        except Exception:
            print(f"   🔴 Critic:    Cannot reach Pi Redis")

        pi_patches = ROOT / "overnight" / "pi_patches.jsonl"
        if pi_patches.exists():
            count = sum(1 for l in pi_patches.read_text().strip().split('\n') if l.strip())
            print(f"   📦 Pending Pi Patches: {count}")
        else:
            print(f"   📦 Pending Pi Patches: 0")
    except Exception as e:
        print(f"   ⚠️ Could not check Pi status: {e}")

    h1("📥 QUEUE STATUS")
    try:
        backlog_path = ROOT / "overnight/fix_backlog.json"
        backlog = json.loads(backlog_path.read_text()) if backlog_path.exists() else []
    except Exception:
        backlog = []
    try:
        deferred_path = ROOT / "overnight/fix_backlog_deferred.json"
        deferred = json.loads(deferred_path.read_text()) if deferred_path.exists() else []
    except Exception:
        deferred = []
    print(f"   Active    : {len(backlog)}")
    print(f"   Deferred  : {len(deferred)}")

    # ── 4. LIVE ACTIVITY ──
    h1("📈 LIVE ACTIVITY (Last 10 lines)")
    log_out = run("tail -n 10 overnight/drun_continuous.log 2>/dev/null")
    print(log_out if log_out else "   (no log entries)")

    # ── 5. DISK HEALTH ──
    h1("💾 DISK HEALTH")
    if is_nas_mounted():
        print(run("df -h / /mnt/docker-data /mnt/backup-nas 2>/dev/null | grep -v tmpfs"))
    else:
        print(run("df -h / /mnt/docker-data 2>/dev/null | grep -v tmpfs"))
        print("   ⚠️ /mnt/backup-nas is not mounted.")

    # ── 6. RECENT FIXES ──
    h1("🛠️ RECENT FIXES")
    git_out = run("git log -5 --oneline")
    print(git_out if git_out else "   (no git history)")

    # ── 7. TEST SUITE ──
    if not args.fast:
        h1("🧪 TEST SUITE (Post-Consensus)")
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=line", "tests/"],
                cwd=ROOT, capture_output=True, text=True, timeout=120,
            )
            out_lines = res.stdout.strip().split(chr(10))
            print(chr(10).join(out_lines[-3:]) if len(out_lines) >= 3 else res.stdout)
        except subprocess.TimeoutExpired:
            print("   ⚠️ Tests timed out after 120s.")
        except Exception as e:
            print(f"   ⚠️ Test error: {e}")
    else:
        h1("🧪 TEST SUITE")
        print("   ⏭️  Skipped (--fast mode)")

    print("\n=== ✅ DASHBOARD COMPLETE ===")

if __name__ == "__main__":
    main()
