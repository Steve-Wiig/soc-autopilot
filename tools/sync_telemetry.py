#!/usr/bin/env python3
import os, sys, fcntl, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT
LOCAL_OUTBOX = PROJECT_ROOT / "overnight" / ".telemetry_buffer" / "outbox"
ARCHIVE_DEST = PROJECT_ROOT / "overnight" / "archive" / "telemetry"
LOCK_FILE = Path("/tmp/soc-slm-telemetry-sync.lock")

def log(msg): print(f"[TELEMETRY SYNC] {msg}", flush=True)

def verify_archive_destination():
    """Ensure the archive destination is safe to sync into.

    Refuses if the destination is equal to or nested inside the outbox.
    Local-only after NAS removal (P1-4).
    """
    archive_str = str(ARCHIVE_DEST.absolute())
    outbox_str = str(LOCAL_OUTBOX.absolute())
    if archive_str == outbox_str:
        log("CRITICAL: Archive destination equals outbox. Aborting.")
        return False
    if archive_str.startswith(outbox_str + "/"):
        log("CRITICAL: Archive destination is inside outbox. Aborting.")
        return False
    return True

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
        if not verify_archive_destination():
            log("Archive destination is unsafe. Exiting safely.")
            return
        try: ARCHIVE_DEST.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log(f"Failed to create archive destination dir: {e}. Exiting.")
            return

        cmd = ["rsync", "-a", "--timeout=30", "--remove-source-files", "--no-inc-recursive", f"{LOCAL_OUTBOX}/", f"{ARCHIVE_DEST}/"]
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
        except Exception as e:
            # HARDENED: Fail closed with telemetry
            import logging
            logging.error(f'CONTROL-PLANE FAILURE in sync_telemetry.py: {e}')
            raise

if __name__ == "__main__": sync()
