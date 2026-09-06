#!/usr/bin/env python3
import datetime
import py_compile
import re
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()
LLM = ROOT / "overnight" / "llm_client.py"
SI = ROOT / "overnight" / "self_improver.py"
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def log(msg):
    print(msg)

def backup(path: Path):
    if not path.exists():
        return None
    bak = path.with_name(path.name + f".bak_fix_{STAMP}")
    shutil.copy2(path, bak)
    log(f"Backed up {path} -> {bak.name}")
    return bak

def apply_regex(text, pattern, repl, desc, flags=0, count=1, literal=True):
    try:
        if literal:
            new_text, n = re.subn(pattern, lambda m: repl, text, count=count, flags=flags)
        else:
            new_text, n = re.subn(pattern, repl, text, count=count, flags=flags)
    except Exception as exc:
        log(f"[ERR ] {desc}: {exc}")
        return text, False

    if n:
        log(f"[OK  ] {desc}")
        return new_text, True

    log(f"[MISS] {desc}")
    return text, False

def apply_exact(text, old, new, desc):
    if old in text:
        log(f"[OK  ] {desc}")
        return text.replace(old, new, 1), True
    log(f"[MISS] {desc}")
    return text, False

def compile_check(path: Path, bak: Path):
    try:
        py_compile.compile(str(path), doraise=True)
        log(f"[OK  ] {path} compiles")
        return True
    except Exception as exc:
        log(f"[FAIL] {path} does not compile: {exc}")
        if bak and bak.exists():
            failed = path.with_name(path.name + f".failed_fix_{STAMP}")
            shutil.move(str(path), str(failed))
            shutil.copy2(bak, path)
            log(f"[RESTORED] {path} from backup. Failed patch saved as {failed.name}")
        return False

HELPERS = r'''
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
'''

NEW_GENERATE = r'''
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
'''

NEW_CALL_GEMINI = r'''
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
'''

NEW_LOAD_API_KEYS = r'''
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
'''

NEW_STRIP_FENCES = r'''
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
'''

NEW_CRITIQUE = r'''
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
'''

NEW_TDD = r'''
def _generate_tdd_test(issue_desc: str, target_file: str, api_keys: dict) -> str:
    # AST_SIGNATURE_FIX_V1
    sig_context = ""
    try:
        target_path = ROOT / target_file
        tree = ast.parse(target_path.read_text())
        defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if defs:
            sigs = []
            for d in defs[:10]:
                args = [a.arg for a in d.args.args if a.arg not in ('self', 'cls')]
                sigs.append(f"def {d.name}({', '.join(args)})")
            sig_context = f"REAL FUNCTION SIGNATURES IN THIS FILE (DO NOT INVENT NEW ARGUMENTS):\n{chr(10).join(sigs)}\n"
    except Exception as e:
        print(f"       ⚠️ TDD AST sig read failed: {e}")
        sig_context = ""

    prompt = (
        f"You are a senior QA engineer. Write a minimal failing pytest test for:\n"
        f"ISSUE: {issue_desc}\nTARGET FILE: {target_file}\n"
        f"PROJECT STRUCTURE: Files live in subdirectories (tools/, engine/, memory/).\n"
        f"IMPORT RULE: To import, you MUST use sys.path manipulation. Example:\n"
        f"import sys\nsys.path.insert(0, 'tools')  # or 'engine'\nfrom file_name import function_name\n\n"
        f"{sig_context}\n"
        "Output ONLY the python code for the test function. No markdown.\n"
    )
    raw = generate(prompt, api_keys, temperature=0.1, model_type="code")
    if not raw: return None
    code = strip_fences(raw)
    try: ast.parse(code); return code
    except SyntaxError: return None
'''

