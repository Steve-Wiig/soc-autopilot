#!/usr/bin/env python3
import os, sys, fcntl, subprocess
from pathlib import Path

PROJECT_ROOT = Path(str(ROOT))
LOCAL_OUTBOX = PROJECT_ROOT / "overnight" / ".telemetry_buffer" / "outbox"
NAS_DEST = Path("/mnt/backup-nas/soc-slm-telemetry")
LOCK_FILE = Path("/tmp/soc-slm-telemetry-sync.lock")

def log(msg): print(f"[TELEMETRY SYNC] {msg}", flush=True)

def verify_nas_mount():
    try:
        # FIX: Check the actual drive mount point, not the specific sub-directory
        mount_point = Path("/mnt/backup-nas")
        if not mount_point.exists(): return False
        nas_dev = os.stat(str(mount_point)).st_dev
        root_dev = os.stat("/").st_dev
        if nas_dev == root_dev:
            log("CRITICAL: NAS mount lost (st_dev matches root). Aborting.")
            return False
        return True
    except OSError as e:
        log(f"NAS mount verification failed: {e}")
        return False

def sync():
    try:
        lock_fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Another syncer is already running. Exiting.")
        return
    except Exception as e:
        log(f"Failed to acquire lock: {e}. Exiting.")
        return

    try:
        if not LOCAL_OUTBOX.exists() or not any(LOCAL_OUTBOX.iterdir()):
            log("Outbox empty. Nothing to do.")
            return
        if not verify_nas_mount():
            log("NAS unavailable or unmounted. Exiting safely.")
            return
        try: NAS_DEST.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log(f"Failed to create NAS destination dir: {e}. Exiting.")
            return

        cmd = ["rsync", "-a", "--timeout=30", "--remove-source-files", "--no-inc-recursive", f"{LOCAL_OUTBOX}/", f"{NAS_DEST}/"]
        log(f"Executing: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0: log("Sync successful.")
            elif result.returncode == 24: log("Sync completed with vanished source files. Safe.")
            else: log(f"rsync failed with code {result.returncode}.")
        except subprocess.TimeoutExpired: log("rsync timed out. Exiting safely.")
        except Exception as e: log(f"rsync execution failed: {e}")
    finally:
        try: os.close(lock_fd)
        except: pass

if __name__ == "__main__": sync()
