#!/usr/bin/env python3
"""
API Budget Manager for soc-autopilot.

Tracks per-minute, per-hour, and per-day API usage for both providers.
Enforces free-tier limits and gracefully pauses/stops when budget is low.

Usage in any automation script:
    from overnight.budget_manager import APIBudgetManager
    
    budget = APIBudgetManager()
    
    if not budget.can_proceed("openrouter"):
        print("Budget exhausted, stopping")
        sys.exit(0)
    
    budget.record_call("openrouter")
    # ... make the API call ...

CLI:
    python3 overnight/budget_manager.py              # Show current usage
    python3 overnight/budget_manager.py --reset      # Reset all counters
"""
import json
import os
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(str(ROOT))
USAGE_FILE = ROOT / "overnight" / "api_usage.json"

# ============================================================
# FREE TIER LIMITS (adjust these to match your actual limits)
# ============================================================
# Check your actual limits at:
#   OpenRouter: https://openrouter.ai/settings/limits
#   Gemini: https://ai.google.dev/gemini-api/docs/rate-limits
#
# Conservative defaults — adjust upward if your tier allows more.
LIMITS = {
    "openrouter": {
        "per_minute": 20,
        "per_hour": 200,
        "per_day": 500,
    },
    "gemini": {
        "per_minute": 15,
        "per_hour": 300,
        "per_day": 1000,
    },
    "groq": {
        "per_minute": 30,       # RPM: 30 requests per minute (all models)
        "per_hour": 1500,       # Conservative: ~25 RPM sustained
        "per_day": 250,         # RPD: 250 requests per day (groq/compound)
    },
    "mistral": {
        "per_minute": 15,
        "per_hour": 300,
        "per_day": 1000,
    },
    "groq_alt": {
        "per_minute": 30,       # RPM: 30 requests per minute
        "per_hour": 1500,       # Conservative
        "per_day": 1000,        # RPD: 1000 requests per day (gpt-oss-*, qwen3.6)
    },
}

# How much buffer to leave before stopping (percentage)
SAFETY_MARGIN = 0.85  # Stop at 85% of limit to avoid hitting 429


