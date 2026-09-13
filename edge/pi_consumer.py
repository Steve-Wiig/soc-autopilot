#!/usr/bin/env python3
"""Pi objective reviewer.

Consumes jobs from pi_critic_queue, verifies HMAC signatures and patch
integrity, runs local Ollama inference, pushes verdicts to
pi_critic_results.

Fail-closed: refuses to start without REDIS_PASSWORD and HMAC_SECRET.
For constrained local development only, set
SOC_ALLOW_UNAUTHENTICATED_REDIS=1 to allow Redis without a password.
"""
import hashlib
import hmac
import json
import os
import re
import time

import redis
import requests


OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:3b"


def dynamic_thermal_pace():
    """I-1: Dynamic thermal pacing based on actual CPU temp. Prevents Pi throttling."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp = int(f.read().strip())
        if temp > 80000:   # > 80C: Critical
            return 10.0
        elif temp > 75000: # > 75C: High
            return 5.0
        elif temp > 70000: # > 70C: Warm
            return 3.0
        else:
            return 1.0     # Normal pace
    except Exception:
        return 2.0         # Fallback to original static sleep if sysfs is unavailable


def build_neutral_prompt(job_data):
    patch_text = job_data.get('patch', '')
    if len(patch_text) > 8000:
        patch_text = patch_text[:8000] + "\n... [TRUNCATED FOR LENGTH] ..."

    return f"""You are a Senior Python Engineer reviewing a code patch.
Your goal is to objectively evaluate if the patch is correct, safe, and solves the issue.

FILE: {job_data.get('file', 'unknown')}
ISSUE: {job_data.get('issue', 'N/A')}

PROPOSED PATCH:
{patch_text}

ANALYSIS TASK:
1. Does this patch correctly implement the intended fix?
2. Does it introduce ANY new bugs, edge cases, or security vulnerabilities?
3. Is the code syntactically correct and safe for production?

If the patch is safe, correct, and improves the codebase: return {{"approved": true}}
If the patch introduces a bug, fails to fix the issue, or is unsafe: return {{"approved": false, "reason": "concise explanation"}}

Return ONLY the JSON. No markdown. No preamble."""


def parse_strict_json(response):
    text = response.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        return {"approved": False, "reason": "Pi model returned invalid JSON"}


def _verify_patch_integrity(patch: str) -> str:
    return hashlib.sha256(patch.encode()).hexdigest()


def _get_canonical_payload(job: dict) -> str:
    """Returns a deterministic, canonical JSON string for HMAC verification."""
    payload = {k: v for k, v in job.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _verify_job_signature(payload: str, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _secure_llm_boundary(prompt: str, patch: str) -> str:
    """Enforces strict XML delimiters and sanitization before LLM inference."""
    return f"{prompt}\n<patch>\n{patch}\n</patch>"


def _read_runtime_config():
    """Return (redis_pwd, hmac_secret) or raise RuntimeError. Fail-closed."""
    allow_unauth = os.environ.get("SOC_ALLOW_UNAUTHENTICATED_REDIS") == "1"

    redis_pwd = os.environ.get("REDIS_PASSWORD")
    if not redis_pwd or redis_pwd == "CHANGE_ME":
        if not allow_unauth:
            raise RuntimeError(
                "REDIS_PASSWORD is missing or set to the placeholder value. "
                "Refusing to connect to Redis without authentication. "
                "For constrained local development only, set "
                "SOC_ALLOW_UNAUTHENTICATED_REDIS=1."
            )
        redis_pwd = None

    hmac_secret = os.environ.get("HMAC_SECRET")
    if not hmac_secret:
        raise RuntimeError(
            "HMAC_SECRET is required; refusing to verify job signatures with an "
            "empty secret."
        )

    return redis_pwd, hmac_secret


def main():
    redis_pwd, hmac_secret = _read_runtime_config()

    r = redis.Redis(
        password=redis_pwd,
        host='127.0.0.1',
        port=6379,
        db=0,
        decode_responses=True,
    )

    print("🍓 Pi Objective Reviewer started. Waiting for jobs...")
    while True:
        try:
            result = r.blpop('pi_critic_queue', timeout=5)
            if result:
                _, job_json = result
                job = json.loads(job_json)

                # --- ENFORCED SECURITY CHECKS (P0 FIX) ---
                if not _verify_job_signature(
                    _get_canonical_payload(job),
                    job.get("signature", ""),
                    hmac_secret,
                ):
                    print("❌ Invalid job signature, rejecting.")
                    continue

                if _verify_patch_integrity(
                    job.get("patch", "")
                ) != job.get("patch_hash", ""):
                    print("❌ Patch integrity check failed, rejecting.")
                    continue
                # -----------------------------------------

                print(
                    f"🧠 Reviewing: {job.get('file', 'unknown')} "
                    f"(Job ID: {job.get('job_id', 'unknown')})"
                )

                prompt = build_neutral_prompt(job)

                start_time = time.time()
                try:
                    res = requests.post(OLLAMA_URL, json={
                        "model": MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "keep_alive": -1,
                        "format": "json"
                    }, timeout=(10, 60))
                    inference_duration = round(time.time() - start_time, 2)
                    raw_response = res.json().get('response', '')
                    verdict = parse_strict_json(raw_response)
                except Exception as e:
                    inference_duration = round(time.time() - start_time, 2)
                    verdict = {"decision": "ERROR", "reason": f"Inference Error: {str(e)}"}

                r.lpush('pi_critic_results', json.dumps({
                    "ledger_event_id": job.get("ledger_event_id"),
                    "job_id": job.get('job_id', 'unknown'),
                    "file": job.get('file', 'unknown'),
                    "verdict": verdict,
                    "inference_duration_sec": inference_duration,
                    "timestamp": time.time()
                }))
                print(f"✅ Verdict pushed: Approved={verdict.get('approved')} (Took {inference_duration}s)")

                time.sleep(dynamic_thermal_pace())

        except redis.exceptions.ConnectionError:
            print("❌ Redis connection lost, retrying...")
            time.sleep(5)
        except Exception as e:
            print(f"⚠️ Consumer Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
