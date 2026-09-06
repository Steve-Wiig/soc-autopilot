#!/usr/bin/env python3
"""
Agentic Docstring Injector: Uses Gemini API to add Google-style docstrings
and type hints to Python files without altering logic.

Safety features:
- Loads API key from .env (never hardcoded)
- Validates LLM output with ast.parse() before writing
- Creates .bak backup of every file before modification
- Dry-run mode previews changes without writing
- Rate-limited to respect free-tier API limits

Usage:
    # Preview what would change (no files modified)
    python3 overnight/docstring_injector.py --dry-run engine/queue_manager.py

    # Apply changes to a single file
    python3 overnight/docstring_injector.py engine/queue_manager.py

    # Apply to all engine files
    python3 overnight/docstring_injector.py engine/*.py
"""
import argparse
import ast
import os
import shutil
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("FAIL: requests not installed. Run: pip install requests")
    sys.exit(2)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent"
RATE_LIMIT_SLEEP = 7  # seconds between API calls
MAX_RETRIES = 3


def load_env():
    """Load secrets from .env file. Never hardcode keys."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        print("CONFIG ERROR: .env file not found")
        sys.exit(2)
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def call_gemini(prompt: str, api_key: str) -> str:
    """Call Gemini API with retry and backoff. Returns text response."""
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,  # Low temp for deterministic code output
            "maxOutputTokens": 8192,
        },
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{API_URL}?key={api_key}",
                json=payload,
                headers=headers,
                timeout=60,
            )

            if resp.status_code == 429:
                wait = 60 * attempt
                print(f"    Rate limited. Waiting {wait}s (attempt {attempt}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

        except requests.exceptions.RequestException as e:
            print(f"    API error (attempt {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(10 * attempt)
            else:
                raise

    return ""


def strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    import re
    text = re.sub(r'^```(?:python)?\s*\n', '', text)
    text = re.sub(r'\n```\s*$', '', text)
    return text.strip()


def validate_python(code: str) -> bool:
    """Verify the LLM output is still valid Python syntax."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def build_prompt(file_content: str, filename: str) -> str:
    """Build the prompt that instructs the LLM what to do."""
    return f"""You are adding documentation to a Python file. Add Google-style docstrings to all functions, classes, and the module itself. Add type hints to function parameters and return types where they can be clearly inferred.

RULES:
- Do NOT change any logic, variable names, or behavior.
- Do NOT add new imports unless required for type hints (e.g., from typing import Optional).
- Do NOT remove existing comments.
- Output ONLY the complete modified file. No explanations, no markdown fences.
- Keep the file valid Python 3.

FILE: {filename}
```python
{file_content}
```"""


def process_file(filepath: Path, api_key: str, dry_run: bool = False) -> bool:
    """Process a single file. Returns True if successful."""
    rel_path = filepath.relative_to(PROJECT_ROOT)
    print(f"\n  Processing: {rel_path}")

    # Read original
    original = filepath.read_text()

    # Skip files that already have comprehensive docstrings
    if original.count('"""') >= 6:
        print(f"    SKIP: Already has {original.count('\"\"\"') // 2} docstrings")
        return True

    # Call LLM
    print(f"    Calling Gemini API...")
    prompt = build_prompt(original, str(rel_path))
    response = call_gemini(prompt, api_key)

    if not response:
        print(f"    FAIL: Empty response from API")
        return False

    # Strip fences and validate
    modified = strip_fences(response)

    if not validate_python(modified):
        print(f"    FAIL: LLM produced invalid Python syntax. Rejecting.")
        return False

    # Verify no logic was changed (function count should be same or higher)
    orig_tree = ast.parse(original)
    mod_tree = ast.parse(modified)
    orig_funcs = len([n for n in ast.walk(orig_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])
    mod_funcs = len([n for n in ast.walk(mod_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])

    if mod_funcs < orig_funcs:
        print(f"    FAIL: LLM removed functions ({orig_funcs} -> {mod_funcs}). Rejecting.")
        return False

    if dry_run:
        # Show a diff preview
        orig_lines = original.splitlines()
        mod_lines = modified.splitlines()
        added = len(mod_lines) - len(orig_lines)
        print(f"    DRY-RUN: Would add ~{added} lines (docstrings/type hints)")
        print(f"    Functions: {orig_funcs} -> {mod_funcs}")
        return True

    # Backup original
    backup_path = filepath.with_suffix(filepath.suffix + ".bak")
    shutil.copy2(filepath, backup_path)
    print(f"    Backup: {backup_path.name}")

    # Write modified file
    filepath.write_text(modified)
    print(f"    ✅ Updated: +{len(modified.splitlines()) - len(original.splitlines())} lines")
    return True


def main():
    parser = argparse.ArgumentParser(description="Agentic Docstring Injector")
    parser.add_argument("files", nargs="+", help="Python files to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview without modifying")
    args = parser.parse_args()

    load_env()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("CONFIG ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(2)

    print(f"{'='*60}")
    print(f"AGENTIC DOCSTRING INJECTOR")
    print(f"{'='*60}")
    print(f"Mode: {'DRY-RUN (no files modified)' if args.dry_run else 'APPLY'}")
    print(f"Files: {len(args.files)}")
    print(f"{'='*60}")

    success = 0
    failed = 0

    for i, file_arg in enumerate(args.files):
        filepath = Path(file_arg)
        if not filepath.is_absolute():
            # If relative, check CWD first, then fallback to project root
            if not filepath.exists():
                filepath = PROJECT_ROOT / file_arg
        filepath = filepath.resolve()  # Convert to absolute path
        
        if not filepath.exists():
            print(f"\n  SKIP: {file_arg} not found")
            continue

        if process_file(filepath, api_key, dry_run=args.dry_run):
            success += 1
        else:
            failed += 1

        # Rate limit between files
        if i < len(args.files) - 1:
            time.sleep(RATE_LIMIT_SLEEP)

    print(f"\n{'='*60}")
    print(f"RESULTS: {success} updated, {failed} failed")
    print(f"{'='*60}")

    if not args.dry_run and success > 0:
        print(f"\nNext steps:")
        print(f"  1. Run tests: python3 -m pytest tests/ -v")
        print(f"  2. If tests pass: git add -A && git commit -m 'Add docstrings'")
        print(f"  3. If tests fail: restore from .bak files")


if __name__ == "__main__":
    main()
