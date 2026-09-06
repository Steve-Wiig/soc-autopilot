#!/usr/bin/env python3
"""
Phase 6 Generation: Tests, tools, and integration tests.
Uses Gemini API with rate limiting, syntax validation, and test verification.

Usage:
    python3 overnight/phase6_generate.py [--dry-run] [--max-tasks N]
"""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("FAIL: requests not installed")
    sys.exit(2)

PROJECT_ROOT = Path(str(ROOT))
import argparse as _ap
from overnight.llm_client import generate_with_critique, load_api_keys, strip_fences
_parser = _ap.ArgumentParser()
_parser.add_argument("--tasks-file", default="overnight/tasks_phase6.json")
_args, _ = _parser.parse_known_args()
TASKS_FILE = PROJECT_ROOT / _args.tasks_file
EVIDENCE_DIR = PROJECT_ROOT / "overnight" / "evidence"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent"
RATE_LIMIT_SLEEP = 7
MAX_GENERATIONS_PER_TASK = 3
MAX_TASKS_DEFAULT = 10


def load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())



def validate_python(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def build_prompt(task: dict, critique: str = None) -> str:
    prompt = f"""You are generating code for the soc-autopilot project.

TASK: {task['prompt_hint']}

TARGET FILE: {task['target']}
TASK TYPE: {task['type']}

CRITICAL RULES:
- Output ONLY valid Python code. No markdown fences, no explanations, no preamble.
- Import from the REAL modules (e.g., from engine.queue_manager import TriageQueueManager).
- Do NOT define phantom classes or mock interfaces that don't exist.
- Do NOT use module-level side effects (no open(), no logging.basicConfig(), no exit() at module level).
- All executable code must be inside functions or if __name__ == "__main__": blocks.
- Use pytest conventions: test functions start with test_, use fixtures where appropriate.
- For tools: include argparse with --dry-run support, exit codes 0/1/2/3.
- Keep the file valid Python 3.
"""
    if critique:
        prompt += f"\nPREVIOUS ATTEMPT FAILED WITH:\n{critique}\n\nFix the issues and regenerate.\n"
    return prompt


def run_tests_for_file(target: str) -> tuple:
    """Run pytest on the generated test file. Returns (passed, output)."""
    if not target.startswith("tests/"):
        return True, "Not a test file, skipping test run"
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", target, "-v", "--tb=short"],
            capture_output=True, text=True, timeout=45,
            cwd=str(PROJECT_ROOT)
        )
        passed = result.returncode == 0
        output = result.stdout[-500:] if result.stdout else result.stderr[-500:]
        return passed, output
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: Test hung (likely trying to load ML model or make network call)"


def process_task(task: dict, api_key: str, dry_run: bool = False) -> bool:
    target_path = PROJECT_ROOT / task["target"]
    print(f"\n  [{task['id']}] {task['target']}")
    
    if target_path.exists():
        print(f"    SKIP: File already exists")
        return True
    
    for generation in range(1, MAX_GENERATIONS_PER_TASK + 1):
        print(f"    Generation {generation}/{MAX_GENERATIONS_PER_TASK}...")
        
        prompt = build_prompt(task)
        api_keys = load_api_keys()
        response = generate_with_critique(prompt, task["description"], api_keys, model_type="code")
        
        if not response:
            print(f"    FAIL: Empty API response")
            return False
        
        code = strip_fences(response)
        
        if not validate_python(code):
            print(f"    FAIL: Invalid Python syntax")
            if generation < MAX_GENERATIONS_PER_TASK:
                time.sleep(RATE_LIMIT_SLEEP)
                continue
            return False
        
        if dry_run:
            lines = len(code.splitlines())
            print(f"    DRY-RUN: Would write {lines} lines to {task['target']}")
            return True
        
        # Write the file
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(code)
        print(f"    Written: {len(code.splitlines())} lines")
        
        # Run tests if it's a test file
        if task["target"].startswith("tests/"):
            passed, output = run_tests_for_file(task["target"])
            if passed:
                print(f"    ✅ Tests PASS")
                return True
            else:
                print(f"    ❌ Tests FAIL: {output[:200]}")
                if generation < MAX_GENERATIONS_PER_TASK:
                    # Delete failed file and retry
                    target_path.unlink()
                    time.sleep(RATE_LIMIT_SLEEP)
                    continue
                # Keep the file but mark as needing manual fix
                print(f"    ⚠️  Keeping file for manual review")
                return False
        
        # For non-test files, just verify syntax
        print(f"    ✅ Syntax valid")
        return True
    
    return False


def main():
    parser = argparse.ArgumentParser(description="Phase 6 Generation")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--max-tasks", type=int, default=MAX_TASKS_DEFAULT)
    args = parser.parse_args()
    
    load_env()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("CONFIG ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(2)
    
    tasks = json.loads(TASKS_FILE.read_text())
    tasks = [t for t in tasks if t["status"] == "open"][:args.max_tasks]
    
    print(f"{'='*60}")
    print(f"PHASE 6 GENERATION")
    print(f"{'='*60}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")
    print(f"Tasks: {len(tasks)}")
    print(f"Estimated API calls: {len(tasks) * MAX_GENERATIONS_PER_TASK} max")
    print(f"Estimated time: ~{len(tasks) * RATE_LIMIT_SLEEP}s minimum")
    print(f"{'='*60}")
    
    success = 0
    failed = 0
    
    for i, task in enumerate(tasks):
        if process_task(task, api_key, dry_run=args.dry_run):
            success += 1
        else:
            failed += 1
        
        # Rate limit between tasks
        if i < len(tasks) - 1:
            time.sleep(RATE_LIMIT_SLEEP)
    
    print(f"\n{'='*60}")
    print(f"RESULTS: {success} success, {failed} failed")
    print(f"{'='*60}")
    
    if not args.dry_run and success > 0:
        print(f"\nNext steps:")
        print(f"  1. python3 -m pytest tests/ -v")
        print(f"  2. python3 integration_verifier.py")
        print(f"  3. git add -A && git commit -m 'Phase 6: add tests and tools'")


if __name__ == "__main__":
    main()
