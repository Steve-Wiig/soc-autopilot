"""
Dual-Model LLM Client with DYNAMIC model discovery and fallback.

Instead of hardcoding model IDs (which break when OpenRouter changes them),
this queries OpenRouter's API to find currently-available free instruct models
and builds the fallback list automatically.
"""
import os
import re
import json
import time
from pathlib import Path

try:
    import requests
except ImportError:
    raise ImportError("requests library required: pip install requests")

# ============================================================
# CONFIGURATION
# ============================================================
CRITIC_MODEL = "gemini-3.1-flash-lite"
GENERATOR_MODEL = "nvidia/nemotron-3.5-lightning:free"  # Primary (dynamic discovery may switch at runtime)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

RATE_LIMIT_SLEEP = 7
MAX_RETRIES = 3

# LLM_FIX_HELPERS_V1

CODE_SYSTEM_PROMPT = """You are a senior Python engineer writing production-ready code for a SOC automation platform.
RULES:
- Output ONLY valid Python code
- No markdown fences, no explanations, no preamble
- No reasoning, analysis, planning, or thinking process
- Do NOT start with Let me / Here / I will / First or any prose
- The first non-empty line MUST be valid Python code
- Use real sqlite3.connect(":memory:") for SQLite, not mocks
- Expect RuntimeError not SystemExit (library code auto-fixed)
- Import from actual modules, don't hallucinate"""

PATCH_SYSTEM_PROMPT = """You are a senior Python engineer producing a machine-readable patch.
Output ONLY Aider-style SEARCH/REPLACE blocks.

Use exactly this format:
<<<<<<< path/to/file.py
[exact search text]
=======
[replacement text]
>>>>>>> REPLACE

RULES:
- No prose
- No explanations
- No markdown fences
- No line numbers
- Preserve indentation exactly
- The search block must match the existing file exactly
- If you cannot produce a safe patch, output nothing"""

JSON_SYSTEM_PROMPT = """You are a precise API assistant.
Output ONLY valid JSON.
No markdown fences.
No prose.
No comments.
No trailing commas.
The first non-empty character must be { or [."""

DOCS_SYSTEM_PROMPT = """You are a technical writer.
Output ONLY the document content.
No reasoning, planning, or meta-commentary.
Start directly with the content."""


def _budget_record(provider):
    try:
        from overnight.budget_manager import APIBudgetManager
        APIBudgetManager().record_call(provider)
    except Exception:
        pass


def _budget_allow(provider, model=None):
    try:
        from overnight.budget_manager import APIBudgetManager
        budget = APIBudgetManager()
        if provider == "groq":
            return budget.can_proceed_model_aware("groq", model)
        return budget.can_proceed(provider)
    except Exception:
        return True


def _openrouter_daily_exhausted():
    try:
        from overnight import openrouter_quota
        st = openrouter_quota.status()
        if not st.get("locked_until"):
            return False
        if st.get("used_today", 0) < openrouter_quota.DAILY_LIMIT:
            return False
        reason = str(st.get("lock_reason", ""))
        return not reason.startswith("429")
    except Exception:
        return False


# Dynamic fallback state
_fallback_list = None
_current_model = None
_calls_since_primary_check = 0
PRIMARY_RETRY_INTERVAL = 3
BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "model_fallback_cache.json"
GROQ_CACHE_FILE = BASE_DIR / "groq_model_cache.json"
CACHE_TTL = 3600  # Refresh model list every hour

