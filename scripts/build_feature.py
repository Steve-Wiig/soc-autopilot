#!/usr/bin/env python3
"""
Feature Builder: Uses scripts/propose_code.py with timestamp-based patch tracking.
Prevents reuse of old patches by only accepting patches newer than the run start.
"""
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent

def build_file(file_path_str: str, issue_desc: str) -> bool:
    """Build a single file using the proven propose_code.py pipeline."""
    print(f"\n{'='*60}")
    print(f"BUILDING: {file_path_str}")
    print(f"{'='*60}")

    # Record the timestamp BEFORE running - only accept patches newer than this
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
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=700,
        )

        # Find patches NEWER than this run started
        proposals_dir = ROOT / "proposals"
        new_patches = [
            p for p in proposals_dir.glob("prop-*.patch")
            if p.stat().st_mtime > run_start
        ]
        new_patches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if not new_patches:
            print(f"❌ FAILED: No NEW patch generated for {file_path_str}")
            print(f"   (propose_code.py likely failed - check model availability)")
            print(f"STDOUT tail: {result.stdout[-300:]}")
            return False

        latest_patch = new_patches[0]
        print(f"✅ New patch generated: {latest_patch.name} (age: {time.time() - latest_patch.stat().st_mtime:.1f}s)")

        # Apply the patch
        apply_result = subprocess.run(
            ["git", "apply", "--ignore-whitespace", str(latest_patch)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        if apply_result.returncode != 0:
            print(f"❌ FAILED to apply patch: {apply_result.stderr}")
            return False

        print(f"✅ SUCCESS: {file_path_str} generated and applied.")
        return True

    except subprocess.TimeoutExpired:
        print(f"❌ FAILED: Timeout after 700 seconds")
        return False
    except Exception as e:
        print(f"❌ FAILED: {e}")
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

    all_success = True
    for fpath, desc in features:
        if not build_file(fpath, desc):
            all_success = False
            break

    if all_success:
        print("\n🎉 All features built successfully!")
        sys.exit(0)
    else:
        print("\n💥 Feature build failed.")
        sys.exit(1)
