import os
import json
import urllib.request
import re

CRITIC_MODEL = os.getenv("OPENROUTER_FREE_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")

def compress_traceback(traceback: str, max_chars: int = 1600) -> str:
    if not traceback: return ""
    failed_match = re.search(r'^(FAILED\s+.+)$', traceback, re.MULTILINE)
    failed_line = failed_match.group(1) if failed_match else ""
    error_lines = re.findall(r'^(E\s+.+)$', traceback, re.MULTILINE)
    loc_match = re.findall(r'^([\w/\-\.]+\.py:\d+:\s+\w+Error.*)$', traceback, re.MULTILINE)
    loc_line = loc_match[-1] if loc_match else ""
    lines = traceback.strip().split('\n')
    noise = ['site-packages', '_pytest', 'pluggy', 'importlib', '<frozen', 'pytest', 'runpy', '<string>']
    clean_lines = [l for l in lines if not any(n in l for n in noise)]
    relevant = []
    if failed_line: relevant.append(failed_line)
    if loc_line and loc_line not in relevant: relevant.append(loc_line)
    if error_lines: relevant.extend(error_lines[:3])
    for l in clean_lines[-5:]:
        if l.strip() and l not in relevant: relevant.append(l)
    result = '\n'.join(relevant)
    return result[:max_chars-3] + "..." if len(result) > max_chars else result

def generate_strategic_constraint(failed_code: str, traceback: str, original_prompt: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "CRITICAL STRATEGY SHIFT: Your previous approach failed. Adopt a fundamentally different algorithmic strategy."
    compressed_tb = compress_traceback(traceback)
    critic_prompt = (
        "You are a Senior Code Architect acting as a Meta-Critic.\n"
        "The junior AI tried to fix a bug but failed the pytest gate.\n\n"
        "ORIGINAL INTENT:\n" + original_prompt[:500] + "\n\n"
        "FAILED CODE SNIPPET:\n```python\n" + failed_code[:1000] + "\n```\n\n"
        "PYTEST TRACEBACK:\n" + compressed_tb + "\n\n"
        "YOUR TASK:\n"
        "In exactly ONE sentence, provide a 'Strategic Constraint' for the junior AI's next attempt.\n"
        "Tell it what specific approach it MUST take, or what approach it is FORBIDDEN from using, to avoid this exact trap.\n"
        "Do NOT write code. Do NOT explain. ONLY output the 1-sentence constraint."
    )
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://localhost",
        "X-Title": "soc-autopilot Meta-Critic"
    }
    payload = {
        "model": CRITIC_MODEL,
        "messages": [{"role": "user", "content": critic_prompt}],
        "max_tokens": 100,
        "temperature": 0.5
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            constraint = data['choices'][0]['message']['content'].strip()
            if len(constraint) > 300: constraint = constraint[:297] + "..."
            return f"CRITICAL STRATEGY SHIFT: {constraint}"
    except Exception as e:
        return f"CRITICAL STRATEGY SHIFT: Meta-Critic failed ({e}). Adopt a fundamentally different algorithmic strategy."
