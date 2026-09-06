#!/usr/bin/env python3
"""
tools/verify_truth_sync.py — Consolidated truth checks

Checks:
1. Documentation reflects current architecture (no Advisory Generation/B)
2. Manifest SHA matches actual HEAD
3. Source code contains no deprecated terms
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def check_docs_current() -> bool:
    """Verify docs describe v11.11 Unified Queue, not Advisory Generation/B."""
    docs_dir = ROOT / "docs"
    forbidden = ["Advisory Generation", "Shadow Canary", "Backlog Drain", "Unified Queue pre-analysis", "v11.11"]

    for md_file in docs_dir.glob("*.md"):
        if "archive" in md_file.parts:
            continue  # Skip archived docs
        content = md_file.read_text().lower()
        for term in forbidden:
            if term in content:
                print(f"❌ {md_file.name} contains deprecated term: {term}")
                return False

    print("✅ Documentation reflects current architecture")
    return True

def check_manifest_matches_head() -> bool:
    """Verify _manifest.md SHA matches git rev-parse HEAD."""
    try:
        actual_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True
        ).strip()[:7]

        manifest = (ROOT / "_manifest.md").read_text()
        if actual_head not in manifest:
            print(f"❌ Manifest SHA doesn't match HEAD ({actual_head})")
            return False

        print(f"✅ Manifest SHA matches HEAD ({actual_head})")
        return True

    except Exception as e:
        print(f"❌ Manifest check failed: {e}")
        return False

def check_source_no_deprecated() -> bool:
    """Verify source code contains no deprecated architecture terms."""
    forbidden = ["Advisory Generation", "Shadow Canary", "Backlog Drain", "Unified Queue pre-analysis", "v11.11"]
    source_dirs = ["engine", "overnight", "orchestrator", "memory", "tools"]

    for dir_name in source_dirs:
        dir_path = ROOT / dir_name
        if not dir_path.exists():
            continue

        for py_file in dir_path.rglob("*.py"):
            content = py_file.read_text().lower()
            for term in forbidden:
                if term in content:
                    print(f"❌ {py_file.relative_to(ROOT)} contains: {term}")
                    return False

    print("✅ Source code contains no deprecated terms")
    return True

def main() -> int:
    """Run all truth-sync checks."""
    print("🔍 Running truth synchronization checks...\n")

    docs_ok = check_docs_current()
    manifest_ok = check_manifest_matches_head()
    source_ok = check_source_no_deprecated()

    print("\n" + "="*60)
    if docs_ok and manifest_ok and source_ok:
        print("✅ ALL TRUTH-SYNC CHECKS PASSED")
        return 0
    else:
        print("❌ TRUTH-SYNC CHECKS FAILED")
        print("\nRequired actions:")
        if not docs_ok:
            print("  • Update docs/ to describe v11.11 Unified Queue")
            print("  • Remove all Advisory Generation/B/C references from current docs")
        if not manifest_ok:
            print("  • Regenerate _manifest.md with current HEAD SHA")
        if not source_ok:
            print("  • Remove deprecated terms from source code")
            print("  • See docs/OVERNIGHT_PIPELINE.md for current architecture")
        return 1

if __name__ == "__main__":
    sys.exit(main())
