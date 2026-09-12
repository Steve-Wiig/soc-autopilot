#!/usr/bin/env python3
"""
OpenRouter quota tracker for the 50 RPD free-tier hard limit.

- Tracks provider usage state and cooldowns
- Locks OpenRouter for configured cooldown period once exhausted
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


def _remaining():
    return max(0, DAILY_LIMIT - _refresh(_load()).get("used_today", 0))


def is_available():
    """
    Deprecated compatibility helper.

    Runtime quota enforcement now uses check_quota_or_raise().
    Kept temporarily to avoid breaking older tooling or generated artifacts.
    """
    raise RuntimeError(
        "is_available() is deprecated. Use check_quota_or_raise()."
    )


def record_attempt():
    """
    Deprecated compatibility helper.

    Runtime accounting is handled by budget_manager.py.
    Runtime circuit breaking is handled by check_quota_or_raise().
    """
    raise RuntimeError(
        "record_attempt() is deprecated. Use budget_manager and check_quota_or_raise()."
    )


def status():
    d = _refresh(_load())
    return {
        "used_today": d.get("used_today", 0),
        "remaining": _remaining(),
        "locked_until": d.get("locked_until"),
        "day": d.get("day"),
    }


def force_lock(reason="429 received"):
    """Instantly lock OpenRouter for configured cooldown period (used when we hit a 429)."""
    data = _refresh(_load())
    data["locked_until"] = (datetime.now(timezone.utc) + timedelta(hours=LOCK_HOURS)).isoformat()
    data["lock_reason"] = reason
    # Preserve usage accounting; lock state controls cooldown behavior
    _save(data)
    print(f"    🔒 OpenRouter force-locked for {LOCK_HOURS}h ({reason})")



if __name__ == "__main__":
    s = status()
    print(f"OpenRouter quota: {s['used_today']}/{DAILY_LIMIT} used, {s['remaining']} remaining")
    print(f"Locked until: {s['locked_until'] or 'not locked'}")



def check_quota_or_raise():
    """Raise RuntimeError when OpenRouter circuit breaker is active."""
    data = _refresh(_load())

    used = data.get("used_today", 0)
    locked_until = data.get("locked_until")

    if locked_until:
        try:
            lock_time = datetime.fromisoformat(
                locked_until.replace("Z", "+00:00")
            )
            if datetime.now(timezone.utc) < lock_time:
                raise RuntimeError(
                    f"OpenRouter quota locked until {locked_until}. "
                    f"Used: {used}/{DAILY_LIMIT}"
                )
        except ValueError:
            pass

    if used >= DAILY_LIMIT:
        lock_until = (
            datetime.now(timezone.utc)
            + timedelta(hours=LOCK_HOURS)
        ).isoformat()

        data["locked_until"] = lock_until
        _save(data)

        raise RuntimeError(
            f"OpenRouter quota exceeded "
            f"({used}/{DAILY_LIMIT}). "
            f"Locked until {lock_until}"
        )