def patch_llm_client():
    if not LLM.exists():
        log(f"[SKIP] {LLM} not found")
        return

    bak = backup(LLM)
    text = LLM.read_text()

    # 1. Insert helper/system-prompt block once
    if "# LLM_FIX_HELPERS_V1" not in text:
        helper_pat = re.compile(r"(MAX_RETRIES = 3[^\n]*)", re.M)
        def _add_helpers(m):
            return m.group(1) + "\n\n# LLM_FIX_HELPERS_V1\n" + HELPERS
        new_text, n = helper_pat.subn(_add_helpers, text, count=1)
        if n:
            text = new_text
            log("[OK  ] Insert system prompts / budget helpers")
        else:
            log("[MISS] Insert system prompts / budget helpers")
    else:
        log("[SKIP] System prompts / budget helpers already present")

    # 2. Portable cache paths
    if "BASE_DIR = Path(__file__).resolve().parent" not in text:
        text, _ = apply_regex(
            text,
            r'CACHE_FILE = Path\(".*?model_fallback_cache\.json"\)[^\n]*\nGROQ_CACHE_FILE = Path\(".*?groq_model_cache\.json"\)[^\n]*',
            'BASE_DIR = Path(__file__).resolve().parent\nCACHE_FILE = BASE_DIR / "model_fallback_cache.json"\nGROQ_CACHE_FILE = BASE_DIR / "groq_model_cache.json"',
            "Portable cache paths",
            literal=True,
        )
    else:
        log("[SKIP] Portable cache paths already present")

    # 3. OpenRouter: missing API key guard
    try:
        openrouter_section = text.split("def _call_openrouter", 1)[1].split("def _call_gemini", 1)[0]
    except IndexError:
        openrouter_section = ""

    if "if not api_key:" not in openrouter_section:
        text, _ = apply_regex(
            text,
            r'(def _call_openrouter\([^\n]*\):\s*"""[^"]*"""\s*global _current_model, _calls_since_primary_check\n)',
            r'\1\n    if not api_key:\n        return ""\n',
            "OpenRouter: guard missing API key",
            literal=False,
        )
    else:
        log("[SKIP] OpenRouter API key guard already present")

    # 4. OpenRouter: cap attempts per generate
    if "max_attempts = 1 if not allow_fallback else 3" not in text:
        text, _ = apply_regex(
            text,
            r'([ \t]*)for try_model in models_to_try:\s*# Count every attempt[^\n]*\s*from overnight import openrouter_quota\s*openrouter_quota\.record_attempt\(\)',
            r'''\1attempts = 0
\1max_attempts = 1 if not allow_fallback else 3

\1for try_model in models_to_try:
\1    attempts += 1
\1    if attempts > max_attempts:
\1        break

\1    # Count every attempt against the daily quota
\1    from overnight import openrouter_quota
\1    if not openrouter_quota.is_available():
\1        break
\1    openrouter_quota.record_attempt()
\1    if not openrouter_quota.is_available():
\1        break''',
            "OpenRouter: cap attempts and recheck quota",
            literal=False,
        )
    else:
        log("[SKIP] OpenRouter attempt cap already present")

    # 5. OpenRouter: auth failure handling
    if "OpenRouter auth failure for" not in text:
        text, _ = apply_regex(
            text,
            r'([ \t]*)elif resp\.status_code == 429:',
            r'''\1elif resp.status_code in (401, 403):
\1    print(f"    ❌ OpenRouter auth failure for {try_model}: {resp.status_code}")
\1    return ""
\1elif resp.status_code == 429:''',
            "OpenRouter: handle 401/403 auth errors",
            literal=False,
            count=1,
        )
    else:
        log("[SKIP] OpenRouter auth handling already present")

    # 6. OpenRouter: record successful calls in budget manager
    if '_budget_record("openrouter")' not in text:
        text, _ = apply_regex(
            text,
            r'([ \t]*)_current_model = try_model\s*return content',
            r'''\1_current_model = try_model
\1_budget_record("openrouter")
\1return content''',
            "OpenRouter: record successful calls in budget manager",
            literal=False,
            count=1,
        )
    else:
        log("[SKIP] OpenRouter budget recording already present")

    # 7. Gemini: safer auth/parsing/budget recording
    if "x-goog-api-key" not in text:
        text, _ = apply_regex(
            text,
            r'def _call_gemini\(.*?(?=\ndef discover_groq_models)',
            NEW_CALL_GEMINI + "\n\n",
            "Gemini: safer auth, parsing, budget recording",
            flags=re.DOTALL,
            literal=True,
        )
    else:
        log("[SKIP] Gemini safer client already present")

    # 8. Gemini pre-analysis prompt fix
    if "FILE: {file_path}" not in text:
        text, _ = apply_regex(
            text,
            r'FILE:\s*\nGHOSTBUSTER PROTOCOL:.*?\{file_path\}\s*\nCODE:',
            '''FILE: {file_path}

GHOSTBUSTER PROTOCOL: You MUST NOT report stylistic issues, missing docstrings, type hints, naming conventions, or code complexity. ONLY report genuine logic bugs, security vulnerabilities, or broken tests. If the code is logically sound, return an empty list or 'No issues'.

CODE:''',
            "Gemini pre-analysis: fix malformed prompt",
            flags=re.DOTALL,
            literal=True,
        )
    else:
        log("[SKIP] Gemini pre-analysis prompt already fixed")

    # 9. Groq: budget-aware model check
    if '_budget_allow("groq", try_model)' not in text:
        text, _ = apply_regex(
            text,
            r'([ \t]*)if _in_cooldown\(try_model\):\s*continue[^\n]*\n',
            r'''\1if _in_cooldown(try_model):
\1    continue  # don't waste a request probing a cooled-down model
\1if not _budget_allow("groq", try_model):
\1    continue  # budget manager says no

''',
            "Groq: budget-aware model check",
            literal=False,
            count=1,
        )
    else:
        log("[SKIP] Groq budget-aware check already present")

    # 10. Groq: remove dangerous **Answer** stripping
    if "**Answer**" in text:
        text, _ = apply_regex(
            text,
            r'[ \t]*if "\*\*Answer\*\*" in content:.*?content = ap\n',
            "",
            "Groq: remove dangerous **Answer** stripping",
            flags=re.DOTALL,
            literal=True,
        )
    else:
        log("[SKIP] Groq **Answer** stripping already removed")

    # 11. Groq: centralize budget recording
    if '_budget_record("groq")' not in text:
        text, _ = apply_regex(
            text,
            r'([ \t]*)# Record Groq call in budget manager\s*try:\s*from overnight\.budget_manager import APIBudgetManager\s*APIBudgetManager\(\)\.record_call\("groq"\)\s*except Exception:\s*pass[^\n]*',
            r'\1_budget_record("groq")',
            "Groq: centralize budget recording",
            literal=False,
            count=1,
        )
    else:
        log("[SKIP] Groq centralized budget recording already present")

    # 12. Mistral: respect budget wait result
    if "Mistral budget wait timeout" not in text:
        text, _ = apply_regex(
            text,
            r'([ \t]*)budget\.wait_if_needed\("mistral", timeout=30\)\n',
            r'''\1if not budget.wait_if_needed("mistral", timeout=30):
\1    print("    🔒 Mistral budget wait timeout")
\1    return ""
''',
            "Mistral: respect budget wait result",
            literal=False,
            count=1,
        )
    else:
        log("[SKIP] Mistral budget wait already fixed")

    # 13. Replace generate() with corrected router/system-prompt logic
    if 'def generate(prompt, api_keys, model_type="code", max_tokens=8192, temperature=0.2, allow_fallback=True, system_prompt=None):' not in text:
        text, _ = apply_regex(
            text,
            r'def generate\(.*?(?=\ndef _call_mistral)',
            NEW_GENERATE + "\n\n",
            "generate(): corrected router + system prompts",
            flags=re.DOTALL,
            literal=True,
        )
    else:
        log("[SKIP] Corrected generate() already present")

    # 14. load_api_keys(): add Mistral and better .env parsing
    if '"mistral": os.getenv("MISTRAL_API_KEY", "")' not in text:
        text, _ = apply_regex(
            text,
            r'def load_api_keys\(.*?(?=\ndef gemini_pre_analysis)',
            NEW_LOAD_API_KEYS + "\n\n",
            "load_api_keys(): add Mistral + robust .env parsing",
            flags=re.DOTALL,
            literal=True,
        )
    else:
        log("[SKIP] load_api_keys() already includes Mistral")

    # 15. strip_fences(): robust fence stripping
    if 're.search(r"^```' not in text:
        text, _ = apply_regex(
            text,
            r'def strip_fences\(.*?(?=\ndef critique)',
            NEW_STRIP_FENCES + "\n\n",
            "strip_fences(): robust fence stripping",
            flags=re.DOTALL,
            literal=True,
        )
    else:
        log("[SKIP] Robust strip_fences() already present")

    # 16. critique(): normalize APPROVE detection
    if 'first_line.startswith("APPROVE")' not in text:
        text, _ = apply_regex(
            text,
            r'def critique\(.*?(?=\ndef generate_with_critique)',
            NEW_CRITIQUE + "\n\n",
            "critique(): normalize APPROVE detection",
            flags=re.DOTALL,
            literal=True,
        )
    else:
        log("[SKIP] Normalized critique() already present")

    LLM.write_text(text)
    compile_check(LLM, bak)

