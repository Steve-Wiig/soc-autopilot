#!/usr/bin/env python3
"""
OpenRouter quota tracker for the 50 RPD free-tier hard limit.

- Tracks every attempt (success AND 429 — both count against quota)
- Locks OpenRouter for 24h once exhausted
- Auto-resets on calendar day rollover
- Persists to disk so it survives restarts
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

QUOTA_FILE = Path(__file__).resolve().parent / "openrouter_quota.json"
DAILY_LIMIT = 1000  # Funded tier (was 50 for free tier)
LOCK_HOURS = 1  # Funded tier: 1h lock on 429 (was 24h for free tier)


def _load():
    if QUOTA_FILE.exists():
        try:
            return json.loads(QUOTA_FILE.read_text())
        except Exception:
            pass
    return {"used_today": 0, "day": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "locked_until": None}


def _save(data):
    QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUOTA_FILE.parent / (QUOTA_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, QUOTA_FILE)  # atomic swap


def _refresh(data):
    """Reset counter on new day; clear expired lock."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if data.get("day") != today:
        data = {"used_today": 0, "day": today, "locked_until": None}
    if data.get("locked_until"):
        try:
            lock_dt = datetime.fromisoformat(data["locked_until"])
            if lock_dt.tzinfo is None:
                lock_dt = lock_dt.replace(tzinfo=timezone.utc)  # legacy naive stamps
            if lock_dt <= datetime.now(timezone.utc):
                data["locked_until"] = None
        except Exception:
            data["locked_until"] = None
    return data


def remaining():
    return max(0, DAILY_LIMIT - _refresh(_load()).get("used_today", 0))


def is_available():
    """True if OpenRouter can be used right now."""
    data = _refresh(_load())
    if data.get("locked_until"):
        return False
    if data.get("used_today", 0) >= DAILY_LIMIT:
        data["locked_until"] = (datetime.now(timezone.utc) + timedelta(hours=LOCK_HOURS)).isoformat()
        _save(data)
        return False
    return True


def record_attempt():
    """Count one request (success or 429). Lock when exhausted."""
    data = _refresh(_load())
    data["used_today"] = data.get("used_today", 0) + 1
    data["last_attempt"] = datetime.now(timezone.utc).isoformat()
    if data["used_today"] >= DAILY_LIMIT and not data.get("locked_until"):
        data["locked_until"] = (datetime.now(timezone.utc) + timedelta(hours=LOCK_HOURS)).isoformat()
        print(f"    🔒 OpenRouter quota exhausted ({data['used_today']}/{DAILY_LIMIT}). Locked 24h.")
    _save(data)
    return data


def status():
    d = _refresh(_load())
    return {
        "used_today": d.get("used_today", 0),
        "remaining": remaining(),
        "locked_until": d.get("locked_until"),
        "day": d.get("day"),
    }


def force_lock(reason="429 received"):
    """Instantly lock OpenRouter for 24h (used when we hit a 429)."""
    data = _refresh(_load())
    data["locked_until"] = (datetime.now(timezone.utc) + timedelta(hours=LOCK_HOURS)).isoformat()
    data["lock_reason"] = reason
    # Mark as fully used so it stays locked even if time resets
    data["used_today"] = DAILY_LIMIT 
    _save(data)
    print(f"    🔒 OpenRouter force-locked for 24h ({reason})")



if __name__ == "__main__":
    s = status()
    print(f"OpenRouter quota: {s['used_today']}/{DAILY_LIMIT} used, {s['remaining']} remaining")
    print(f"Locked until: {s['locked_until'] or 'not locked'}")



def check_quota_or_raise():
    """Raises RuntimeError if quota is exceeded, preventing API drain."""
    import json
    from pathlib import Path
    from datetime import datetime, timezone, timedelta
    
    quota_file = Path(__file__).parent / "openrouter_quota.json"
    if not quota_file.exists(): return
    
    try:
        data = json.loads(quota_file.read_text())
        used = data.get("used_today", 0)
        locked_until = data.get("locked_until")
        
        if locked_until:
            lock_time = datetime.fromisoformat(locked_until.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) < lock_time:
                raise RuntimeError(f"OpenRouter quota locked until {locked_until}. Used: {used}/50")
        
        if used >= 50:
            lock_until = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            data["locked_until"] = lock_until
            quota_file.write_text(json.dumps(data, indent=2))
            raise RuntimeError(f"OpenRouter quota exceeded ({used}/50). Locked until {lock_until}")
    except Exception as e:
        if "quota" in str(e).lower(): raise
        print(f"Warning: Could not check quota: {e}")