# Ultimate fallback if discovery fails entirely
DEFAULT_FALLBACK = ["nvidia/nemotron-3.5-lightning:free"]
# Groq-specific fallback if discovery fails entirely
GROQ_DEFAULT_MODELS = ["groq/compound", "groq/compound-mini", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
_last_groq_call = 0.0


# ============================================================
# DYNAMIC MODEL DISCOVERY
# ============================================================
def _estimate_params(name, model_id):
    """Estimate parameter count from model name for ranking."""
    text = (name + " " + model_id).lower()

    # NVIDIA naming convention
    if "ultra" in text: return 500
    if "lightning" in text: return 300
    if "super" in text: return 120
    if "nano" in text: return 30

    # Look for explicit parameter counts: "70b", "72b", "253b", "550b"
    matches = re.findall(r'(\d+(?:\.\d+)?)\s*b\b', text)
    if matches:
        try:
            return max(float(m) for m in matches)
        except (ValueError, TypeError):
            pass

    return 10  # Unknown, rank low


def discover_free_models(api_key):
    """Query OpenRouter for currently available free instruct models."""
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30
        )
        if resp.status_code != 200:
            return None

        models = resp.json().get("data", [])
        candidates = []

        for m in models:
            pricing = m.get("pricing", {})
            try:
                if float(pricing.get("prompt", "1")) != 0.0:
                    continue
                if float(pricing.get("completion", "1")) != 0.0:
                    continue
            except (ValueError, TypeError):
                continue

            model_id = m.get("id", "")
            name = m.get("name", "")
            context = m.get("context_length", 0)

            # Skip very small context models (< 8K) — not useful for code review
            if context < 8000:
                continue

            # Determine if it's an instruct/chat model
            text = (name + " " + model_id).lower()
            is_instruct = any(x in text for x in [
                "instruct", "chat", "-it", "it:", "it-",
                "ultra", "super", "lightning",  # NVIDIA instruct variants
            ])

            # Skip non-instruct models (completion-only, embedding, etc.)
            if not is_instruct:
                continue

            params = _estimate_params(name, model_id)

            candidates.append({
                "id": model_id,
                "name": name,
                "context": context,
                "params": params,
            })

        # Sort by: params (quality), then context length
        candidates.sort(key=lambda x: (x["params"], x["context"]), reverse=True)

        # Return top 8 model IDs
        result = [c["id"] for c in candidates[:8]]
        if result:
            print(f"    🔍 Discovered {len(result)} free instruct models:")
            for c in candidates[:8]:
                print(f"       {c['id']} (~{c['params']}B, {c['context']:,} ctx)")
        return result

    except Exception as e:
        print(f"    ⚠️  Model discovery failed: {e}")
        return None


def get_fallback_list(api_key):
    """Get fallback list, using cache if fresh."""
    global _fallback_list, _current_model

    if _fallback_list is not None:
        return _fallback_list

    # Check cache
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text())
            if time.time() - cache.get("timestamp", 0) < CACHE_TTL:
                _fallback_list = cache["models"]
                _current_model = _fallback_list[0] if _fallback_list else DEFAULT_FALLBACK[0]
                return _fallback_list
        except (json.JSONDecodeError, KeyError):
            pass

    # Discover fresh
    models = discover_free_models(api_key)
    if models:
        _fallback_list = models
        _current_model = models[0]
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "timestamp": time.time(),
            "models": models,
        }, indent=2))
        return models

    # Ultimate fallback
    _fallback_list = DEFAULT_FALLBACK
    _current_model = DEFAULT_FALLBACK[0]
    return _fallback_list


