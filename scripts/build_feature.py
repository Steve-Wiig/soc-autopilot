#!/usr/bin/env python3
"""
Feature Builder: Uses propose_code.py (the proven path) with timestamp tracking.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def build_file(file_path_str: str, issue_desc: str) -> bool:
    print(f"\n{'='*60}")
    print(f"BUILDING: {file_path_str}")
    print(f"{'='*60}")
    
    run_start = time.time()
    
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "propose_code.py"),
        "--auto",
        issue_desc,
        "--files",
        file_path_str,
    ]
    
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=700)
        
        proposals_dir = ROOT / "proposals"
        new_patches = [p for p in proposals_dir.glob("prop-*.patch") if p.stat().st_mtime > run_start]
        new_patches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        if not new_patches:
            print(f"❌ No patch generated")
            print(f"STDOUT tail: {result.stdout[-400:]}")
            return False
        
        latest_patch = new_patches[0]
        print(f"✅ Patch: {latest_patch.name}")
        
        apply_result = subprocess.run(
            ["git", "apply", "--ignore-whitespace", str(latest_patch)],
            cwd=ROOT, capture_output=True, text=True,
        )
        
        if apply_result.returncode != 0:
            print(f"❌ Apply failed: {apply_result.stderr}")
            return False
        
        # Commit to keep worktree clean for next task
        subprocess.run(["git", "add", file_path_str], cwd=ROOT, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"feat: add {file_path_str}"], cwd=ROOT, capture_output=True)
        
        print(f"✅ SUCCESS: {file_path_str}")
        return True
        
    except subprocess.TimeoutExpired:
        print(f"❌ Timeout after 700 seconds")
        return False
    except Exception as e:
        print(f"❌ {e}")
        return False

if __name__ == "__main__":
    features = [
        (
            "contracts/alert_models.py",
            "Create Pydantic models for Alert and EnrichedAlert. Alert must have: alert_id (str), timestamp (datetime), severity (str), description (str). EnrichedAlert inherits from Alert and adds: llm_analysis (str), mitre_techniques (List[str]), false_positive_likelihood (float). Use strict typing."
        ),
        (
            "engine/alert_enrichment.py",
            "Create AlertEnrichmentService. It must have an enrich_alert method that takes an Alert or dict. It must simulate an LLM call in a separate thread with a 30-second timeout. If successful, return an EnrichedAlert. If timeout or exception, return the original Alert. Do not make real API calls yet, just simulate."
        ),
        (
            "tests/test_alert_enrichment.py",
            "Write pytest tests for AlertEnrichmentService. Test successful enrichment, timeout (using a very short timeout and mocking), failure (mocking an exception), and dict input. CRITICAL: Use valid UUID v4 for alert_id and valid severity enums ('low', 'medium', 'high', 'critical')."
        )
    ]
    
    for fpath, desc in features:
        if not build_file(fpath, desc):
            print(f"\n💥 Failed at {fpath}")
            sys.exit(1)
    
    print("\n🎉 All features built successfully!")
    sys.exit(0)
