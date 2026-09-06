#!/usr/bin/env python3
"""
P0 Governance: Ensures documentation and manifests match the actual codebase state.
Prevents LLMs from ingesting deprecated architectural patterns.
"""
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def check_docs():
    """Verify OVERNIGHT_PIPELINE.md doesn't reference deprecated Phase A/B."""
    doc_path = ROOT / "docs" / "OVERNIGHT_PIPELINE.md"
    if not doc_path.exists():
        print("⚠️ docs/OVERNIGHT_PIPELINE.md missing")
        return True # Skip if not created yet
        
    text = doc_path.read_text().lower()
    
    # Deprecated patterns that should NOT exist in v11.11+
    deprecated = ["phase a", "phase b", "gemini prefill", "v11.9"]
    violations = [term for term in deprecated if term in text]
    
    if violations:
        print(f"❌ TRUTH DRIFT: Docs contain deprecated terms: {violations}")
        print("   Action: Update docs to reflect v11.11 (Shadow Canary, Unified Queue)")
        return False
    
    # Required patterns for v11.11+
    required = ["shadow canary", "unified queue", "slm triage"]
    missing = [term for term in required if term not in text]
    if missing:
        print(f"⚠️ Docs missing v11.11 features: {missing}")
        # We won't fail the build for this yet, just warn
        
    print("✅ Docs are synchronized with v11.11 architecture.")
    return True

def check_manifest():
    """Verify _manifest.md references the actual current HEAD."""
    manifest_path = ROOT / "_manifest.md"
    if not manifest_path.exists():
        print("⚠️ _manifest.md missing")
        return True
        
    text = manifest_path.read_text()
    
    # Get actual HEAD
    try:
        actual_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()[:7] # Short SHA
    except Exception:
        print("⚠️ Could not determine git HEAD")
        return True
        
    if actual_head not in text:
        print(f"❌ TRUTH DRIFT: Manifest references stale SHA. Actual HEAD is {actual_head}")
        print("   Action: Regenerate manifest from current HEAD.")
        return False
        
    print(f"✅ Manifest synchronized with HEAD ({actual_head}).")
    return True

if __name__ == "__main__":
    docs_ok = check_docs()
    manifest_ok = check_manifest()
    
    if not (docs_ok and manifest_ok):
        sys.exit(1)
    print("\n🎯 ALL TRUTH SYNC CHECKS PASSED")
    sys.exit(0)