# ============================================================
# OPENROUTER WITH DYNAMIC FALLBACK
# ============================================================
def _call_openrouter(prompt, api_key, model=None, system_prompt=None, max_tokens=8192, temperature=0.2, allow_fallback=True):
    """Call OpenRouter with dynamic model fallback on rate limits."""
    global _current_model, _calls_since_primary_check

    if not api_key:
        return ""

    # Hard RPD limit (funded tier: 1000) — skip entirely if exhausted/locked
    from overnight import openrouter_quota
    if not openrouter_quota.is_available():
        print(f"    🔒 OpenRouter locked/exhausted ({openrouter_quota.remaining()} left) — skipping")
        return ""

    # Ensure fallback list is loaded
    fallback_list = get_fallback_list(api_key)

    if model is None:
        model = _current_model or (fallback_list[0] if fallback_list else DEFAULT_FALLBACK[0])

    # Build ordered list: preferred model first, then fallbacks
    if allow_fallback:
        models_to_try = [model] + [m for m in fallback_list if m != model]
    else:
        # STRICT MODE: only try the preferred model, no fallbacks
        models_to_try = [model]

    # Every N calls, try primary first to check if it recovered
    _calls_since_primary_check += 1
    if _calls_since_primary_check >= PRIMARY_RETRY_INTERVAL and fallback_list:
        _calls_since_primary_check = 0
        primary = fallback_list[0]
        if models_to_try[0] != primary:
            models_to_try = [primary] + models_to_try
            print(f"    🔄 Checking if primary ({primary}) is back...")

    # Large-prompt filter: small free models truncate mid-string on big files,
    # wasting quota. Route large prompts (>~25k chars ≈ >800 lines) to
    # high-capacity models only.
    if len(prompt) > 25000:
        big_models = [m for m in models_to_try
                      if any(k in m for k in ("ultra", "550b", "super-120b", "compound"))]
        if big_models:
            print(f"    📏 Large prompt ({len(prompt)} chars) → high-capacity models only")
            models_to_try = big_models

    attempts = 0
    max_attempts = 1 if not allow_fallback else 3

    for try_model in models_to_try:
        attempts += 1
        if attempts > max_attempts:
            break

        # Count every attempt against the daily quota
        from overnight import openrouter_quota
        if not openrouter_quota.is_available():
            break
        openrouter_quota.record_attempt()
        if not openrouter_quota.is_available():
            break
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://soc-autopilot.local",
            "X-Title": "soc-autopilot Pipeline",
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": try_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120)

            if resp.status_code == 200:
                data = resp.json()
                if "choices" not in data or not data["choices"]:
                    continue
                content = data["choices"][0]["message"]["content"]

                if try_model != _current_model:
                    if fallback_list and try_model == fallback_list[0]:
                        print(f"    ✅ Primary recovered: {try_model}")
                    else:
                        print(f"    🔄 Using fallback: {try_model}")
                _current_model = try_model
                _budget_record("openrouter")
                return content

            elif resp.status_code in (401, 403):
                print(f"    ❌ OpenRouter auth failure for {try_model}: {resp.status_code}")
                return ""
            elif resp.status_code == 429:
                print(f"    ⚠️  {try_model} rate-limited. Locking OpenRouter (duration per openrouter_quota.LOCK_HOURS).")
                openrouter_quota.force_lock(f"429 on {try_model}")
                break  # STOP trying other OpenRouter models, quota is exhausted!

            elif resp.status_code == 404:
                print(f"    ⚠️  {try_model} not available → next")
                continue

            elif resp.status_code == 402:
                print(f"    ❌ {try_model} quota exhausted → next")
                continue

            else:
                print(f"    ❌ {try_model} returned {resp.status_code} → next")
                continue

        except Exception as e:
            print(f"    ❌ {try_model} error: {e} → next")
            continue

    # All OpenRouter models saturated — return empty immediately
    # generate() will handle Groq fallback
    print(f"    ⚠️  All OpenRouter models saturated")
    return ""



def _call_gemini(prompt, api_key, max_tokens=8192, temperature=0.2):
    """Call Gemini (Google)."""
    if not api_key:
        return ""

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(GEMINI_URL, json=payload, headers=headers, timeout=90)

            if resp.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"    [Gemini] Rate limited. Waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code in (400, 401, 403):
                print(f"    [Gemini] Auth/request error: {resp.status_code}")
                return ""

            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("candidates") or []
            if not candidates:
                return ""

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return ""

            _budget_record("gemini")
            return parts[0].get("text", "")
        except Exception as e:
            print(f"    [Gemini] API error: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(10)

    return ""



def discover_groq_models(api_key):
    """Query Groq API for available free models."""
    try:
        resp = requests.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15
        )
        if resp.status_code != 200:
            return None

        models = resp.json().get("data", [])
        candidates = []
        for m in models:
            model_id = m.get("id", "")
            # Filter for instruct/chat models with decent context
            if any(x in model_id for x in ["whisper", "embed", "tts"]):
                continue
            context = m.get("context_window", 8192)
            if context < 8000:
                continue
            candidates.append({"id": model_id, "context": context})

        # Sort by context length
        candidates.sort(key=lambda x: x["context"], reverse=True)
        result = [c["id"] for c in candidates[:6]]
        if result:
            print(f"    🔍 Groq: discovered {len(result)} models")
        return result
    except Exception as e:
        print(f"    ⚠️  Groq discovery failed: {e}")
        return None


