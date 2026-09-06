import os, json, time, uuid, sys, threading
from pathlib import Path
from datetime import datetime, timezone

DEFAULT_BUFFER_ROOT = ROOT / "overnight/.telemetry_buffer"
DEFAULT_ROTATE_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_BUFFER_BYTES = 50 * 1024 * 1024

class TelemetryWriter:
    def __init__(self, buffer_root=None, rotate_bytes=None, max_buffer_bytes=None):
        self.buffer_root = Path(buffer_root or DEFAULT_BUFFER_ROOT)
        self.outbox_dir = self.buffer_root / "outbox"
        self.current_file = self.buffer_root / "current.jsonl"
        self.rotate_bytes = rotate_bytes if rotate_bytes is not None else DEFAULT_ROTATE_BYTES
        self.max_buffer_bytes = max_buffer_bytes if max_buffer_bytes is not None else DEFAULT_MAX_BUFFER_BYTES
        self._drop_mode = False
        self._warnings = {}
        self._lock = threading.Lock()
        self._ensure_dirs()

    def _ensure_dirs(self):
        try:
            for d in [self.buffer_root, self.outbox_dir]:
                d.mkdir(parents=True, exist_ok=True)
                os.chmod(str(d), 0o700)
        except Exception as e:
            self._warn("dir_creation", f"Failed to create telemetry dirs: {e}")

    def _warn(self, err_type, msg, event=None):
        now = time.time()
        if now - self._warnings.get(err_type, 0) > 300:
            self._warnings[err_type] = now
            try: print(f"[TELEMETRY WARNING] {msg}", file=sys.stderr)
            except Exception: pass

    def _get_total_size(self):
        total = 0
        try:
            if self.current_file.exists(): total += self.current_file.stat().st_size
            if self.outbox_dir.exists():
                for f in self.outbox_dir.iterdir():
                    if f.is_file(): total += f.stat().st_size
        except OSError: pass
        return total

    def _enforce_cap(self, event=None):
        try:
            total = self._get_total_size()
            if total <= self.max_buffer_bytes:
                if self._drop_mode:
                    self._drop_mode = False
                    self._warn("recovery", "Telemetry storage under cap, exiting drop mode.", event)
                return
            while total > self.max_buffer_bytes:
                outbox_files = sorted(self.outbox_dir.glob("pending_*.jsonl"))
                if outbox_files: outbox_files[0].unlink(missing_ok=True)
                else:
                    if not self._drop_mode:
                        self._drop_mode = True
                        self._warn("cap_drop", "Telemetry cap exceeded. Entering drop mode.", event)
                    break
                total = self._get_total_size()
        except Exception as e:
            self._warn("cap_enforcement", f"Failed to enforce cap: {e}", event)

    def _rotate(self):
        if not self.current_file.exists(): return
        try: size = self.current_file.stat().st_size
        except OSError: return
        if size < self.rotate_bytes: return
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        uid = uuid.uuid4().hex[:8]
        target = self.outbox_dir / f"pending_{ts}_{uid}.jsonl"
        try:
            os.rename(str(self.current_file), str(target))
            os.chmod(str(target), 0o600)
            if self._drop_mode:
                self._drop_mode = False
                self._warn("recovery", "Telemetry rotation succeeded, exiting drop mode.")
        except OSError as e:
            self._warn("rotation", f"Failed to rotate current.jsonl: {e}")

    def log_attempt(self, event):
        try:
            safe_event = dict(event)
            for bad_key in ['api_keys', 'prompt', 'generated_code', 'raw_response', 'env_vars']:
                safe_event.pop(bad_key, None)
            self._enforce_cap(safe_event)
            if self._drop_mode: return
            line = json.dumps(safe_event, separators=(',', ':')) + "\n"
            with self._lock:
                self._rotate()
                self._enforce_cap(safe_event)
                if self._drop_mode: return
                try:
                    fd = os.open(str(self.current_file), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                    try:
                        os.fchmod(fd, 0o600)
                        os.write(fd, line.encode('utf-8'))
                        os.fsync(fd)
                    finally: os.close(fd)
                except Exception as e:
                    self._warn("write", f"Telemetry write failed: {e}", safe_event)
        except Exception as e:
            self._warn("unexpected", f"Unexpected telemetry failure: {e}")

writer = TelemetryWriter()
def log_attempt(event): writer.log_attempt(event)