class APIBudgetManager:
    """Tracks and enforces API usage limits across providers."""

    def __init__(self, limits: Optional[Dict] = None):
        self.limits = limits or LIMITS
        self.usage_file = USAGE_FILE
        self._usage = self._load_usage()

    # ============================================================
    # PERSISTENCE
    # ============================================================
    def _load_usage(self) -> Dict:
        """Load usage history from disk."""
        if self.usage_file.exists():
            try:
                data = json.loads(self.usage_file.read_text())
                # Convert lists back to deques with datetime objects
                usage = {}
                for provider, timestamps in data.items():
                    usage[provider] = deque(
                        datetime.fromisoformat(ts) for ts in timestamps
                    )
                return usage
            except (json.JSONDecodeError, ValueError):
                pass
        return {provider: deque() for provider in self.limits}

    def _save_usage(self):
        """Persist usage history to disk."""
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for provider, timestamps in self._usage.items():
            data[provider] = [ts.isoformat() for ts in timestamps]
        self.usage_file.write_text(json.dumps(data, indent=2))

    # ============================================================
    # USAGE TRACKING
    # ============================================================
    def _cleanup_old(self, provider: str):
        """Remove timestamps older than 24 hours."""
        cutoff = datetime.now() - timedelta(hours=24)
        usage = self._usage.get(provider, deque())
        while usage and usage[0] < cutoff:
            usage.popleft()
        self._usage[provider] = usage

    def record_call(self, provider: str):
        """Record a single API call."""
        self._cleanup_old(provider)
        if provider not in self._usage:
            self._usage[provider] = deque()
        self._usage[provider].append(datetime.now())
        self._save_usage()

    def _count_in_window(self, provider: str, window_minutes: int) -> int:
        """Count calls within the last N minutes."""
        self._cleanup_old(provider)
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        usage = self._usage.get(provider, deque())
        return sum(1 for ts in usage if ts >= cutoff)

    # ============================================================
    # BUDGET CHECKS
    # ============================================================
    def get_usage(self, provider: str) -> Dict[str, int]:
        """Get current usage counts for all windows."""
        self._cleanup_old(provider)
        return {
            "last_minute": self._count_in_window(provider, 1),
            "last_hour": self._count_in_window(provider, 60),
            "last_day": self._count_in_window(provider, 1440),
        }

    def get_remaining(self, provider: str) -> Dict[str, int]:
        """Get remaining budget for all windows."""
        usage = self.get_usage(provider)
        limits = self.limits.get(provider, {})
        return {
            "per_minute": max(0, limits.get("per_minute", 0) - usage["last_minute"]),
            "per_hour": max(0, limits.get("per_hour", 0) - usage["last_hour"]),
            "per_day": max(0, limits.get("per_day", 0) - usage["last_day"]),
        }

    def get_limits_for_model(self, model: str = None) -> Dict:
        """Get rate limits for a specific Groq model.
        
        groq/compound and groq/compound-mini: 250 RPD
        gpt-oss-*, qwen3.6: 1000 RPD
        """
        if model and 'groq/compound' in model:
            return self.limits.get('groq', self.limits['groq'])
        elif model and ('gpt-oss' in model or 'qwen' in model):
            return self.limits.get('groq_alt', self.limits['groq'])
        else:
            return self.limits.get('groq', self.limits['groq'])
    
    def can_proceed_model_aware(self, provider: str, model: str = None) -> bool:
        """Check if we can proceed, taking model-specific limits into account."""
        if provider != 'groq':
            return self.can_proceed(provider)
        
        now = datetime.now()
        calls = list(self._usage.get(provider, deque()))
        limits = self.get_limits_for_model(model)
        
        # Check per-minute
        minute_cutoff = now - timedelta(minutes=1)
        minute_calls = [c for c in calls if c > minute_cutoff]
        if len(minute_calls) >= limits['per_minute']:
            return False
        
        # Check per-hour
        hour_cutoff = now - timedelta(hours=1)
        hour_calls = [c for c in calls if c > hour_cutoff]
        if len(hour_calls) >= limits['per_hour']:
            return False
        
        # Check per-day
        day_cutoff = now - timedelta(hours=24)
        day_calls = [c for c in calls if c > day_cutoff]
        if len(day_calls) >= limits['per_day']:
            return False
        
        return True
    
    def wait_if_needed_model_aware(self, provider: str, model: str = None, timeout: int = 120) -> bool:
        """Model-aware precise wait for Groq; delegates for other providers."""
        if provider != "groq":
            return self.wait_if_needed(provider, timeout)
        import time
        waited = 0.0
        limits = self.get_limits_for_model(model)
        while waited < timeout:
            if self.can_proceed_model_aware(provider, model):
                return True
            if self._seconds_until_slot(provider, 86400, limits["per_day"]) > 0:
                print(f"  🔒 [groq/{model or 'any'}] daily limit reached — no more calls this window")
                return False
            waits = [self._seconds_until_slot(provider, 60, limits["per_minute"]),
                     self._seconds_until_slot(provider, 3600, limits["per_hour"])]
            full = [w for w in waits if w > 0]
            sleep_time = min(full) if full else 1.0
            sleep_time = min(sleep_time, max(0.5, timeout - waited))
            print(f"  ⏱️  [groq/{model or 'any'}] rate window full — sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
            waited += sleep_time
        return False
    def can_proceed(self, provider: str) -> bool:
        """Check if we can make another call without exceeding limits."""
        usage = self.get_usage(provider)
        limits = self.limits.get(provider, {})

        for window, key in [
            ("per_minute", "last_minute"),
            ("per_hour", "last_hour"),
            ("per_day", "last_day"),
        ]:
            limit = limits.get(window, float("inf"))
            current = usage[key]
            threshold = int(limit * SAFETY_MARGIN)
            if current >= threshold:
                return False

        return True

    def _seconds_until_slot(self, provider, window_seconds, max_calls):
        """Exact seconds until a slot frees in a sliding window (0.0 if open)."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=window_seconds)
        stamps = [ts for ts in self._usage.get(provider, deque()) if ts > cutoff]
        # Apply SAFETY_MARGIN to match can_proceed() threshold logic
        effective_max = int(max_calls * SAFETY_MARGIN)
        if len(stamps) < effective_max:
            return 0.0
        oldest = min(stamps)
        return max(0.0, window_seconds - (now - oldest).total_seconds()) + 0.25
    def wait_if_needed(self, provider: str, timeout: int = 120) -> bool:
        """Sleep precisely until a rate slot opens (no 1s polling spam)."""
        import time
        waited = 0.0
        limits = self.limits.get(provider, self.limits.get("groq"))
        while waited < timeout:
            if self.can_proceed(provider):
                return True
            if self._seconds_until_slot(provider, 86400, limits["per_day"]) > 0:
                print(f"  🔒 [{provider}] daily limit reached — no more calls this window")
                return False
            waits = [self._seconds_until_slot(provider, 60, limits["per_minute"]),
                     self._seconds_until_slot(provider, 3600, limits["per_hour"])]
            full = [w for w in waits if w > 0]
            sleep_time = min(full) if full else 1.0
            sleep_time = min(sleep_time, max(0.5, timeout - waited))
            print(f"  ⏱️  [{provider}] rate window full — sleeping {sleep_time:.1f}s until a slot opens")
            time.sleep(sleep_time)
            waited += sleep_time
        return False
    def _oldest_in_window(self, provider: str, window_minutes: int) -> Optional[datetime]:
        """Get the oldest timestamp in the window."""
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        usage = self._usage.get(provider, deque())
        for ts in usage:
            if ts >= cutoff:
                return ts
        return None

    # ============================================================
    # REPORTING
    # ============================================================
    def report(self) -> str:
        """Generate a human-readable usage report."""
        lines = ["=" * 60]
        lines.append("API USAGE REPORT")
        lines.append("=" * 60)

        for provider, limits in self.limits.items():
            usage = self.get_usage(provider)
            remaining = self.get_remaining(provider)

            lines.append(f"\n  {provider.upper()}:")
            lines.append(f"    Last minute: {usage['last_minute']:3d} / {limits.get('per_minute', '?')} "
                        f"(remaining: {remaining['per_minute']})")
            lines.append(f"    Last hour:   {usage['last_hour']:3d} / {limits.get('per_hour', '?')} "
                        f"(remaining: {remaining['per_hour']})")
            lines.append(f"    Last 24h:    {usage['last_day']:3d} / {limits.get('per_day', '?')} "
                        f"(remaining: {remaining['per_day']})")

            # Status indicator
            can_go = self.can_proceed(provider)
            status = "✅ READY" if can_go else "⚠️  PAUSED (limit approaching)"
            lines.append(f"    Status:      {status}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def reset(self):
        """Reset all usage counters."""
        self._usage = {provider: deque() for provider in self.limits}
        self._save_usage()


# ============================================================
# CONVENIENCE: Decorator for budget-aware API calls
# ============================================================
def budget_aware(provider: str, max_wait: int = 120):
    """
    Decorator that enforces budget limits before calling an API function.
    
    Usage:
        budget = APIBudgetManager()
        
        @budget_aware("openrouter")
        def my_api_call(prompt):
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            budget = APIBudgetManager()
            if not budget.wait_if_needed(provider, timeout=max_wait):
                raise RuntimeError(
                    f"API budget exhausted for {provider}. "
                    f"Try again later or increase limits."
                )
            result = func(*args, **kwargs)
            budget.record_call(provider)
            return result
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="API Budget Manager")
    parser.add_argument("--reset", action="store_true", help="Reset all usage counters")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    budget = APIBudgetManager()

    if args.reset:
        budget.reset()
        print("✅ All usage counters reset")
    else:
        if args.json:
            usage = {
                provider: budget.get_usage(provider)
                for provider in budget.limits
            }
            remaining = {
                provider: budget.get_remaining(provider)
                for provider in budget.limits
            }
            print(json.dumps({"usage": usage, "remaining": remaining}, indent=2))
        else:
            print(budget.report())
