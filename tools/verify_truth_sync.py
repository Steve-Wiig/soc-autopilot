#!/usr/bin/env python3
"""
tools/verify_truth_sync.py — Consolidated truth checks

Checks:
1. Documentation reflects current architecture (no deprecated phases)
2. Manifest exists and references a valid recent commit
3. Source code contains no deprecated terms

Note: This file intentionally contains the forbidden terms as string
literals for pattern matching. It excludes itself from scanning.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Deprecated terms that should NOT appear in project files
# (This file is excluded from scanning since it must reference them)
FORBIDDEN_TERMS = [
    "phase a", "phase b", "phase c",
    "gemini prefill",
    "v11.9", "v11.8", "v11.7",
]

# Directories and files to skip
SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".bak", "archive"}
SKIP_FILES = {"verify_truth_sync.py"}  # This file must reference the terms

def should_skip(path: Path) -> bool:
    """Check if a path should be skipped."""
    if path.name in SKIP_FILES:
        return True
    return any(skip in path.parts for skip in SKIP_DIRS)

def check_docs_current() -> bool:
    """Verify docs describe v11.11 Unified Queue, not deprecated phases."""
    docs_dir = ROOT / "docs"
    if not docs_dir.exists():
        print("⚠️ docs/ directory not found")
        return True

    issues = []
    for md_file in docs_dir.glob("*.md"):
        if should_skip(md_file):
            continue
        try:
            content = md_file.read_text().lower()
            for term in FORBIDDEN_TERMS:
                if term in content:
                    issues.append(f"  {md_file.name}: '{term}'")
        except Exception:
            pass

    if issues:
        print(f"❌ Documentation contains deprecated terms:")
        for issue in issues:
            print(issue)
        return False

    print("✅ Documentation reflects current architecture")
    return True

def check_manifest_exists() -> bool:
    """Verify _manifest.md exists and references a recent commit."""
    manifest_path = ROOT / "_manifest.md"
    if not manifest_path.exists():
        print("❌ _manifest.md not found")
        return False

    try:
        manifest = manifest_path.read_text()

        # Get the last 5 commit SHAs (short form)
        recent_shas = subprocess.check_output(
            ["git", "log", "--format=%h", "-5"],
            cwd=ROOT,
            text=True
        ).strip().split('\n')

        # Check if manifest references any of the recent commits
        for sha in recent_shas:
            if sha in manifest:
                print(f"✅ Manifest references recent commit ({sha})")
                return True

        print(f"❌ Manifest doesn't reference any of the last 5 commits")
        print(f"   Recent commits: {', '.join(recent_shas)}")
        return False

    except Exception as e:
        print(f"❌ Manifest check failed: {e}")
        return False

def check_source_no_deprecated() -> bool:
    """Verify source code contains no deprecated architecture terms."""
    source_dirs = ["engine", "overnight", "orchestrator", "memory", "tools"]
    issues = []

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
                        issues.append(f"  {py_file.relative_to(ROOT)}: '{term}'")
            except Exception:
                pass

    if issues:
        print(f"❌ Source code contains deprecated terms:")
        for issue in issues[:10]:  # Show first 10
            print(issue)
        if len(issues) > 10:
            print(f"  ... and {len(issues) - 10} more")
        return False

    print("✅ Source code contains no deprecated terms")
    return True

def main() -> int:
    """Run all truth-sync checks."""
    print("🔍 Running truth synchronization checks...\n")

    docs_ok = check_docs_current()
    manifest_ok = check_manifest_exists()
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
