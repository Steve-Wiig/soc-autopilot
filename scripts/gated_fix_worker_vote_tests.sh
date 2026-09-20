#!/usr/bin/env bash

# Test-only WorkerVote task_id migration.
# No production files are modified.
# No Git cleanup, commit, merge, push, or Aider execution.
#
# Intentionally no `set -e` so a failure cannot terminate the parent shell.

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$ROOT" ]; then
    echo "ERROR: not inside a Git repository"
    exit 1
fi

cd "$ROOT"

FILES=(
    "tests/helpers/crypto_test_helpers.py"
    "tests/test_adversarial.py"
    "tests/test_worker_identity.py"
    "tests/test_p0_identity_invariant.py"
)

RUN_ID="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="tests/.gated-worker-vote-backup-${RUN_ID}"

restore() {
    echo
    echo "===== RESTORING TEST FILES ====="

    for file in "${FILES[@]}"; do
        if [ -f "$BACKUP_DIR/$file" ]; then
            mkdir -p "$(dirname "$file")"
            cp -a "$BACKUP_DIR/$file" "$file"
        fi
    done

    echo "Test files restored."
    echo
    git status --short --branch
    exit 1
}

echo "============================================================"
echo "GATED TEST FIX: WorkerVote task_id migration"
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
        echo "ERROR: refusing protected-test modification on non-test branch"
        exit 1
        ;;
esac

for file in "${FILES[@]}"; do
    if ! git diff --quiet -- "$file"; then
        echo "ERROR: target has tracked modifications: $file"
        git diff -- "$file"
        exit 1
    fi

    if ! git diff --cached --quiet -- "$file"; then
        echo "ERROR: target has staged modifications: $file"
        git diff --cached -- "$file"
        exit 1
    fi
done

echo "PASS: all target tests clean"

echo
echo "===== BACKUPS ====="

for file in "${FILES[@]}"; do
    mkdir -p "$BACKUP_DIR/$(dirname "$file")"

    if ! cp -a "$file" "$BACKUP_DIR/$file"; then
        echo "ERROR: backup failed for $file"
        exit 1
    fi
done

echo "Backup directory: $BACKUP_DIR"

echo
echo "===== PATCHING TEST HELPER ====="

python3 - <<'PY'
from pathlib import Path
import sys

path = Path("tests/helpers/crypto_test_helpers.py")
text = path.read_text()

old = '''        candidate_hash=candidate_hash,
        decision=decision,
        timestamp=int(time.time()),
        signature="placeholder",
'''

new = '''        candidate_hash=candidate_hash,
        decision=decision,
        timestamp=int(time.time()),
        task_id="test-task",
        signature="placeholder",
'''

if old not in text:
    print("ERROR: expected helper WorkerVote block not found.")
    sys.exit(1)

if text.count(old) != 1:
    print("ERROR: helper replacement is not unique.")
    sys.exit(1)

path.write_text(text.replace(old, new, 1))
print("Helper patched.")
PY

RC=$?
if [ "$RC" -ne 0 ]; then
    restore
fi

echo
echo "===== PATCHING ADVERSARIAL TESTS ====="

python3 - <<'PY'
from pathlib import Path
import sys

path = Path("tests/test_adversarial.py")
text = path.read_text()

replacements = [
    (
        '''candidate_hash="old_hash",
          decision="APPROVE", timestamp=int(time.time()), signature="old_sig"
''',
        '''candidate_hash="old_hash",
          decision="APPROVE", timestamp=int(time.time()),
          task_id="replay-test", signature="old_sig"
''',
    ),
    (
        '''candidate_hash="new_hash",
          decision="APPROVE", timestamp=int(time.time()), signature="old_sig"
''',
        '''candidate_hash="new_hash",
          decision="APPROVE", timestamp=int(time.time()),
          task_id="replay-test", signature="old_sig"
''',
    ),
    (
        '''candidate_hash="hash1",
          decision="APPROVE", timestamp=int(time.time()), signature="sig1"
''',
        '''candidate_hash="hash1",
          decision="APPROVE", timestamp=int(time.time()),
          task_id="duplicate-worker-test", signature="sig1"
''',
    ),
    (
        '''candidate_hash="hash1",
          decision="REJECT", timestamp=int(time.time()), signature="sig2"
''',
        '''candidate_hash="hash1",
          decision="REJECT", timestamp=int(time.time()),
          task_id="duplicate-worker-test", signature="sig2"
''',
    ),
]

for old, new in replacements:
    if old not in text:
        print("ERROR: expected adversarial WorkerVote block not found:")
        print(old)
        sys.exit(1)

text = text.replace(replacements[0][0], replacements[0][1], 1)
text = text.replace(replacements[1][0], replacements[1][1], 1)
text = text.replace(replacements[2][0], replacements[2][1], 1)
text = text.replace(replacements[3][0], replacements[3][1], 1)

path.write_text(text)
print("Adversarial tests patched.")
PY

RC=$?
if [ "$RC" -ne 0 ]; then
    restore