def get_groq_models(api_key):
    """Get Groq model list with caching."""
    if GROQ_CACHE_FILE.exists():
        try:
            cache = json.loads(GROQ_CACHE_FILE.read_text())
            if time.time() - cache.get("timestamp", 0) < CACHE_TTL:
                return cache["models"]
        except:
            pass

    models = discover_groq_models(api_key)
    if models:
        GROQ_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        GROQ_CACHE_FILE.write_text(json.dumps({"timestamp": time.time(), "models": models}))
        return models
    return GROQ_DEFAULT_MODELS


# ---- Groq token pacing (free-tier TPM-aware) ----
GROQ_TPM = {
    "groq/compound": 70000,
    "groq/compound-mini": 70000,
    "openai/gpt-oss-120b": 8000,
    "openai/gpt-oss-20b": 8000,
}
DEFAULT_GROQ_TPM = 8000
_groq_usage = {}  # model -> [(timestamp, tokens)]


def _est_tokens(text):
    return max(1, len(text) // 4)


def _groq_window(model):
    now = time.time()
    window = [(ts, t) for ts, t in _groq_usage.get(model, []) if now - ts < 60]
    _groq_usage[model] = window
    return window


def _groq_headroom(model, needed):
    limit = int(GROQ_TPM.get(model, DEFAULT_GROQ_TPM) * 0.8)  # 20% safety margin
    used = sum(t for _, t in _groq_window(model))
    return (limit - used) >= needed


def _groq_record(model, tokens):
    _groq_usage.setdefault(model, []).append((time.time(), tokens))


def _groq_suggested_wait(models):
    now = time.time()
    best = 10
    for m in models:
        window = _groq_window(m)
        if window:
            best = min(best, max(1, int(60 - (now - window[0][0]) + 1)))
    return min(best, 20)


_groq_cooldown = {}
_groq_429_count = {}  # model -> consecutive 429 count  # model -> timestamp until which it's rate-limited


_groq_rl = {}  # model -> {"rem_req","rem_tok","req_reset","tok_reset"}


def _parse_dur(s):
    if not s:
        return 0
    import re as _re
    total = 0
    m = _re.search(r"(\d+)h", s)
    if m: total += int(m.group(1)) * 3600
    m = _re.search(r"(\d+)m", s)
    if m: total += int(m.group(1)) * 60
    m = _re.search(r"([\d.]+)s", s)
    if m: total += float(m.group(1))
    return total


def _groq_note_rl(model, headers):
    try:
        now = time.time()
        e = _groq_rl.setdefault(model, {})
        rr = headers.get("x-ratelimit-remaining-requests")
        rt = headers.get("x-ratelimit-remaining-tokens")
        if rr is not None: e["rem_req"] = int(float(rr))
        if rt is not None: e["rem_tok"] = int(float(rt))
        sr = headers.get("x-ratelimit-reset-requests")
        st = headers.get("x-ratelimit-reset-tokens")
        if sr: e["req_reset"] = now + _parse_dur(sr)
        if st: e["tok_reset"] = now + _parse_dur(st)
    except Exception:
        pass


def _groq_preempted(model):
    e = _groq_rl.get(model)
    if not e:
        return False
    now = time.time()
    if e.get("rem_req", 1) <= 0 and now < e.get("req_reset", 0):
        return True
    if e.get("rem_tok", 1) <= 0 and now < e.get("tok_reset", 0):
        return True
    return False


def _call_groq(prompt, api_key, model=None, system_prompt=None, max_tokens=8192, temperature=0.2):
    """Call Groq with cooldown tracking so we never waste requests probing
    models that are already rate-limited."""
    if not api_key:
        return ""

    global _last_groq_call
    models = get_groq_models(api_key)

    PREFERRED = ["groq/compound-mini", "groq/compound",
                 "openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    BLOCKED = ["qwen/qwen3.6-27b", "openai/gpt-oss-safeguard-20b"]
    models = [m for m in models if m not in BLOCKED]
    models.sort(key=lambda m: PREFERRED.index(m) if m in PREFERRED else len(PREFERRED))
    if model and model in models:
        models = [model] + [m for m in models if m != model]

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    def _in_cooldown(m):
        return _groq_cooldown.get(m, 0) > time.time()

    def _pace():
        global _last_groq_call
        gap = time.time() - _last_groq_call
        if gap < 2.0:
            time.sleep(2.0 - gap)
        _last_groq_call = time.time()

    for pass_num in range(2):  # pass 1: try ready models; pass 2: after cooldown wait
        for try_model in models:
            if _groq_preempted(try_model):
                continue  # server says remaining=0; don't probe until reset
            if _in_cooldown(try_model):
                continue  # don't waste a request probing a cooled-down model
            if not _budget_allow("groq", try_model):
                continue  # budget manager says no


            # Fresh sizing per model (a 413-shrink must not leak to the next model)
            body = prompt[:9000]
            max_out = min(max_tokens, 4096)
            needed = _est_tokens(body) + max_out
            if not _groq_headroom(try_model, needed):
                continue

            for attempt in range(2):
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": body})
                payload = {"model": try_model, "messages": messages,
                           "temperature": temperature, "max_tokens": max_out}
                try:
                    _pace()
                    resp = requests.post(GROQ_URL, json=payload, headers=headers, timeout=90)
                    _groq_note_rl(try_model, resp.headers)
                except Exception as e:
                    print(f"    ❌ Groq {try_model} error: {e} → next")
                    break

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("choices"):
                        usage = data.get("usage", {})
                        tokens = (usage.get("prompt_tokens", 0)
                                  + usage.get("completion_tokens", 0)) or needed
                        _groq_record(try_model, tokens)
                        content = data["choices"][0]["message"]["content"]
                        _groq_429_count[try_model] = 0  # success resets backoff
                        _budget_record("groq")
                        print(f"    ✅ Groq ({try_model}) responded ({len(content)} chars)")
                        return content

                elif resp.status_code == 429:
                    ra = resp.headers.get("retry-after", "5")
                    try:
                        base = min(int(ra), 30)
                    except ValueError:
                        base = 5
                    # Exponential backoff when the same model keeps rejecting us
                    n = _groq_429_count.get(try_model, 0) + 1
                    _groq_429_count[try_model] = n
                    wait = min(base * (2 ** (n - 1)), 90)
                    _groq_cooldown[try_model] = time.time() + wait
                    _groq_record(try_model, needed)
                    print(f"    ⚠️  Groq {try_model} rate-limited (hit x{n}) → backoff {wait}s")
                    break

                elif resp.status_code == 413:
                    if attempt == 0:
                        body = prompt[:4500]
                        max_out = min(max_out, 2048)
                        continue
                    break
                else:
                    break

        # Nothing succeeded this pass — wait for the earliest cooldown, then retry
        now = time.time()
        active = [t for t in _groq_cooldown.values() if t > now]
        if active:
            wait = max(1, int(min(active) - now))
            print(f"    ⏳ Groq cooling down — waiting {wait}s for a model to free up")
            time.sleep(min(wait, 40))
        else:
            time.sleep(8)  # token-window recovery

    return ""

def load_api_keys():
    """Load API keys from .env file."""
    env_path = Path(__file__).resolve().parent.parent / ".env"

    if not env_path.exists():
        env_path = Path("/home/swiig/Documents/soc-autopilot/.env")

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            if line.startswith("export "):
                line = line[len("export "):]

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)

    return {
        "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "groq": os.getenv("GROQ_API_KEY", ""),
        "mistral": os.getenv("MISTRAL_API_KEY", ""),
    }



def gemini_pre_analysis(file_path, content, api_keys):
    """Use Gemini's abundant free tier for preliminary analysis.
    Returns advisory notes passed to primary model as non-authoritative context.
    """
    prompt = f"""You are doing a preliminary code review. Read this file and provide
your initial observations about potential issues, improvements, or concerns.

FILE: {file_path}

GHOSTBUSTER PROTOCOL: You MUST NOT report stylistic issues, missing docstrings, type hints, naming conventions, or code complexity. ONLY report genuine logic bugs, security vulnerabilities, or broken tests. If the code is logically sound, return an empty list or 'No issues'.

CODE:
{content[:6000]}

Provide 3-5 bullet points of observations. Be specific about line numbers.
Keep it brief - this is a preliminary pass, not a final review."""

    try:
        response = _call_gemini(prompt, api_keys.get("gemini", ""),
                                max_tokens=1500, temperature=0.3)
        if response:
            print(f"    📝 Gemini pre-analysis complete ({len(response)} chars)")
            return response.strip()
    except Exception as e:
        print(f"    ⚠️  Gemini pre-analysis failed: {e}")
    return ""



def generate(prompt, api_keys, model_type="code", max_tokens=8192, temperature=0.2, allow_fallback=True, system_prompt=None):
    """Generate content with multi-provider fallback.

    Order: OpenRouter -> Groq -> Mistral -> wait & retry.
    Gemini is reserved for critique/pre-analysis by default.
    """
    if system_prompt is None:
        lowered = prompt.lower()

        if model_type == "code" and (
            "aider-style search/replace" in lowered
            or "<<<<<<<" in prompt
        ):
            model_type = "patch"
        elif model_type == "code" and (
            "json object" in lowered
            or "json array" in lowered
            or "output only a json object" in lowered
        ):
            model_type = "json"

        if model_type == "patch":
            system_prompt = PATCH_SYSTEM_PROMPT
        elif model_type == "json":
            system_prompt = JSON_SYSTEM_PROMPT
        elif model_type == "docs":
            system_prompt = DOCS_SYSTEM_PROMPT
        elif model_type == "code":
            system_prompt = CODE_SYSTEM_PROMPT
        else:
            system_prompt = None

    def _finalize(provider, result):
        if not result:
            return ""
        generate.last_model_used = provider
        try:
            from engine.reasoning_ledger import record_interaction
            record_interaction("heavy_generation", prompt, result, provider)
        except Exception:
            pass
        return result

    result = _call_openrouter(
        prompt,
        api_keys.get("openrouter", ""),
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        allow_fallback=allow_fallback,
    )
    if result:
        return _finalize("openrouter", result)

    if not allow_fallback:
        print("    ⏳ Primary model unavailable, fallback disabled. Deferring to next cycle.")
        return ""

    if _openrouter_daily_exhausted():
        print("    🛑 OpenRouter daily quota exhausted. Deferring instead of burning Groq/Mistral.")
        return ""

    print("    🔄 OpenRouter busy → trying Groq")
    result = _call_groq(
        prompt,
        api_keys.get("groq", ""),
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if result:
        return _finalize("groq", result)

    print("    🔄 Groq busy → trying Mistral")
    result = _call_mistral(
        prompt,
        api_keys.get("mistral", ""),
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if result:
        return _finalize("mistral", result)

    if _openrouter_daily_exhausted():
        print("    ⏳ Providers busy and OpenRouter daily quota locked. Deferring to next cycle.")
        return ""

    print("    ⏳ OpenRouter, Groq, and Mistral busy. Waiting 30s...")
    time.sleep(30)

    result = _call_openrouter(
        prompt,
        api_keys.get("openrouter", ""),
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if result:
        return _finalize("openrouter", result)

    result = _call_groq(
        prompt,
        api_keys.get("groq", ""),
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _finalize("groq", result)



def _call_mistral(prompt, api_key, system_prompt="", max_tokens=8192, temperature=0.2):
    """Call Mistral API directly (OpenAI-compatible)."""
    import requests
    if not api_key:
        return ""
    
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": "mistral-small-latest",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    try:
        from overnight.budget_manager import APIBudgetManager
        budget = APIBudgetManager()
        if not budget.can_proceed("mistral"):
            print("    🔒 Mistral budget exhausted")
            return ""
        if not budget.wait_if_needed("mistral", timeout=30):
            print("    🔒 Mistral budget wait timeout")
            return ""
        
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        budget.record_call("mistral")
        
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        elif resp.status_code == 429:
            print("    ⚠️ Mistral 429 Rate Limit")
            return ""
        else:
            print(f"    ⚠️ Mistral error {resp.status_code}")
            return ""
    except Exception as e:
        print(f"    ⚠️ Mistral exception: {e}")
        return ""


def strip_fences(text):
    """Remove markdown code fences."""
    if not text:
        return ""
    text = text.strip()

    m = re.search(r"^```[a-zA-Z0-9_+-]*[ \t]*\n?(.*?)\n?```[ \t]*$", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    text = re.sub(r"^```[a-zA-Z0-9_+-]*[ \t]*\n?", "", text)
    text = re.sub(r"\n?```[ \t]*$", "", text)
    return text.strip()




def critique(code, task_description, api_keys):
    """Have Gemini critique generated code."""
    critique_prompt = f"""Review this code for a SOC automation platform.

TASK: {task_description}

CODE:
{code}

Check for: hallucinated imports, wrong signatures, deprecated APIs, logic bugs.

Respond with:
APPROVE if production-ready
REVISE:<fixes needed> if changes required"""

    critique_text = _call_gemini(critique_prompt, api_keys.get("gemini", ""),
                                 max_tokens=1000, temperature=0.1)
    if not critique_text:
        return True, "No critique available"

    critique_text = strip_fences(critique_text).strip()
    first_line = critique_text.splitlines()[0].upper() if critique_text else ""

    if first_line.startswith("APPROVE"):
        return True, critique_text
    if "APPROVE" in first_line:
        return True, critique_text

    return False, critique_text



def generate_with_critique(prompt, task_description, api_keys, model_type="code", max_iterations=2, max_tokens=8192):
    """Generate with cross-model critique loop."""
    current = generate(prompt, api_keys, model_type=model_type, max_tokens=max_tokens)
    if not current:
        return ""
    current = strip_fences(current)

    for i in range(max_iterations):
        is_good, critique_text = critique(current, task_description, api_keys)
        if is_good:
            return current

        fix_prompt = f"""Original task: {prompt}
Previous output: {current}
Reviewer feedback: {critique_text}
Fix the issues. Output ONLY corrected code."""

        current = generate(fix_prompt, api_keys, model_type=model_type, max_tokens=max_tokens)
        if not current:
            return current
        current = strip_fences(current)
        time.sleep(RATE_LIMIT_SLEEP)

    return current


def quick_generate(prompt, model_type="code"):
    api_keys = load_api_keys()
    return generate(prompt, api_keys, model_type=model_type)


def quick_critique_loop(prompt, task_description, model_type="code", max_iterations=2):
    api_keys = load_api_keys()
    return generate_with_critique(prompt, task_description, api_keys,
                                   model_type=model_type, max_iterations=max_iterations)


def get_fallback_status():
    """Return current fallback state for monitoring."""
    return {
        "current_model": _current_model,
        "fallback_list": _fallback_list or [],
        "calls_since_primary_check": _calls_since_primary_check,
    }
