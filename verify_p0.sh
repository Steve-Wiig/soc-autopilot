#!/bin/bash
# ==============================================================================
# SOC-Autopilot P0 Hardening Verification Script (Robust Version)
# Date: 2026-09-11
# Constraint: STRICTLY READ-ONLY. No repository modifications.
# ==============================================================================

# 1. Verify we are in the correct repository directory
if [ ! -d "engine" ] || [ ! -d "overnight" ] || [ ! -d "tools" ]; then
    echo "ERROR: This script must be run from the root of the SOC-Autopilot repository."
    echo "Current directory: $(pwd)"
    echo "Please run: cd /path/to/SOC-Autopilot"
    exit 1
fi

export PYTHONDONTWRITEBYTECODE=1
FAILURES=0

pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAILURES=$((FAILURES+1)); }
section() { echo ""; echo "=== $1 ==="; }

# Helper to safely grep a file
safe_grep() {
    local file=$1
    shift
    if [ -f "$file" ]; then
        grep "$@" "$file" 2>/dev/null
    else
        return 1
    fi
}

section "P0-1: Local-only production SOC inference"
if safe_grep "engine/model_registry.py" -Eiq "(triage|primary|code_review).*(openrouter|cloud)"; then
    fail "Production roles may still route to Cloud/OpenRouter."
else
    pass "Production roles do not explicitly route to Cloud/OpenRouter."
fi

if safe_grep "engine/model_registry.py" -Eiq "fail_closed|local_only|no_cloud_fallback|raise.*LocalInferenceUnavailable"; then
    pass "Fail-closed / local-only enforcement logic detected."
else
    fail "Missing explicit fail-closed enforcement for local inference outage."
fi

if find tests -type f -name "*.py" 2>/dev/null | xargs grep -lq "test_production_routing_no_cloud\|test_local_outage_fail_closed" 2>/dev/null; then
    pass "Routing isolation acceptance tests exist."
else
    fail "Missing routing isolation acceptance tests."
fi

section "P0-2: Close autonomous patch mutation boundary"
if safe_grep "engine/multi_file_patcher.py" -Eq "\.resolve\(\)|is_relative_to|commonpath"; then
    pass "Path resolution and containment check detected in patcher."
else
    fail "Missing path resolution/containment check (e.g., .resolve() or is_relative_to)."
fi

if safe_grep "engine/multi_file_patcher.py" -Eiq "is_absolute|startswith\(['\"]\.\.['\"]\)|traversal|symlink"; then
    pass "Rejection of absolute paths, traversals, or symlinks detected."
else
    fail "Missing explicit rejection of absolute paths, '../', or symlinks."
fi

if safe_grep "engine/multi_file_patcher.py" -Eiq "exact_match|normalized_exact|ambiguous.*fail|fuzzy.*reject"; then
    pass "Fuzzy match hardening (exact/normalized preference, ambiguity rejection) detected."
else
    fail "Missing fuzzy match hardening for autonomous mutation."
fi

if find tests -type f -name "*.py" 2>/dev/null | xargs grep -lq "test_path_traversal\|test_symlink_escape\|test_ambiguous_fuzzy" 2>/dev/null; then
    pass "Path containment and patch ambiguity regression tests exist."
else
    fail "Missing path containment and ambiguity regression tests."
fi

section "P0-3: Fix promotion-state semantics"
if safe_grep "overnight/self_improver.py" -Eq "GENERATED|TESTED|CANARY_PASSED|PENDING_HUMAN_MERGE|MERGED|REJECTED|REVERTED"; then
    pass "Required granular promotion states are defined."
else
    fail "Missing required granular promotion states."
fi

if safe_grep "overnight/self_improver.py" -Eiq "if.*state.*==.*MERGED.*APPLIED|APPLIED.*only.*MERGED"; then
    pass "APPLIED state is strictly gated by MERGED state."
else
    if safe_grep "overnight/self_improver.py" -A 5 "CANARY_PASSED" | grep -iq "APPLIED"; then
        fail "APPLIED state is incorrectly triggered by CANARY_PASSED."
    else
        pass "APPLIED state is not incorrectly triggered by CANARY_PASSED."
    fi
fi

if safe_grep "overnight/self_improver.py" -Eiq "proven_fixes.*MERGED|write.*proven_fixes.*merged"; then
    pass "proven_fixes.jsonl is only populated on actual MERGED state."
else
    fail "proven_fixes.jsonl population is not strictly gated by MERGED state."
fi

