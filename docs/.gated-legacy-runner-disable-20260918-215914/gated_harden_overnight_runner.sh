#!/usr/bin/env bash

# Standalone gated hardening for the bounded overnight development runner.
# Intentionally does NOT use `set -e`: every failure is handled explicitly.
# Run this script from the repository root on a test/* branch.

set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$ROOT" ]; then
    echo "ERROR: not inside a Git repository"
    exit 1
fi

cd "$ROOT"

RUNNER="scripts/overnight_runner.py"
IGNORE_FILE=".gitignore"
RUN_ID="$(date +%Y%m%d-%H%M%S)"

RUNNER_BACKUP="${RUNNER}.bak-gated-runner-${RUN_ID}"
IGNORE_BACKUP="${IGNORE_FILE}.bak-gated-runner-${RUN_ID}"

cleanup_failed() {
    echo
    echo "===== FAILURE: RESTORING HARDENING TARGETS ====="

    if [ -f "$RUNNER_BACKUP" ]; then
        cp -a "$RUNNER_BACKUP" "$RUNNER"
    fi

    if [ -f "$IGNORE_BACKUP" ]; then
        cp -a "$IGNORE_BACKUP" "$IGNORE_FILE"
    fi

    echo "Targets restored from gated backups."
    echo
    echo "Current status:"
    git status --short --branch
    exit 1
}

echo "============================================================"
echo "SOC-AUTOPILOT — GATED OVERNIGHT RUNNER HARDENING"
echo "============================================================"

echo
echo "===== PRECONDITIONS ====="

BRANCH="$(git branch --show-current)"
echo "Branch: $BRANCH"

