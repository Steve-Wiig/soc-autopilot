#!/usr/bin/env python3
"""
Overnight verification and development pipeline.
Runs in background, produces a morning report.

Usage:
  nohup python3 overnight/overnight_verify_and_develop.py > overnight_run.log 2>&1 &

Phases:
  1. Full verification sweep (imports, dry-runs, SQL, pytest)
  2. Gap analysis (missing features, style issues)
  3. Task generation for next development pass
  4. Optional: run the LLM loop to fill gaps
  5. Morning report generation
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env file if it exists
def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


PROJECT_ROOT = ROOT
OVERNIGHT_DIR = PROJECT_ROOT / "overnight"
REPORT_PATH = OVERNIGHT_DIR / "morning_report.md"
TASKS_PATH = OVERNIGHT_DIR / "tasks_phase5.json"
EVIDENCE_DIR = OVERNIGHT_DIR / "evidence"

# Configuration
RUN_LLM_LOOP = False  # Set to True to auto-generate fixes overnight
API_BUDGET = 200      # Conservative budget for overnight run
MAX_SWEEPS = 1        # Single sweep overnight


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}", flush=True)


def run_command(cmd, cwd=None, timeout=120):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or str(PROJECT_ROOT),
            shell=isinstance(cmd, str)
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -2, "", str(e)


def phase1_verification():
    """Run all verification checks and collect results."""
    log("=" * 60)
    log("PHASE 1: FULL VERIFICATION SWEEP")
    log("=" * 60)
    results = {}

    # 1a. Module imports
    log("  [1a] Checking module imports...")
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    import importlib

    py_files = [
        f for f in PROJECT_ROOT.rglob("*.py")
        if ".venv" not in str(f)
        and "__pycache__" not in str(f)
        and "overnight" not in str(f)
        and f.name not in ("overnight_verify_and_develop.py", "bulk_audit.py", "integration_verifier.py")
    ]

    import_failures = []
    for f in py_files:
        module_name = str(f.relative_to(PROJECT_ROOT)).replace("/", ".").replace(".py", "")
        try:
            importlib.import_module(module_name)
        except Exception as e:
            import_failures.append({"file": str(f.relative_to(PROJECT_ROOT)), "error": str(e)[:100]})

    results["module_imports"] = {
        "total": len(py_files),
        "passed": len(py_files) - len(import_failures),
        "failed": len(import_failures),
        "failures": import_failures
    }
    log(f"    {len(py_files) - len(import_failures)}/{len(py_files)} modules import OK")

    # 1b. Pytest suite
    log("  [1b] Running pytest suite...")
    rc, stdout, stderr = run_command(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=line"],
        timeout=120
    )
    passed = stdout.count(" PASSED")
    failed = stdout.count(" FAILED")
    errors = stdout.count(" ERROR")
    results["pytest"] = {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors
    }
    log(f"    {passed} passed, {failed} failed, {errors} errors")

    # 1c. CI tool dry-runs
    log("  [1c] Running CI tool dry-runs...")
    tools_dir = PROJECT_ROOT / "tools"
    tool_results = []
    for tool in sorted(tools_dir.glob("*.py")):
        rc, stdout, stderr = run_command(
            [sys.executable, str(tool), "--dry-run"],
            timeout=15
        )
        status = "PASS" if rc == 0 else ("EXPECTED" if rc in (2, 3) else "FAIL")
        tool_results.append({"tool": tool.name, "exit_code": rc, "status": status})

    results["ci_tools"] = {
        "total": len(tool_results),
        "passed": sum(1 for t in tool_results if t["status"] == "PASS"),
        "expected": sum(1 for t in tool_results if t["status"] == "EXPECTED"),
        "failed": sum(1 for t in tool_results if t["status"] == "FAIL"),
        "details": tool_results
    }
    log(f"    {results['ci_tools']['passed']} pass, {results['ci_tools']['expected']} expected, {results['ci_tools']['failed']} fail")

    # 1d. YAML validation
    log("  [1d] Validating YAML files...")
    try:
        import yaml
        yaml_files = list(PROJECT_ROOT.rglob("*.yaml"))
        yaml_results = []
        for yf in yaml_files:
            if ".venv" in str(yf):
                continue
            try:
                with open(yf) as f:
                    yaml.safe_load(f)
                yaml_results.append({"file": str(yf.relative_to(PROJECT_ROOT)), "status": "PASS"})
            except Exception as e:
                yaml_results.append({"file": str(yf.relative_to(PROJECT_ROOT)), "status": "FAIL", "error": str(e)[:80]})
        results["yaml"] = yaml_results
        log(f"    {sum(1 for y in yaml_results if y['status'] == 'PASS')}/{len(yaml_results)} YAML files valid")
    except ImportError:
        results["yaml"] = [{"status": "SKIP", "error": "pyyaml not installed"}]
        log("    SKIP: pyyaml not installed")

    # 1e. SQL syntax check
    log("  [1e] Checking SQL files...")
    import sqlite3
    sql_files = list(PROJECT_ROOT.rglob("*.sql"))
    sql_results = []
    for sf in sql_files:
        if ".venv" in str(sf):
            continue
        try:
            content = sf.read_text()
            # Basic structural check
            has_create = "CREATE" in content.upper()
            has_semicolons = ";" in content
            sql_results.append({
                "file": str(sf.relative_to(PROJECT_ROOT)),
                "status": "PASS" if has_create and has_semicolons else "WARN",
                "lines": len(content.splitlines())
            })
        except Exception as e:
            sql_results.append({"file": str(sf.relative_to(PROJECT_ROOT)), "status": "FAIL", "error": str(e)[:80]})
    results["sql"] = sql_results
    log(f"    {len(sql_results)} SQL files checked")

    return results


def phase2_gap_analysis(verification_results):
    """Analyze verification results to identify development gaps."""
    log("")
    log("=" * 60)
    log("PHASE 2: GAP ANALYSIS")
    log("=" * 60)

    gaps = []

    # Check for tools missing --dry-run
    tools_dir = PROJECT_ROOT / "tools"
    for tool in sorted(tools_dir.glob("*.py")):
        content = tool.read_text()
        if "dry-run" not in content and "dry_run" not in content:
            gaps.append({
                "type": "add_dry_run",
                "target": f"tools/{tool.name}",
                "description": f"Add --dry-run support to {tool.name}"
            })

    # Check for tools missing explicit exit codes
    for tool in sorted(tools_dir.glob("*.py")):
        content = tool.read_text()
        if "sys.exit" not in content and "exit(" not in content:
            if "def main" not in content and 'if __name__' not in content:
                gaps.append({
                    "type": "add_exit_codes",
                    "target": f"tools/{tool.name}",
                    "description": f"Add explicit exit codes to {tool.name}"
                })

    # Check for missing __init__.py files
    for pkg_dir in ["engine", "memory", "orchestrator", "tools", "tests"]:
        init_path = PROJECT_ROOT / pkg_dir / "__init__.py"
        if not init_path.exists():
            gaps.append({
                "type": "add_init",
                "target": f"{pkg_dir}/__init__.py",
                "description": f"Add __init__.py to {pkg_dir}/ package"
            })

    # Check for missing requirements.txt
    req_path = PROJECT_ROOT / "requirements.txt"
    if not req_path.exists():
        gaps.append({
            "type": "add_requirements",
            "target": "requirements.txt",
            "description": "Add requirements.txt with pinned dependencies"
        })

    # Check for missing .env.example
    env_path = PROJECT_ROOT / ".env.example"
    if not env_path.exists():
        gaps.append({
            "type": "add_env_example",
            "target": ".env.example",
            "description": "Add .env.example with required environment variables"
        })

    log(f"  Identified {len(gaps)} development gaps")
    for gap in gaps[:10]:
        log(f"    - [{gap['type']}] {gap['target']}")

    return gaps


def phase3_generate_tasks(gaps):
    """Generate a task list for the next development pass."""
    log("")
    log("=" * 60)
    log("PHASE 3: TASK GENERATION")
    log("=" * 60)

    tasks = []
    task_id = 401  # Continue from T-315

    for gap in gaps:
        task = {
            "id": f"T-{task_id}",
            "type": "implement_tool" if gap["type"] in ("add_dry_run", "add_exit_codes") else "generate_config",
            "target": gap["target"],
            "prompt_hint": gap["description"] + ". Output ONLY valid code. No markdown fences.",
            "priority": task_id - 400,
            "status": "open"
        }
        tasks.append(task)
        task_id += 1

    # Add requirements.txt task
    if any(g["type"] == "add_requirements" for g in gaps):
        tasks.append({
            "id": f"T-{task_id}",
            "type": "generate_config",
            "target": "requirements.txt",
            "prompt_hint": "Generate a requirements.txt file with pinned versions for: psycopg2-binary, numpy, pyyaml, pytest, sentence-transformers, requests. Use >= for minimum versions. Output ONLY the file content.",
            "priority": task_id - 400,
            "status": "open"
        })
        task_id += 1

    # Add .env.example task
    if any(g["type"] == "add_env_example" for g in gaps):
        tasks.append({
            "id": f"T-{task_id}",
            "type": "generate_config",
            "target": ".env.example",
            "prompt_hint": "Generate a .env.example file documenting all required environment variables: GEMINI_API_KEY, LAB_URL, WAZUH_USER, WAZUH_TOKEN, PFSENSE_USER, PFSENSE_TOKEN, VRAM_BUDGET_MB. Include comments explaining each. Output ONLY the file content.",
            "priority": task_id - 400,
            "status": "open"
        })
        task_id += 1

    # Write tasks file
    with open(TASKS_PATH, "w") as f:
        json.dump(tasks, f, indent=2)

    log(f"  Generated {len(tasks)} tasks -> {TASKS_PATH}")
    return tasks


def phase4_run_loop(tasks):
    """Optionally run the LLM loop to fill gaps."""
    if not RUN_LLM_LOOP:
        log("")
        log("=" * 60)
        log("PHASE 4: LLM LOOP (SKIPPED - RUN_LLM_LOOP=False)")
        log("=" * 60)
        log("  Set RUN_LLM_LOOP=True in this script to enable overnight generation.")
        return None

    log("")
    log("=" * 60)
    log("PHASE 4: LLM LOOP (RUNNING)")
    log("=" * 60)

    # Check for API key
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        log("  ERROR: GEMINI_API_KEY not set. Skipping LLM loop.")
        return None

    # Copy tasks to active tasks.json
    import shutil
    shutil.copy(TASKS_PATH, OVERNIGHT_DIR / "tasks.json")

    # Remove progress.json to force fresh run
    progress_path = OVERNIGHT_DIR / "progress.json"
    if progress_path.exists():
        progress_path.unlink()

    # Run the loop
    log(f"  Starting loop_v3.py with budget={API_BUDGET}, sweeps={MAX_SWEEPS}")
    rc, stdout, stderr = run_command(
        [sys.executable, "-u", str(OVERNIGHT_DIR / "loop_v3.py")],
        timeout=3600  # 1 hour max
    )

    log(f"  Loop completed with exit code {rc}")
    return {"exit_code": rc, "stdout_tail": stdout[-500:] if stdout else ""}


def phase5_morning_report(verification_results, gaps, tasks, loop_result):
    """Generate the morning report."""
    log("")
    log("=" * 60)
    log("PHASE 5: MORNING REPORT")
    log("=" * 60)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report_lines = [
        f"# Overnight Verification Report",
        f"**Generated:** {now}",
        f"**Project:** soc-autopilot",
        "",
        "---",
        "",
        "## Verification Summary",
        "",
        "| Check | Result |",
        "|---|---|",
    ]

    # Module imports
    mi = verification_results.get("module_imports", {})
    report_lines.append(f"| Module imports | {mi.get('passed', '?')}/{mi.get('total', '?')} pass |")

    # Pytest
    pt = verification_results.get("pytest", {})
    report_lines.append(f"| Pytest | {pt.get('passed', '?')} pass, {pt.get('failed', '?')} fail |")

    # CI tools
    ct = verification_results.get("ci_tools", {})
    report_lines.append(f"| CI tools dry-run | {ct.get('passed', '?')} pass, {ct.get('expected', '?')} expected, {ct.get('failed', '?')} fail |")

    # YAML
    yaml_results = verification_results.get("yaml", [])
    yaml_pass = sum(1 for y in yaml_results if y.get("status") == "PASS")
    report_lines.append(f"| YAML validation | {yaml_pass}/{len(yaml_results)} valid |")

    # SQL
    sql_results = verification_results.get("sql", [])
    sql_pass = sum(1 for s in sql_results if s.get("status") == "PASS")
    report_lines.append(f"| SQL structure | {sql_pass}/{len(sql_results)} valid |")

    report_lines.extend([
        "",
        "---",
        "",
        "## Gap Analysis",
        "",
        f"**Total gaps identified:** {len(gaps)}",
        "",
    ])

    if gaps:
        report_lines.append("| Type | Target | Description |")
        report_lines.append("|---|---|---|")
        for gap in gaps[:20]:
            report_lines.append(f"| {gap['type']} | `{gap['target']}` | {gap['description']} |")

    report_lines.extend([
        "",
        "---",
        "",
        "## Generated Tasks",
        "",
        f"**Tasks generated:** {len(tasks)}",
        f"**Task file:** `{TASKS_PATH}`",
        "",
    ])

    if tasks:
        report_lines.append("| ID | Type | Target |")
        report_lines.append("|---|---|---|")
        for task in tasks[:20]:
            report_lines.append(f"| {task['id']} | {task['type']} | `{task['target']}` |")

    report_lines.extend([
        "",
        "---",
        "",
        "## LLM Loop Status",
        "",
    ])

    if loop_result is None:
        report_lines.append("LLM loop was **not run** (RUN_LLM_LOOP=False or no API key).")
        report_lines.append("")
        report_lines.append("To run the loop manually:")
        report_lines.append("```bash")
        report_lines.append(f"cd {ROOT}/overnight")
        report_lines.append(f"cp {TASKS_PATH.name} tasks.json")
        report_lines.append("rm -f progress.json")
        report_lines.append('export GEMINI_API_KEY="YOUR_KEY"')
        report_lines.append("python3 -u loop_v3.py 2>&1 | tail -20")
        report_lines.append("```")
    else:
        report_lines.append(f"LLM loop completed with exit code: {loop_result['exit_code']}")
        if loop_result.get("stdout_tail"):
            report_lines.append(f"```\n{loop_result['stdout_tail']}\n```")

    report_lines.extend([
        "",
        "---",
        "",
        "## Failures Detail",
        "",
    ])

    # List any failures
    failures_found = False

    if mi.get("failures"):
        failures_found = True
        report_lines.append("### Module Import Failures")
        for f in mi["failures"]:
            report_lines.append(f"- `{f['file']}`: {f['error']}")
        report_lines.append("")

    if pt.get("failed", 0) > 0 or pt.get("errors", 0) > 0:
        failures_found = True
        report_lines.append(f"### Pytest Failures: {pt.get('failed', 0)} failed, {pt.get('errors', 0)} errors")
        report_lines.append("Run `python3 -m pytest tests/ -v` for details.")
        report_lines.append("")

    if ct.get("failed", 0) > 0:
        failures_found = True
        report_lines.append("### CI Tool Failures")
        for t in ct.get("details", []):
            if t["status"] == "FAIL":
                report_lines.append(f"- `{t['tool']}`: exit {t['exit_code']}")
        report_lines.append("")

    if not failures_found:
        report_lines.append("No failures detected. All checks passed or returned expected status.")

    report_lines.extend([
        "",
        "---",
        "",
        "## Next Steps",
        "",
        "1. Review this report",
        "2. Run `python3 -m pytest tests/ -v` to confirm test status",
        "3. If gaps were identified, review `tasks_phase5.json`",
        "4. To fill gaps with LLM: set `RUN_LLM_LOOP=True` and re-run, or run loop manually",
        "5. Commit verified state: `git add -A && git commit -m 'Overnight verification pass'`",
        "",
        "---",
        "",
        "*Report generated by overnight_verify_and_develop.py*",
    ])

    report_content = "\n".join(report_lines)
    REPORT_PATH.write_text(report_content)
    log(f"  Report written to {REPORT_PATH}")

    # Also save raw results as JSON
    evidence_path = EVIDENCE_DIR / f"overnight_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    with open(evidence_path, "w") as f:
        json.dump({
            "timestamp": now,
            "verification": verification_results,
            "gaps": gaps,
            "tasks_generated": len(tasks),
            "loop_result": loop_result
        }, f, indent=2, default=str)
    log(f"  Evidence saved to {evidence_path}")


def main():
    load_env()
    log("=" * 60)
    log("OVERNIGHT VERIFICATION & DEVELOPMENT PIPELINE")
    log("=" * 60)
    log(f"Blueprint root: {PROJECT_ROOT}")
    log(f"Run LLM loop: {RUN_LLM_LOOP}")
    log("")

    start_time = time.time()

    # Phase 1: Verification
    verification_results = phase1_verification()

    # Phase 2: Gap analysis
    gaps = phase2_gap_analysis(verification_results)

    # Phase 3: Task generation
    tasks = phase3_generate_tasks(gaps)

    # Phase 4: Optional LLM loop
    loop_result = phase4_run_loop(tasks)

    # Phase 5: Morning report
    phase5_morning_report(verification_results, gaps, tasks, loop_result)

    elapsed = time.time() - start_time
    log("")
    log(f"Total runtime: {elapsed:.1f} seconds")
    log("Done. Check morning_report.md for results.")


if __name__ == "__main__":
    main()