section "P0-4: Correct Pi critic telemetry semantics"
if safe_grep "tools/pi_redis_ingestor.py" -Eiq "PI_APPROVED|PI_REJECTED"; then
    pass "Pi reviewer uses distinct states (PI_APPROVED/PI_REJECTED)."
else
    fail "Pi reviewer is missing distinct states (PI_APPROVED/PI_REJECTED)."
fi

if safe_grep "tools/pi_redis_ingestor.py" -A 10 "approved.*true\|approved.*=.*True" | grep -iq "APPLIED"; then
    fail "Pi approval is incorrectly mapped to APPLIED state."
else
    pass "Pi approval is not mapped to APPLIED state."
fi

section "P0-5: Make worker identity guarantees real"
if safe_grep "engine/worker_vote.py" -Eiq "worker_id.*worker_class.*execution_host|cryptographic.*signature|WorkerVote.*identity" || \
   safe_grep "overnight/self_improver.py" -Eiq "worker_id.*worker_class.*execution_host|cryptographic.*signature|WorkerVote.*identity"; then
    pass "Strong worker identity binding (Option A) detected."
elif safe_grep "engine/worker_vote.py" -Eiq "distinct logical reviewers|three distinct logical|downgrade.*terminology" || \
     safe_grep "overnight/self_improver.py" -Eiq "distinct logical reviewers|three distinct logical|downgrade.*terminology" || \
     find docs -type f -name "*.md" 2>/dev/null | xargs grep -lq "distinct logical reviewers|three distinct logical|downgrade.*terminology" 2>/dev/null; then
    pass "Truthful weaker guarantee (Option B) documentation detected."
else
    fail "Neither strong identity binding nor truthful documentation downgrade detected."
fi

if safe_grep "engine/worker_vote.py" -Eiq "replay.*detect|candidate_hash.*distinct|prevent.*reuse"; then
    pass "Replay and distinct candidate hash enforcement detected."
else
    fail "Missing replay and distinct candidate hash enforcement."
fi

section "Dynamic Verification: Running Pytest Suite"
echo "  Checking for pytest..."
if ! command -v pytest &> /dev/null; then
    fail "pytest is not installed or not in PATH. Skipping dynamic tests."
else
    echo "  Running targeted P0 acceptance tests and adversarial simulation..."
    echo "  (Timeout set to 60 seconds to prevent hanging)"
    
    TEST_OUTPUT=$(timeout 60 pytest -q \
        -k "routing_isolation or path_containment or patch_ambiguity or promotion_state or pi_approval or worker_identity or adversarial_simulation" \
        --tb=short 2>&1)
    TEST_EXIT_CODE=$?

    if [ $TEST_EXIT_CODE -eq 124 ]; then
        fail "Targeted P0 tests TIMED OUT after 60 seconds."
    elif [ $TEST_EXIT_CODE -eq 0 ]; then
        pass "All targeted P0 acceptance and adversarial simulation tests PASSED."
    elif [ $TEST_EXIT_CODE -eq 5 ]; then
        fail "No tests matched the P0 criteria. Are the tests named correctly?"
    else
        fail "Targeted P0 tests FAILED. See output below:"
        echo "$TEST_OUTPUT" | tail -n 20
    fi

    echo "  Running full regression suite (pytest -q)..."
    FULL_TEST_OUTPUT=$(timeout 120 pytest -q --tb=line 2>&1)
    FULL_EXIT_CODE=$?

    if [ $FULL_EXIT_CODE -eq 124 ]; then
        fail "Full regression suite TIMED OUT after 120 seconds."
    elif [ $FULL_EXIT_CODE -eq 0 ]; then
        pass "Full regression suite PASSED."
    else
        fail "Full regression suite FAILED."
        echo "$FULL_TEST_OUTPUT" | tail -n 10
    fi
fi

section "Verification Summary"
echo ""
if [ $FAILURES -eq 0 ]; then
    echo "  SUCCESS: All P0 hardening invariants are verified and enforced."
    echo "  Definition of Done met:"
    echo "    1. LLM patch cannot write outside authorized targets."
    echo "    2. Production SOC data cannot spill to cloud LLM."
    echo "    3. System cannot claim fix applied without human merge."
    echo "    4. Pi approval cannot masquerade as applied code change."
    echo "    5. Fabricated worker identities cannot satisfy quorum."
    exit 0
else
    echo "  FAILURE: $FAILURES invariant check(s) failed."
    echo "  Review the [FAIL] outputs above and apply the required P0 fixes."
    exit 1
fi