fi

echo
echo "===== PATCHING WORKER IDENTITY FIXTURE ====="

python3 - <<'PY'
from pathlib import Path
import sys

path = Path("tests/test_worker_identity.py")
text = path.read_text()

old = '''        "candidate_hash": "hash123",
        "decision": "APPROVE",
        "timestamp": int(time.time()),
        "signature": "sig123"
'''

new = '''        "candidate_hash": "hash123",
        "decision": "APPROVE",
        "timestamp": int(time.time()),
        "task_id": "worker-identity-test",
        "signature": "sig123"
'''

if old not in text:
    print("ERROR: expected worker identity fixture block not found.")
    sys.exit(1)

if text.count(old) != 1:
    print("ERROR: worker identity replacement is not unique.")
    sys.exit(1)

path.write_text(text.replace(old, new, 1))
print("Worker identity fixture patched.")
PY

RC=$?
if [ "$RC" -ne 0 ]; then
    restore
fi

echo
echo "===== PATCHING P0 IDENTITY TEST ====="

python3 - <<'PY'
from pathlib import Path
import sys

path = Path("tests/test_p0_identity_invariant.py")
text = path.read_text()

old = '''          candidate_hash="hash1", decision="approve",
          timestamp=int(time.time()), signature="sig1"
'''

new = '''          candidate_hash="hash1", decision="approve",
          timestamp=int(time.time()), task_id="candidate-binding-test",
          signature="sig1"
'''

if old not in text:
    print("ERROR: expected P0 WorkerVote block not found.")
    sys.exit(1)

if text.count(old) != 1:
    print("ERROR: P0 replacement is not unique.")
    sys.exit(1)

path.write_text(text.replace(old, new, 1))
print("P0 identity test patched.")
PY

RC=$?
if [ "$RC" -ne 0 ]; then
    restore
fi

echo
echo "===== VERIFY NO TEST WORKER VOTE IS MISSING TASK_ID ====="

python3 - <<'PY'
from pathlib import Path
import re
import sys

files = [
    Path("tests/helpers/crypto_test_helpers.py"),
    Path("tests/test_adversarial.py"),
    Path("tests/test_worker_identity.py"),
    Path("tests/test_p0_identity_invariant.py"),
]

bad = []

for path in files:
    text = path.read_text()
    for match in re.finditer(r'WorkerVote\((.*?)\)', text, re.DOTALL):
        block = match.group(1)
        if "task_id=" not in block:
            bad.append(str(path))

if bad:
    print("ERROR: WorkerVote constructors missing task_id:")
    for path in sorted(set(bad)):
        print(f"  {path}")
    sys.exit(1)

print("PASS: every WorkerVote constructor in target files has task_id.")
PY

RC=$?
if [ "$RC" -ne 0 ]; then
    restore
fi

echo
echo "===== SYNTAX ====="

for file in "${FILES[@]}"; do
    case "$file" in
        *.py)
            python3 -m py_compile "$file"
            RC=$?
            if [ "$RC" -ne 0 ]; then
                echo "ERROR: syntax failure: $file"
                restore
            fi
            ;;
    esac
done

echo "PASS"

echo
echo "===== DIFF CHECK ====="

git diff --check -- "${FILES[@]}"
RC=$?

if [ "$RC" -ne 0 ]; then
    echo "ERROR: diff check failed"
    restore
fi

echo "PASS"

echo
echo "===== TARGETED TESTS ====="

python3 -m pytest -q \
    tests/test_adversarial.py \
    tests/test_worker_identity.py \
    tests/test_p0_identity_invariant.py \
    tests/test_phase3_enforcement.py

RC=$?

if [ "$RC" -ne 0 ]; then
    echo "ERROR: targeted WorkerVote tests failed"
    restore
fi

echo "PASS"

echo
echo "===== FULL RELEVANT DEVELOPMENT TESTS ====="

python3 -m pytest -q \
    tests/test_adversarial.py \
    tests/test_worker_identity.py \
    tests/test_p0_identity_invariant.py \
    tests/test_phase3_enforcement.py \
    tests/pipeline/test_development_worker_gate.py \
    tests/pipeline/test_development_worker_pipeline.py \
    tests/pipeline/test_aider_development_worker.py

RC=$?

if [ "$RC" -ne 0 ]; then
    echo "ERROR: relevant development tests failed"
    restore
fi

echo "PASS"

echo
echo "===== FINAL DIFF ====="

git diff -- \
    tests/helpers/crypto_test_helpers.py \
    tests/test_adversarial.py \
    tests/test_worker_identity.py \
    tests/test_p0_identity_invariant.py

echo
echo "===== FINAL STATUS ====="

git status --short --branch

echo
echo "============================================================"
echo "GATED WorkerVote TEST FIX PASSED"
echo "============================================================"
echo
echo "No production code changed."
echo "No Aider execution."
echo "No commit."
echo "Backup retained: $BACKUP_DIR"
echo
echo "Review the diff, then commit these test changes separately."
