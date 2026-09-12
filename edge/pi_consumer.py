import os
#!/usr/bin/env python3
import redis
import json
import time
import requests
import re

redis_pwd = os.environ.get("REDIS_PASSWORD")
if not redis_pwd or redis_pwd == "CHANGE_ME":
    raise RuntimeError("Fatal: REDIS_PASSWORD must be explicitly configured")
r = redis.Redis(password=redis_pwd, password=os.environ.get("REDIS_PASSWORD"), host='localhost', port=6379, db=0, decode_responses=True)
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:3b" # Note: Your code specifies 3b. If you want 1.5b, change this string.

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

print("🍓 Pi Objective Reviewer started. Waiting for jobs...")
while True:
    try:
        result = r.blpop('pi_critic_queue', timeout=5)
        if result:
            _, job_json = result
            job = json.loads(job_json)

    # --- ENFORCED SECURITY CHECKS (P0 FIX) ---
    if not _verify_job_signature(job_data, job.get("signature", ""), os.environ.get("HMAC_SECRET", "")):
        print("❌ Invalid job signature, rejecting.")
        continue
    if _verify_patch_integrity(job.get("patch", "")) != job.get("patch_hash", ""):
        print("❌ Patch integrity check failed, rejecting.")
        continue
    # -----------------------------------------

            print(f"🧠 Reviewing: {job.get('file', 'unknown')} (Job ID: {job.get('job_id', 'unknown')})")

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
                verdict = {"approved": False, "reason": f"Inference Error: {str(e)}"}

            r.lpush('pi_critic_results', json.dumps({
                "ledger_event_id": job.get("ledger_event_id"),
    "job_id": job.get('job_id', 'unknown'),
                "file": job.get('file', 'unknown'),
                "verdict": verdict,
                "inference_duration_sec": inference_duration,
                "timestamp": time.time()
            }))
            print(f"✅ Verdict pushed: Approved={verdict.get('approved')} (Took {inference_duration}s)")

            time.sleep(2)

    except redis.exceptions.ConnectionError:
        print("❌ Redis connection lost, retrying...")
        time.sleep(5)
    except Exception as e:
        print(f"⚠️ Consumer Error: {e}")
        time.sleep(5)

import hashlib
def _verify_patch_integrity(patch: str) -> str:
    return hashlib.sha256(patch.encode()).hexdigest()

import hmac
def _verify_job_signature(payload: str, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
