import os
import json
import urllib.request

# We use a fast, cheap model for the Critic role to save heavy-model budget
CRITIC_MODEL = "meta-llama/mistralai/mistral-7b-instruct:free"

def generate_strategic_constraint(failed_code: str, traceback: str, original_prompt: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "CRITICAL STRATEGY SHIFT: Your previous approach failed. Adopt a fundamentally different algorithmic strategy."

    # Using explicit concatenation to avoid f-string backtick confusion in some environments
    critic_prompt = (
        "You are a Senior Code Architect acting as a Meta-Critic.\n"
        "The junior AI tried to fix a bug but failed the pytest gate.\n\n"
        "ORIGINAL INTENT:\n" + original_prompt[:500] + "\n\n"
        "FAILED CODE SNIPPET:\n```python\n" + failed_code[:1000] + "\n```\n\n"
        "PYTEST TRACEBACK:\n" + traceback[:1000] + "\n\n"
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
            if len(constraint) > 300:
                constraint = constraint[:297] + "..."
            return f"CRITICAL STRATEGY SHIFT: {constraint}"
    except Exception as e:
        return f"CRITICAL STRATEGY SHIFT: Meta-Critic failed ({e}). Adopt a fundamentally different algorithmic strategy."