def patch_self_improver():
    if not SI.exists():
        log(f"[SKIP] {SI} not found")
        return

    bak = backup(SI)
    text = SI.read_text()

    # 1. Replace weak TDD signature extraction with AST-based extraction
    if "AST_SIGNATURE_FIX_V1" not in text:
        text, _ = apply_regex(
            text,
            r'def _generate_tdd_test\(.*?(?=\ndef _failed_test_ids)',
            NEW_TDD + "\n\n",
            "self_improver: AST-based TDD signature extraction",
            flags=re.DOTALL,
            literal=True,
        )
    else:
        log("[SKIP] AST-based TDD signature extraction already present")

    # 2. Explicit patch mode for Aider patch generation
    if 'model_type="patch"' not in text:
        text, _ = apply_regex(
            text,
            r'raw = generate\(prompt, api_keys, temperature=current_temp, max_tokens=current_max\)',
            'raw = generate(prompt, api_keys, temperature=current_temp, max_tokens=current_max, model_type="patch")',
            "self_improver: explicit model_type='patch' for fixes",
            literal=True,
            count=1,
        )
    else:
        log("[SKIP] Explicit patch model_type already present")

    # 3. Explicit JSON mode for forensic analysis
    if 'model_type="json"' not in text:
        text, _ = apply_regex(
            text,
            r'raw = generate\(prompt, api_keys, temperature=0\.1, max_tokens=1024\)',
            'raw = generate(prompt, api_keys, temperature=0.1, max_tokens=1024, model_type="json")',
            "self_improver: explicit model_type='json' for forensics",
            literal=True,
            count=1,
        )
    else:
        log("[SKIP] Explicit JSON model_type already present")

    SI.write_text(text)
    compile_check(SI, bak)

def main():
    log("=== SOC Autopilot programmatic patcher ===")
    patch_llm_client()
    patch_self_improver()
    log("Done.")
    log("Review changes with: git diff")
    log("Backups match: *.bak_fix_*")

if __name__ == "__main__":
    main()
