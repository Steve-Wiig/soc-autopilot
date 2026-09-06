#!/usr/bin/env python3
"""
tools/verify_truth_sync.py — Consolidated truth checks

Checks:
1. Documentation reflects current architecture (no Phase A/B)
2. Manifest SHA matches actual HEAD
3. Source code contains no deprecated terms
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# These are the terms we're checking FOR (deprecated terms that should NOT exist)
FORBIDDEN_TERMS = ["phase a", "phase b", "phase c", "gemini prefill", "v11.9", "v11.8", "v11.7"]

# Directories to skip entirely
SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".bak", "archive"}

def should_skip(path: Path) -> bool:
    """Check if a path should be skipped."""
    return any(skip in path.parts for skip in SKIP_DIRS)

def check_docs_current() -> bool:
    """Verify docs describe v11.11 Unified Queue, not deprecated phases."""
    docs_dir = ROOT / "docs"
    if not docs_dir.exists():
        print("⚠️ docs/ directory not found")
        return True

    for md_file in docs_dir.glob("*.md"):
        if should_skip(md_file):
            continue
        try:
            content = md_file.read_text().lower()
            for term in FORBIDDEN_TERMS:
                if term in content:
                    print(f"❌ {md_file.name} contains deprecated term: {term}")
                    return False
        except Exception:
            pass

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

        manifest_path = ROOT / "_manifest.md"
        if not manifest_path.exists():
            print("❌ _manifest.md not found")
            return False

        manifest = manifest_path.read_text()
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
    source_dirs = ["engine", "overnight", "orchestrator", "memory", "tools"]
    found_issues = False

    for dir_name in source_dirs:
        dir_path = ROOT / dir_name
        if not dir_path.exists():
            continue

        for py_file in dir_path.rglob("*.py"):
            if should_skip(py_file):
                continue
            try:
                content = py_file.read_text().lower()
                for term in FORBIDDEN_TERMS:
                    if term in content:
                        print(f"❌ {py_file.relative_to(ROOT)} contains: {term}")
                        found_issues = True
            except Exception:
                pass

    if not found_issues:
        print("✅ Source code contains no deprecated terms")
        return True
    return False

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
        return 1

if __name__ == "__main__":
    sys.exit(main())
