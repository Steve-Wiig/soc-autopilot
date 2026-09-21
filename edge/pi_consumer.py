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
from typing import Any, Dict, Optional, Tuple

import redis
import requests


OLLAMA_URL: str = "http://localhost:11434/api/generate"
MODEL: str = "qwen2.5-coder:3b"


def dynamic_thermal_pace() -> float:
    """I-1: Dynamic thermal pacing based on actual CPU temp.

    Prevents Pi throttling by increasing the delay between jobs as the
    CPU temperature rises. Falls back to a static pace if the thermal
    sysfs entry is unavailable (e.g. non-Pi hardware).

    Returns:
        Number of seconds to sleep before processing the next job.
    """
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


def build_neutral_prompt(job_data: Dict[str, Any]) -> str:
    """Build the LLM review prompt for a given job.

    Args:
        job_data: The job payload, expected to contain "patch", "file",
            and "issue" keys.

    Returns:
        A prompt string instructing the model to objectively review the
        patch and return a strict JSON verdict.
    """
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


def parse_strict_json(response: str) -> Dict[str, Any]:
    """Parse a model response as strict JSON, tolerating markdown fences.

    Args:
        response: Raw text returned by the LLM.

    Returns:
        The parsed JSON object, or a fallback rejection verdict if the
        response could not be parsed as JSON.
    """
    text = response.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        return {"approved": False, "reason": "Pi model returned invalid JSON"}


def _verify_patch_integrity(patch: str) -> str:
    """Compute the SHA-256 hex digest of a patch, used for integrity checks."""
    return hashlib.sha256(patch.encode()).hexdigest()


def _get_canonical_payload(job: Dict[str, Any]) -> str:
    """Returns a deterministic, canonical JSON string for HMAC verification."""
    payload = {k: v for k, v in job.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _verify_job_signature(payload: str, signature: str, secret: str) -> bool:
    """Verify that `signature` is a valid HMAC-SHA256 of `payload` under `secret`."""
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _secure_llm_boundary(prompt: str, patch: str) -> str:
    """Enforces strict XML delimiters and sanitization before LLM inference.

    Wraps the untrusted patch content in explicit `<patch>` delimiters so
    it is clearly separated from the instruction prompt. Currently
    reserved for future use; not yet wired into the main pipeline.
    """
    return f"{prompt}\n<patch>\n{patch}\n</patch>"


def _read_runtime_config() -> Tuple[Optional[str], str]:
    """Read and validate required runtime secrets from the environment.

    Returns:
        A tuple of (redis_password, hmac_secret). `redis_password` may be
        `None` only when unauthenticated Redis access has been explicitly
        allowed via SOC_ALLOW_UNAUTHENTICATED_REDIS=1.

    Raises:
        RuntimeError: If REDIS_PASSWORD is missing/placeholder without the
            unauthenticated override, or if HMAC_SECRET is missing.
    """
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


def _is_job_valid(job: Dict[str, Any], hmac_secret: str) -> bool:
    """Run the enforced security checks (P0 fix) on an incoming job.

    Verifies the HMAC signature over the canonical payload and confirms
    the patch content matches its declared hash, guarding against tampered
    or forged jobs.

    Args:
        job: The decoded job payload popped from pi_critic_queue.
        hmac_secret: Shared secret used to verify the job signature.

    Returns:
        True if the job's signature and patch integrity check out,
        False otherwise.
    """
    if not _verify_job_signature(
        _get_canonical_payload(job),
        job.get("signature", ""),
        hmac_secret,
    ):
        print("❌ Invalid job signature, rejecting.")
        return False

    if _verify_patch_integrity(job.get("patch", "")) != job.get("patch_hash", ""):
        print("❌ Patch integrity check failed, rejecting.")
        return False

    return True


def _run_inference(job: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    """Run local Ollama inference for a job and return the verdict.

    Args:
        job: The validated job payload to review.

    Returns:
        A tuple of (verdict, inference_duration_sec). On failure, verdict
        is an error dict describing the inference exception.
    """
    prompt = build_neutral_prompt(job)

    start_time = time.time()
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "keep_alive": -1,
            "format": "json"
        }, timeout=(10, 60))
        inference_duration = round(time.time() - start_time, 2)
        raw_response = response.json().get('response', '')
        verdict = parse_strict_json(raw_response)
    except Exception as exc:
        inference_duration = round(time.time() - start_time, 2)
        verdict = {"decision": "ERROR", "reason": f"Inference Error: {str(exc)}"}

    return verdict, inference_duration


def _publish_verdict(
    redis_client: "redis.Redis",
    job: Dict[str, Any],
    verdict: Dict[str, Any],
    inference_duration: float,
) -> None:
    """Push a job's review verdict onto the pi_critic_results queue.

    Args:
        redis_client: Connected Redis client.
        job: The original job payload the verdict corresponds to.
        verdict: The parsed model verdict (or error dict).
        inference_duration: Time in seconds the inference call took.
    """
    redis_client.lpush('pi_critic_results', json.dumps({
        "ledger_event_id": job.get("ledger_event_id"),
        "job_id": job.get('job_id', 'unknown'),
        "file": job.get('file', 'unknown'),
        "verdict": verdict,
        "inference_duration_sec": inference_duration,
        "timestamp": time.time()
    }))
    print(f"✅ Verdict pushed: Approved={verdict.get('approved')} (Took {inference_duration}s)")


def _handle_job(redis_client: "redis.Redis", job_json: str, hmac_secret: str) -> None:
    """Decode, validate, review, and publish the verdict for a single job.

    Args:
        redis_client: Connected Redis client.
        job_json: Raw JSON string popped from pi_critic_queue.
        hmac_secret: Shared secret used to verify the job signature.
    """
    job = json.loads(job_json)

    if not _is_job_valid(job, hmac_secret):
        return

    print(
        f"🧠 Reviewing: {job.get('file', 'unknown')} "
        f"(Job ID: {job.get('job_id', 'unknown')})"
    )

    verdict, inference_duration = _run_inference(job)
    _publish_verdict(redis_client, job, verdict, inference_duration)

    time.sleep(dynamic_thermal_pace())


def main() -> None:
    """Entry point: connect to Redis and process jobs until interrupted."""
    redis_pwd, hmac_secret = _read_runtime_config()

    redis_client = redis.Redis(
        password=redis_pwd,
        host='127.0.0.1',
        port=6379,
        db=0,
        decode_responses=True,
    )

    print("🍓 Pi Objective Reviewer started. Waiting for jobs...")
    while True:
        try:
            result = redis_client.blpop('pi_critic_queue', timeout=5)
            if result:
                _, job_json = result
                _handle_job(redis_client, job_json, hmac_secret)

        except redis.exceptions.ConnectionError:
            print("❌ Redis connection lost, retrying...")
            time.sleep(5)
        except Exception as exc:
            print(f"⚠️ Consumer Error: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    main()
