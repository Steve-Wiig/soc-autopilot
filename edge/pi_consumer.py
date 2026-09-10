#!/usr/bin/env python3
import redis
import json
import time
import requests
import re

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:3b"

def build_neutral_prompt(job_data):
    # FIX: Increased truncation from 1500 to 8000 chars so the LLM sees the full patch
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
    except:
        return {"approved": False, "reason": "Pi model returned invalid JSON"}

print("🍓 Pi Objective Reviewer started. Waiting for jobs...")
while True:
    try:
        result = r.blpop('pi_critic_queue', timeout=5)
        if result:
            _, job_json = result
            job = json.loads(job_json)
            print(f"🧠 Reviewing: {job['file']} (Job ID: {job['job_id']})")

            prompt = build_neutral_prompt(job)

            try:
                res = requests.post(OLLAMA_URL, json={
                    "model": MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }, timeout=180)
                raw_response = res.json().get('response', '')
                verdict = parse_strict_json(raw_response)
            except Exception as e:
                verdict = {"approved": False, "reason": f"Inference Error: {str(e)}"}

            r.lpush('pi_critic_results', json.dumps({
                "job_id": job['job_id'],
                "file": job['file'],
                "verdict": verdict,
                "timestamp": time.time()
            }))
            print(f"✅ Verdict pushed: Approved={verdict.get('approved')}")

            time.sleep(2)

    except redis.exceptions.ConnectionError:
        print("❌ Redis connection lost, retrying...")
        time.sleep(5)
    except Exception as e:
        print(f"⚠️ Consumer Error: {e}")
        time.sleep(5)