case "$BRANCH" in
    test/*)
        echo "PASS: test branch"
        ;;
    *)
        echo "ERROR: unattended development hardening requires test/*"
        exit 1
        ;;
esac

if ! git diff --quiet; then
    echo "ERROR: repository already has tracked modifications."
    git status --short
    exit 1
fi

if ! git diff --cached --quiet; then
    echo "ERROR: repository already has staged modifications."
    git status --short
    exit 1
fi

echo "PASS: no tracked/staged modifications"

echo
echo "===== BACKUPS ====="

if ! cp -a "$RUNNER" "$RUNNER_BACKUP"; then
    echo "ERROR: runner backup failed"
    exit 1
fi

if ! cp -a "$IGNORE_FILE" "$IGNORE_BACKUP"; then
    echo "ERROR: .gitignore backup failed"
    cp -a "$RUNNER_BACKUP" "$RUNNER" || true
    exit 1
fi

echo "Runner backup: $RUNNER_BACKUP"
echo "Gitignore backup: $IGNORE_BACKUP"

echo
echo "===== PATCHING RUNNER ====="

python3 - "$RUNNER" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()

if "LOW_RISK_AUTO_TASK_SCOPES" in text:
    print("ERROR: runner already appears hardened.")
    sys.exit(2)

start = text.find("\ndef run_task(")
main = text.find('\nif __name__ == "__main__":')

if start < 0:
    print("ERROR: run_task definition not found.")
    sys.exit(3)

if main < 0:
    print("ERROR: __main__ block not found.")
    sys.exit(4)

prefix = text[:start]

replacement = r'''
# Explicit deny-by-default policy for unattended development.
#
# Only these exact task/file combinations may run hands-free.
# The Wazuh Active Response task is intentionally absent because it is
# medium-risk and requires a separate human-gated path.
LOW_RISK_AUTO_TASK_SCOPES = {
    "engine/alert_correlator.py": frozenset({
        "engine/alert_correlator.py",
        "contracts/incident_models.py",
        "tests/test_alert_correlator.py",
    }),
    "engine/sigma_generator.py": frozenset({
        "engine/sigma_generator.py",
        "tests/test_sigma_generator.py",
    }),
}

AUTO_BRANCH_PREFIX = "test/"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _repo_is_clean() -> tuple[bool, str]:
    result = _git("status", "--porcelain", "--untracked-files=all")

    if result.returncode != 0:
        return False, "Unable to inspect repository state."

    if result.stdout.strip():
        return (
            False,
            "Repository is not clean. Refusing unattended task execution.",
        )

    return True, ""


def _require_test_branch() -> tuple[bool, str]:
    result = _git("branch", "--show-current")

    if result.returncode != 0:
        return False, "Unable to determine current branch."

    branch = result.stdout.strip()

    if not branch:
        return False, "Detached HEAD is not permitted."

    if not branch.startswith(AUTO_BRANCH_PREFIX):
        return (
            False,
            "Unattended development requires a test/* branch; "
            f"current branch is {branch!r}.",
        )

    return True, branch


def _tracked_in_head(path: str) -> bool:
    return _git("cat-file", "-e", f"HEAD:{path}").returncode == 0


def validate_task_policy(
    task_name: str,
    files_list: list[str],
) -> tuple[bool, str]:
    expected = LOW_RISK_AUTO_TASK_SCOPES.get(task_name)

    if expected is None:
        return (
            False,
            f"{task_name!r} is not classified LOW risk for unattended execution.",
        )

    if frozenset(files_list) != expected:
        return (
            False,
            "Task file scope does not exactly match the approved LOW-risk scope.",
        )

    # Existing tests remain human-owned because tests/ is protected in the
    # autonomous/self-improvement path. These tasks may only CREATE new tests.
    existing_tests = sorted(
        path
        for path in files_list
        if path.startswith("tests/") and _tracked_in_head(path)
    )

    if existing_tests:
        return (
            False,
            "Unattended tasks may not modify existing tests: "
            + ", ".join(existing_tests),
        )

    return True, ""


def _changed_paths() -> set[str]:
    result = _git(
        "status",
        "--porcelain",
        "--untracked-files=all",
    )

    if result.returncode != 0:
        return {"<git-status-failed>"}

    changed: set[str] = set()

    for line in result.stdout.splitlines():
        if not line:
            continue

        # Porcelain v1 paths:
        # XY path
        # XY old -> new
        value = line[3:]

        if " -> " in value:
            value = value.split(" -> ", 1)[1]

        changed.add(value)

    return changed


def _rollback_task_paths(
    files_list: list[str],
    existed_before: set[str],
) -> bool:
    ok = True

    for path in files_list:
        if path in existed_before:
            result = _git(
                "restore",
                "--source=HEAD",
                "--staged",
                "--worktree",
                "--",
                path,
            )

            if result.returncode != 0:
                print(
                    f"❌ Rollback failed for tracked path {path}: "
                    f"{result.stderr.strip()}"
                )
                ok = False
        else:
            target = ROOT / path

            if target.is_symlink() or target.is_file():
                try:
                    target.unlink()
                except OSError as exc:
                    print(f"❌ Could not remove new task file {path}: {exc}")
                    ok = False
            elif target.exists():
                print(
                    f"❌ Refusing recursive rollback of unexpected target: {path}"
                )
                ok = False

    remaining = _changed_paths()

    if remaining:
        print("❌ Rollback did not restore a clean repository:")
        for path in sorted(remaining):
            print(f"   {path}")
        ok = False

    return ok


def run_task(
    task_name: str,
    prompt: str,
    files_str: str,
) -> bool | None:
    print(f"\n{'='*60}")
    print(f"TASK: {task_name}")
    print(f"{'='*60}")

    files_list = files_str.split()

    policy_ok, policy_reason = validate_task_policy(
        task_name,
        files_list,
    )

    if not policy_ok:
        print(f"⏸️ DEFERRED: {policy_reason}")
        return None

    branch_ok, branch_value = _require_test_branch()

    if not branch_ok:
        print(f"❌ {branch_value}")
        return False

    clean_ok, clean_reason = _repo_is_clean()

    if not clean_ok:
        print(f"❌ {clean_reason}")
        return False

    existed_before = {
        path for path in files_list if _tracked_in_head(path)
    }

    (ROOT / "proposals").mkdir(parents=True, exist_ok=True)
    run_start = time.time()

    env = os.environ.copy()
    env["SOC_AUTOPILOT_DEVELOPMENT_CLOUD"] = "1"
    env["SOC_AUTOPILOT_DEVELOPMENT_FREE_ONLY"] = "0"

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "propose_code.py"),
        "--auto",
        prompt,
        "--files",
    ]
    cmd.extend(files_list)

    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=700,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print("❌ propose_code.py timed out.")
        print("   No broad rollback was attempted.")
        return False
    except Exception as exc:
        print(f"❌ propose_code.py execution failed: {exc}")
        return False

    if result.returncode != 0:
        print(
            f"❌ propose_code.py failed with code {result.returncode}"
        )
        print(f"STDERR:\n{result.stderr[-1200:]}")
        print(f"STDOUT:\n{result.stdout[-2500:]}")
        return False

    proposals_dir = ROOT / "proposals"

    new_patches = [
        p for p in proposals_dir.glob("prop-*.patch")
        if p.stat().st_mtime > run_start
    ]

    new_patches.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not new_patches:
        print("❌ No new proposal patch generated.")
        return False

    latest_patch = new_patches[0]
    print(f"✅ Patch: {latest_patch.name}")

    check = subprocess.run(
        ["git", "apply", "--check", str(latest_patch)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if check.returncode != 0:
        print("❌ Patch preflight failed.")
        print(check.stderr)
        return False

    apply_result = subprocess.run(
        ["git", "apply", str(latest_patch)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if apply_result.returncode != 0:
        print("❌ Patch application failed.")
        print(apply_result.stderr)
        return False

    changed = _changed_paths()
    allowed = set(files_list)

    unauthorized = sorted(changed - allowed)

    if unauthorized:
        print("❌ PATCH SCOPE VIOLATION")
        for path in unauthorized:
            print(f"   {path}")
        print(
            "Repository left untouched by automatic rollback so the "
            "unexpected mutation can be reviewed safely."
        )
        return False

    for path in files_list:
        if path.endswith(".py") and (ROOT / path).exists():
            check = subprocess.run(
                ["python3", "-m", "py_compile", path],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            if check.returncode != 0:
                print(f"❌ Syntax failure in {path}")
                if not _rollback_task_paths(files_list, existed_before):
                    print("❌ Rollback failed; stopping.")
                return False

    tests = subprocess.run(
        [
            "python3",
            "-m",
            "pytest",
            "tests/",
            "-q",
            "--tb=line",
            "--ignore=tests/test_cer_critic.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if tests.returncode != 0:
        print("❌ Test suite failed.")
        print(tests.stdout[-5000:])
        print(tests.stderr[-2500:])

        if not _rollback_task_paths(files_list, existed_before):
            print("❌ Rollback failed; stopping.")
        return False

    stage = subprocess.run(
        ["git", "add", "--", *files_list],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if stage.returncode != 0:
        print("❌ Explicit task-file staging failed.")
        print(stage.stderr)

        if not _rollback_task_paths(files_list, existed_before):
            print("❌ Rollback failed; stopping.")
        return False

    staged = _git("diff", "--cached", "--name-only")

    if staged.returncode != 0:
        print("❌ Could not inspect staged scope.")

        if not _rollback_task_paths(files_list, existed_before):
            print("❌ Rollback failed; stopping.")
        return False

    staged_paths = {
        line.strip()
        for line in staged.stdout.splitlines()
        if line.strip()
    }

    if staged_paths != allowed:
        print("❌ STAGING SCOPE VIOLATION")
        print("Expected:")
        for path in sorted(allowed):
            print(f"   {path}")
        print("Staged:")
        for path in sorted(staged_paths):
            print(f"   {path}")

        if not _rollback_task_paths(files_list, existed_before):
            print("❌ Rollback failed; stopping.")
        return False

    diff_check = _git("diff", "--cached", "--check")

    if diff_check.returncode != 0:
        print("❌ Staged diff check failed.")
        print(diff_check.stdout)
        print(diff_check.stderr)

        if not _rollback_task_paths(files_list, existed_before):
            print("❌ Rollback failed; stopping.")
        return False

    commit = subprocess.run(
        [
            "git",
            "commit",
            "-m",
            f"feat: add {task_name}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    if commit.returncode != 0:
        print("❌ Commit failed.")
        print(commit.stderr)

        if not _rollback_task_paths(files_list, existed_before):
            print("❌ Rollback failed; stopping.")
        return False

    # Verify the commit contains only this task's declared files.
    committed = _git(
        "show",
        "--format=",
        "--name-only",
        "HEAD",
    )

    if committed.returncode != 0:
        print("❌ Could not verify commit contents.")
        return False

    committed_paths = {
        line.strip()
        for line in committed.stdout.splitlines()
        if line.strip()
    }

    if committed_paths != allowed:
        print("❌ COMMIT SCOPE VIOLATION")
        print("Expected:")
        for path in sorted(allowed):
            print(f"   {path}")
        print("Committed:")
        for path in sorted(committed_paths):
            print(f"   {path}")
        return False

    print("✅ SUCCESS")
    print(f"   Local commit created on: {branch_value}")
    print(f"   Files committed: {len(committed_paths)}")

    return True


if __name__ == "__main__":
    budget = APIBudgetManager()
    passed = 0
    failed = 0
    deferred = 0

    branch_ok, branch_value = _require_test_branch()

    if not branch_ok:
        print(f"🛑 {branch_value}")
        sys.exit(1)

    clean_ok, clean_reason = _repo_is_clean()

    if not clean_ok:
        print(f"🛑 {clean_reason}")
        sys.exit(1)

    print("🌙 OVERNIGHT RUNNER STARTED")
    print(f"   Tasks: {len(TASKS)}")
    print("   Auto-risk policy: LOW only")
    print(f"   Branch: {branch_value}")
    print(f"   Budget: {budget.get_remaining('openrouter')}")

    for task_name, full_prompt in TASKS:
        if not budget.can_proceed("openrouter"):
            print("\n🛑 Budget exhausted. Stopping safely.")
            break

        parts = full_prompt.rsplit("|", 1)
        prompt = parts[0]
        files_str = parts[1] if len(parts) > 1 else task_name

        result = run_task(task_name, prompt, files_str)

        if result is True:
            passed += 1
        elif result is None:
            deferred += 1
        else:
            failed += 1

            clean_ok, clean_reason = _repo_is_clean()

            if not clean_ok:
                print(
                    "\n🛑 Repository is not clean after task failure. "
                    "Stopping before the next task."
                )
                break

        time.sleep(2)

    print(f"\n{'='*60}")
    print("🌙 OVERNIGHT RUNNER COMPLETE")
    print(f"   Passed:   {passed}")
    print(f"   Failed:   {failed}")
    print(f"   Deferred: {deferred}")
    print(f"{'='*60}")

    report = ROOT / "proposals" / "MORNING_REPORT.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# Morning Report\n"
        f"- Passed: {passed}\n"
        f"- Failed: {failed}\n"
        f"- Deferred: {deferred}\n"
    )
    print(f"📋 Report: {report}")
'''

path.write_text(prefix + replacement)
print("Runner replacement complete.")
PY

RC=$?
if [ "$RC" -ne 0 ]; then
    cleanup_failed
fi

echo
echo "===== PATCHING .gitignore ====="

python3 - "$IGNORE_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()

entries = (
    "# Disposable development artifacts\n"
    ".worktrees/\n"
    "*.bak-*\n"
)

missing = []

for line in (
    ".worktrees/",
    "*.bak-*",
):
    if line not in text.splitlines():
        missing.append(line)

if missing:
    block = (
        "\n# Disposable development artifacts\n"
        + "\n".join(missing)
        + "\n"
    )
    path.write_text(text.rstrip() + "\n" + block)

print("Gitignore update complete.")
PY

RC=$?
if [ "$RC" -ne 0 ]; then
    cleanup_failed
fi

echo
echo "===== SYNTAX ====="

python3 -m py_compile "$RUNNER"
RC=$?

if [ "$RC" -ne 0 ]; then
    echo "ERROR: runner syntax failure"
    cleanup_failed
fi

echo "PASS"

echo
echo "===== DIFF CHECK ====="

git diff --check
RC=$?

if [ "$RC" -ne 0 ]; then
    echo "ERROR: diff check failure"
    cleanup_failed
fi

echo "PASS"

echo
echo "===== STATIC SAFETY ASSERTIONS ====="

if grep -nF '["git", "clean", "-fd"]' "$RUNNER"; then
    echo "ERROR: broad git clean remains"
    cleanup_failed
fi

if grep -nF '["git", "reset", "--hard", "HEAD"]' "$RUNNER"; then
    echo "ERROR: broad git reset remains"
    cleanup_failed
fi

if grep -nF '["git", "add", "-A"]' "$RUNNER"; then
    echo "ERROR: broad git add remains"
    cleanup_failed
fi

if ! grep -q '["git", "add", "--", \*files_list]' "$RUNNER"; then
    echo "ERROR: explicit task-file staging not found"
    cleanup_failed
fi

if ! grep -q 'LOW_RISK_AUTO_TASK_SCOPES' "$RUNNER"; then
    echo "ERROR: low-risk policy missing"
    cleanup_failed
fi

if ! grep -q 'AUTO_BRANCH_PREFIX = "test/"' "$RUNNER"; then
    echo "ERROR: test-branch gate missing"
    cleanup_failed
fi

echo "PASS"

echo
echo "===== POLICY ASSERTIONS ====="

python3 - <<'PY'
import scripts.overnight_runner as r

cases = [
    (
        "engine/alert_correlator.py",
        [
            "engine/alert_correlator.py",
            "contracts/incident_models.py",
            "tests/test_alert_correlator.py",
        ],
        True,
    ),
    (
        "engine/sigma_generator.py",
        [
            "engine/sigma_generator.py",
            "tests/test_sigma_generator.py",
        ],
        True,
    ),
    (
        "engine/wazuh_response.py",
        [
            "engine/wazuh_response.py",
            "tests/test_wazuh_response.py",
        ],
        False,
    ),
]

for task, files, expected in cases:
    ok, reason = r.validate_task_policy(task, files)

    if ok != expected:
        raise SystemExit(
            f"POLICY FAILURE: {task}: expected {expected}, got {ok}: {reason}"
        )

print("PASS: alert_correlator = LOW/allowed")
print("PASS: sigma_generator = LOW/allowed")
print("PASS: wazuh_response = MEDIUM/deferred")
PY

RC=$?

if [ "$RC" -ne 0 ]; then
    cleanup_failed
fi

echo
echo "===== TARGETED REGRESSION SUITE ====="

python3 -m pytest -q \
    tests/test_protected_kernel.py \
    tests/pipeline/test_aider_development_worker.py \
    tests/pipeline/test_development_worker_pipeline.py \
    tests/pipeline/test_development_worker_dispatch.py \
    tests/pipeline/test_development_worker_lifecycle.py

RC=$?

if [ "$RC" -ne 0 ]; then
    echo "ERROR: targeted regression suite failed"
    cleanup_failed
fi

echo "PASS"

echo
echo "===== FULL TEST SUITE ====="

python3 -m pytest -q \
    tests/ \
    --tb=line \
    --ignore=tests/test_cer_critic.py

RC=$?

if [ "$RC" -ne 0 ]; then
    echo "ERROR: full test suite failed"
    cleanup_failed
fi

echo "PASS"

echo
echo "===== FINAL DIFF ====="

git diff -- "$RUNNER" "$IGNORE_FILE"

echo
echo "===== FINAL STATUS ====="

git status --short --branch

echo
echo "============================================================"
echo "GATED HARDENING VALIDATION PASSED"
echo "============================================================"
echo
echo "No Aider execution occurred."
echo "No development task was committed."
echo "No merge or push occurred."
echo
echo "Review the diff above before committing the hardening."
echo "Backups retained:"
echo "  $RUNNER_BACKUP"
echo "  $IGNORE_BACKUP"
