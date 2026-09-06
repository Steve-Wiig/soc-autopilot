#!/usr/bin/env python3
"""
Documentation & Config Generator.
Unlike phase6_generate.py, this does NOT validate Python syntax.
Supports: Markdown, YAML, SQL, XML output.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from overnight.llm_client import generate_with_critique, load_api_keys, strip_fences

try:
    import requests
except ImportError:
    print("FAIL: requests not installed")
    sys.exit(2)

ROOT = Path(str(ROOT))
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent"
MAX_ATTEMPTS = 3
RATE_LIMIT_SLEEP = 7

def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def validate_output(content, file_type):
    """Validate output based on expected file type."""
    if not content:
        return False, "Empty response"
    if len(content) < 50:
        return False, "Response too short"
    
    if file_type == "markdown":
        # Must have headers
        if '#' not in content:
            return False, "No markdown headers found"
    elif file_type == "yaml":
        # Basic YAML validation
        try:
            import yaml
            yaml.safe_load(content)
        except:
            return False, "Invalid YAML"
    elif file_type == "sql":
        # Must have SQL keywords
        if not any(kw in content.upper() for kw in ['CREATE', 'INSERT', 'ALTER', 'SELECT']):
            return False, "No SQL statements found"
    
    return True, None

def detect_file_type(target):
    """Detect expected output type from file extension."""
    ext = Path(target).suffix.lower()
    mapping = {'.md': 'markdown', '.yaml': 'yaml', '.yml': 'yaml', '.sql': 'sql', '.xml': 'xml', '.py': 'python'}
    return mapping.get(ext, 'text')

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 overnight/generate_docs.py <tasks_file.json>")
        print("Examples:")
        print("  python3 overnight/generate_docs.py overnight/tasks_phase8.json")
        print("  python3 overnight/generate_docs.py overnight/tasks_phase10.json")
        sys.exit(1)
    
    tasks_file = ROOT / sys.argv[1]
    if not tasks_file.exists():
        print(f"ERROR: {tasks_file} not found")
        sys.exit(2)
    
    tasks = json.loads(tasks_file.read_text())
    open_tasks = [t for t in tasks if t.get("status") == "open"]

    # Normalize: generator expects 'description'; v11.11 schema uses 'prompt_hint'
    for t in open_tasks:
        if not t.get("description"):
            t["description"] = (
                t.get("prompt_hint")
                or t.get("contract")
                or f"Generate {t.get('target', 'document')}"
            )
    
    print("=" * 70)
    print(f"DOCUMENTATION/CONFIG GENERATION")
    print(f"Tasks: {len(open_tasks)}")
    print("=" * 70)
    
    load_env()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("CONFIG ERROR: GEMINI_API_KEY not set")
        sys.exit(2)
    
    success = 0
    failed = 0
    
    for task in open_tasks:
        target = task["target"]
        file_type = detect_file_type(target)
        target_path = ROOT / target
        
        print(f"\n  [{task['id']}] {target} ({file_type})")
        
        # Read relevant source files for context
        context = ""
        if file_type == "markdown":
            # Include module structure for architecture docs
            for d in ["engine", "orchestrator", "memory"]:
                dir_path = ROOT / d
                if dir_path.exists():
                    modules = [f.stem for f in dir_path.glob("*.py") if f.name != "__init__.py"]
                    context += f"\n{d}/ modules: {', '.join(modules)}"
        
        prompt = f"""{task['prompt_hint']}

PROJECT CONTEXT:
- This is soc-autopilot: a local SOC automation platform
- Layers: engine (intake, sanitization, queue, enrichment, writeback), orchestrator (model routing, context), memory (embeddings, retention, RAG)
- Target audience: SOC engineers setting up and operating the platform
{context}

OUTPUT FORMAT: {file_type}
OUTPUT FILE: {target}

RULES:
1. Output ONLY the raw {file_type} content. No markdown fences, no explanations.
2. Be comprehensive and specific to this project.
3. Use exact module names, function names, and file paths from the codebase.
4. Include real examples where possible.
5. Minimum 100 lines of content.
"""
        
        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"    Attempt {attempt}/{MAX_ATTEMPTS}...")
            
            api_keys = load_api_keys()
            response = generate_with_critique(prompt, task["description"], api_keys, model_type="docs")
            if not response:
                print(f"    ⚠️  Empty response")
                time.sleep(RATE_LIMIT_SLEEP)
                continue
            
            content = strip_fences(response)
            valid, error = validate_output(content, file_type)
            
            if valid:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(content)
                lines = len(content.splitlines())
                print(f"    ✅ Written: {lines} lines")
                success += 1
                break
            else:
                print(f"    ❌ {error}")
                if attempt >= MAX_ATTEMPTS:
                    failed += 1
                time.sleep(RATE_LIMIT_SLEEP)
        
        time.sleep(RATE_LIMIT_SLEEP)
    
    # Update task statuses
    for task in tasks:
        target_path = ROOT / task["target"]
        if target_path.exists() and target_path.stat().st_size > 100:
            task["status"] = "done"
    
    tasks_file.write_text(json.dumps(tasks, indent=2))
    
    print(f"\n{'='*70}")
    print(f"RESULTS: {success} generated, {failed} failed")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()
