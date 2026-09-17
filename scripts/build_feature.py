#!/usr/bin/env python3
"""
Feature Builder: Uses the proven self_improver.py patterns for reliable free tier usage.
"""
import sys
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.development_worker_dispatch import dispatch_development_worker, DevelopmentWorkerRequest, AIDER_BACKEND

def materialize_aider_diff(diff_text: str, file_path: Path, original: str) -> str:
    """Convert Aider's unified diff to SEARCH/REPLACE format (from self_improver.py)"""
    rel_target = str(file_path.relative_to(ROOT))
    if not diff_text.strip():
        raise ValueError("Aider returned an empty diff.")

    with tempfile.TemporaryDirectory(prefix="soc-autopilot-aider-") as tmp:
        tmp_root = Path(tmp)
        temp_target = tmp_root / rel_target
        temp_target.parent.mkdir(parents=True, exist_ok=True)
        temp_target.write_text(original)

        subprocess.run(["git", "init", "-q"], cwd=tmp_root, check=True, capture_output=True)
        subprocess.run(["git", "add", "--", rel_target], cwd=tmp_root, check=True, capture_output=True)

        check = subprocess.run(
            ["git", "apply", "--check", "--whitespace=nowarn", "-"],
            cwd=tmp_root, input=diff_text, text=True, capture_output=True, check=False,
        )
        if check.returncode != 0:
            raise ValueError(f"Aider diff failed validation: {check.stderr or check.stdout}")

        applied = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=tmp_root, input=diff_text, text=True, capture_output=True, check=False,
        )
        if applied.returncode != 0:
            raise ValueError(f"Aider diff could not be materialized: {applied.stderr or applied.stdout}")

        new_content = temp_target.read_text()

    if new_content == original:
        raise ValueError("Aider diff materialized to no content change.")

    search = original
    replace = new_content
    if not search.endswith("\n"): search += "\n"
    if not replace.endswith("\n"): replace += "\n"

    return f"<<<<<<< {rel_target}\n{search}=======\n{replace}\n>>>>>>> REPLACE\n"

def build_file_with_retry(file_path_str: str, issue_desc: str, max_attempts: int = 3) -> bool:
    """Build a file with retry logic and failed attempt injection (from self_improver.py)"""
    fpath = ROOT / file_path_str
    fpath.parent.mkdir(parents=True, exist_ok=True)
    
    original = fpath.read_text() if fpath.exists() else ""
    rel_target = str(fpath.relative_to(ROOT))
    
    failed_attempt_raw = ""
    
    for attempt in range(max_attempts):
        print(f"\n{'='*60}")
        print(f"BUILDING: {file_path_str} (attempt {attempt + 1}/{max_attempts})")
        print(f"{'='*60}")
        
        # Build prompt with failed attempt injection (from self_improver.py)
        prompt = f"""You are the bounded implementation worker for SOC-AUTOPILOT.

YOU MUST CREATE/EDIT THE FILE.
Do not merely explain the change. Do not return a prose-only answer.

You may modify ONLY:
{rel_target}

Implement the issue below.

ISSUE:
{issue_desc}

IMPLEMENTATION RULES:
1. Modify ONLY the authorized file.
2. If the file is new, the SEARCH block must be EMPTY, and the REPLACE block must contain the COMPLETE, fully implemented code.
3. NEVER output placeholder text like '[exact search text]' or '[replace text]'.
4. Include all necessary imports.
5. The caller will independently validate the resulting diff, scope, safety, and regression behavior.
"""
        
        # Inject failed attempt (from self_improver.py)
        if failed_attempt_raw:
            prompt += f"\n\nPREVIOUS FAILED ATTEMPT — DO NOT REPEAT:\n{failed_attempt_raw[:5000]}"
        
        try:
            request = DevelopmentWorkerRequest(
                prompt=prompt,
                files=(rel_target,),
                backend=AIDER_BACKEND,
                timeout=600,
            )
            
            result = dispatch_development_worker(request)
            
            if not result.accepted_for_review or not result.worker_result:
                print(f"❌ Worker rejected: {result.reason}")
                failed_attempt_raw = result.reason or ""
                continue
            
            worker_result = result.worker_result
            changed = {str(Path(path)) for path in worker_result.changed_files}
            
            if changed != {rel_target}:
                print(f"❌ Aider modified unauthorized files: {changed}")
                failed_attempt_raw = f"Modified unauthorized files: {changed}"
                continue
            
            # Convert Aider's diff to SEARCH/REPLACE format (from self_improver.py)
            search_replace_block = materialize_aider_diff(worker_result.diff, fpath, original)
            
            # Apply using the proven patch engine (from self_improver.py)
            from overnight.multi_file_patcher import parse_multi_file_diff, apply_multi_file_patches
            patches = parse_multi_file_diff(search_replace_block, ROOT)
            apply_multi_file_patches(patches, repo_root=ROOT, authorized_files={fpath.relative_to(ROOT)})
            
            print(f"✅ SUCCESS: {file_path_str} generated and applied.")
            return True
            
        except Exception as e:
            print(f"❌ Attempt {attempt + 1} failed: {e}")
            failed_attempt_raw = str(e)
            continue
    
    print(f"💥 All {max_attempts} attempts failed")
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
        if not build_file_with_retry(fpath, desc):
            all_success = False
            # Commit before moving to next file
            subprocess.run(["git", "add", fpath], cwd=ROOT)
            subprocess.run(["git", "commit", "-m", f"feat: add {fpath}"], cwd=ROOT)
            break
        else:
            # Commit successful file
            subprocess.run(["git", "add", fpath], cwd=ROOT)
            subprocess.run(["git", "commit", "-m", f"feat: add {fpath}"], cwd=ROOT)
            
    if all_success:
        print("\n🎉 All features built successfully!")
        sys.exit(0)
    else:
        print("\n💥 Feature build failed.")
        sys.exit(1)
