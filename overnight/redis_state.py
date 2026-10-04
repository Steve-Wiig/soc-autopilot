"""
Redis-backed Fault-Tolerance & State Management for the SOC Autopilot Swarm.
Replaces fragile local JSONL files and in-memory dictionaries with distributed,
crash-proof Redis data structures. Includes a local fallback if Redis is unreachable.
"""
import redis
import json
import os
import time
import logging

logger = logging.getLogger(__name__)

# Configurable via environment variable (e.g., redis://192.168.1.26:6379/0)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
NAMESPACE = "soc_autopilot:swarm:"

class SwarmState:
    def __init__(self):
        self.use_redis = False
        try:
            self.r = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            self.r.ping()
            self.use_redis = True
            logger.info("✅ Redis connected. Fault-tolerance enabled.")
        except Exception as e:
            logger.warning(f"⚠️ Redis unavailable ({e}). Falling back to local memory.")
            self._local_backlog = []
            self._local_seen = set()

    # --- BACKLOG & DEDUPLICATION (Prevents infinite loops & duplicate fixes) ---
    def add_to_backlog(self, fix_item: dict) -> bool:
        """Adds a fix to the backlog. Returns False if it's a duplicate."""
        item_hash = f"{fix_item.get('file')}:{fix_item.get('line')}:{fix_item.get('desc')}"
        if self.use_redis:
            # SADD returns 1 if added, 0 if already exists (atomic deduplication)
            if self.r.sadd(f"{NAMESPACE}seen_fixes", item_hash):
                self.r.rpush(f"{NAMESPACE}backlog", json.dumps(fix_item))
                return True
        else:
            if item_hash not in self._local_seen:
                self._local_seen.add(item_hash)
                self._local_backlog.append(fix_item)
                return True
        return False

    def pop_from_backlog(self) -> dict:
        """Atomically pops the next fix from the backlog."""
        if self.use_redis:
            item = self.r.lpop(f"{NAMESPACE}backlog")
            return json.loads(item) if item else None
        else:
            return self._local_backlog.pop(0) if self._local_backlog else None

    def get_backlog_size(self) -> int:
        if self.use_redis:
            return self.r.llen(f"{NAMESPACE}backlog")
        return len(self._local_backlog)

    # --- DISTRIBUTED LOCKS (Prevents Git & Quota collisions) ---
    def acquire_lock(self, name: str, timeout: int = 15) -> bool:
        """Acquires a distributed lock. Returns True if successful."""
        if self.use_redis:
            lock = self.r.lock(f"{NAMESPACE}lock:{name}", timeout=timeout)
            return lock.acquire(blocking=True, blocking_timeout=2)
        return True # Local fallback always succeeds (single process assumed)

    def release_lock(self, name: str):
        if self.use_redis:
            self.r.delete(f"{NAMESPACE}lock:{name}")

    # --- CIRCUIT BREAKER (Protects API quota from broken models) ---
    def record_model_failure(self, model_name: str):
        key = f"{NAMESPACE}breaker:{model_name}"
        if self.use_redis:
            pipe = self.r.pipeline()
            pipe.hincrby(key, "failures", 1)
            pipe.hset(key, "last_failure", time.time())
            pipe.execute()
            
    def is_model_blocked(self, model_name: str, threshold: int = 3, cooldown: int = 900) -> bool:
        """Returns True if a model has failed too many times recently."""
        key = f"{NAMESPACE}breaker:{model_name}"
        if self.use_redis:
            data = self.r.hgetall(key)
            if not data: return False
            failures = int(data.get("failures", 0))
            last_fail = float(data.get("last_failure", 0))
            if failures >= threshold and (time.time() - last_fail) < cooldown:
                return True
        return False

    def reset_model_breaker(self, model_name: str):
        if self.use_redis:
            self.r.delete(f"{NAMESPACE}breaker:{model_name}")

# Global singleton for easy importing across the swarm
swarm_state = SwarmState()
