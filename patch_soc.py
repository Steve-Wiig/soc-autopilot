import os, re
from pathlib import Path
from datetime import datetime, timezone

root = Path('.')
print("="*60)
print("SOC-AUTOPILOT GATED PATCHER (Targeted & Safe)")
print("="*60)

def safe_read(filepath):
    try:
        return filepath.read_text(encoding='utf-8')
    except Exception:
        return None

def safe_write(filepath, content):
    try:
        filepath.write_text(content, encoding='utf-8')
        return True
    except Exception:
        return False

def gated_replace(filepath, vulnerable_snippet, fixed_snippet, desc):
    txt = safe_read(filepath)
    if not txt or "HARDENED:" in txt:
        return
    if vulnerable_snippet in txt:
        new_txt = txt.replace(vulnerable_snippet, fixed_snippet)
        new_txt = f"# HARDENED: {datetime.now(timezone.utc).isoformat()}\n" + new_txt
        if safe_write(filepath, new_txt):
            print(f"[+] PATCHED: {desc}")
        else:
            print(f"[!] ERROR: Could not write to {filepath}")

def fix_swallowed_exceptions(filepath):
    txt = safe_read(filepath)
    if not txt or "HARDENED:" in txt:
        return
    
    # Match exactly: except Exception:\n    pass (preserving indentation)
    pattern = re.compile(r'^([ \t]*)except\s+Exception\s*:\s*\n[ \t]*pass\b', re.MULTILINE)
    
    def replacer(match):
        indent = match.group(1)
        return (
            f"{indent}except Exception as e:\n"
            f"{indent}    # HARDENED: Fail closed with telemetry\n"
            f"{indent}    import logging\n"
            f"{indent}    logging.error(f'CONTROL-PLANE FAILURE in {filepath.name}: {{e}}')\n"
            f"{indent}    raise"
        )
        
    if pattern.search(txt):
        new_txt = pattern.sub(replacer, txt)
        if safe_write(filepath, new_txt):
            print(f"[+] PATCHED: Swallowed exception in {filepath}")
        else:
            print(f"[!] ERROR: Could not write to {filepath}")

# 1. Core P0/P1 targeted fixes
gated_replace(
    root / "tools" / "shadow_canary.py",
    "return False",
    "return {'passed': False, 'failures': [{'error': 'Canary failed'}]}",
    "P0-3: Shadow Canary strict return contract"
)

for f in [root / "tests" / "test_defeat_ledger.py", root / "tests" / "test_safety_gates.py"]:
    gated_replace(
        f,
        "/home/swiig/Documents/soc-autopilot",
        "str(Path(__file__).parent.parent.resolve())",
        f"P1-3: Replace hardcoded path in {f.name}"
    )

for f in [root / "overnight" / "self_improver.py", root / "overnight" / "refeed_bundle.py"]:
    gated_replace(
        f,
        "subprocess.run(['git', 'push'",
        "# HARDENED: Autonomous push disabled. Awaiting human merge.\n# subprocess.run(['git', 'push'",
        f"P0-4: Comment out autonomous git push in {f.name}"
    )
    gated_replace(
        f,
        'subprocess.run(["git", "push"',
        '# HARDENED: Autonomous push disabled. Awaiting human merge.\n# subprocess.run(["git", "push"',
        f"P0-4: Comment out autonomous git push in {f.name} (double quotes)"
    )

# 2. P1-4: Fix swallowed exceptions in PROJECT files only (ignoring .venv)
project_files_with_swallowed_exceptions = [
    root / "engine" / "reasoning_ledger.py",
    root / "engine" / "consensus_gate.py",
    root / "engine" / "defeat_ledger.py",
    root / "engine" / "telemetry.py",
    root / "engine" / "hash_chain_sealer.py",
    root / "contracts" / "worker_vote_adapter.py",
    root / "overnight" / "self_improver.py",
    root / "overnight" / "llm_client.py",
    root / "overnight" / "pi_generator.py",
    root / "overnight" / "openrouter_quota.py",
    root / "overnight" / "pi_idle_reviewer.py",
    root / "orchestrator" / "context_stitcher.py",
    root / "tools" / "telemetry_report.py",
    root / "tools" / "sync_telemetry.py",
    root / "tools" / "process_oracle.py",
    root / "tools" / "verify_truth_sync.py",
    root / "tools" / "build_efficacy_matrix.py",
    root / "tools" / "audit.py"
]

for f in project_files_with_swallowed_exceptions:
    fix_swallowed_exceptions(f)

print("="*60)
print("PATCHING COMPLETE.")
print("="*60)
print("\nNOTE: P0-1 (model_registry.py) and P0-2 (slm_triage_worker.py)")
print("require structural review as they need context-aware refactoring.")
print("\nRun these commands to verify:")
print("  pytest -q")
print("  git diff --check")
print("  git status --short")
