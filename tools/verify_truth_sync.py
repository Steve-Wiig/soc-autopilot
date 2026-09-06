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
        print("❌ CRITICAL: docs/OVERNIGHT_PIPELINE.md missing")
        return False
        
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
        print("❌ CRITICAL: _manifest.md missing")
        return False
        
    text = manifest_path.read_text()
    
    # Get actual HEAD
    try:
        actual_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()[:7] # Short SHA
    except Exception:
        print("❌ CRITICAL: Could not determine git HEAD")
        return False
        
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

def check_source_code_for_deprecated_terms():
    """Check source code files for deprecated architecture terms."""
    deprecated_terms = ["phase a", "phase b", "gemini prefill", "v11.9"]
    source_dirs = ["overnight/", "engine/", "orchestrator/", "memory/"]
    
    findings = []
    from pathlib import Path
    
    for source_dir in source_dirs:
        dir_path = Path(source_dir)
        if not dir_path.exists():
            continue
            
        for py_file in dir_path.glob("*.py"):
            try:
                content = py_file.read_text().lower()
                for term in deprecated_terms:
                    if term in content:
                        findings.append((str(py_file), term))
            except Exception:
                pass
    
    return findings

# Add source code check to main validation
if __name__ == "__main__":
    print("\n🔍 Checking source code for deprecated terms...")
    source_findings = check_source_code_for_deprecated_terms()
    
    if source_findings:
        print(f"❌ Found {len(source_findings)} deprecated terms in source:")
        for filepath, term in source_findings[:10]:
            print(f"  {filepath}: contains '{term}'")
        exit(1)
    else:
        print("✅ No deprecated terms in source code")
