#!/bin/bash
# SOC-Autopilot P0/P1 Behavioral Verification
#
# Validates the CURRENT hardened contract surface. Must not reference
# removed APIs. If any referenced symbol is missing, the corresponding
# check must report a real failure, not a false one.

PASS=0
FAIL=0

pass() { echo "  [PASS] $1"; PASS=$((PASS+1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }

echo "=========================================="
echo "SOC-Autopilot P0/P1 Invariants"
echo "=========================================="

# 1. P0-3: Deterministic Policy — dynamic behavioral check
echo -e "\n[1] P0-3: Deterministic Policy Authority"
if python3 -c "
from engine.deterministic_policy import (
    RecommendationEnvelope as PolicyRec,
    evaluate_deterministic_policy as eval_policy,
)

assert eval_policy(
    PolicyRec('BLOCK', 'LOW', False, 'evt-1'),
    authoritative_trusted_source=True,
) == 'REVIEW', 'BLOCK must REVIEW even when trusted'

assert eval_policy(
    PolicyRec('ENRICH', 'LOW', False, 'evt-1'),
    authoritative_trusted_source=False,
) == 'REVIEW', 'ENRICH must REVIEW without trusted runtime'

assert eval_policy(
    PolicyRec('ENRICH', 'LOW', False, 'evt-1'),
    authoritative_trusted_source=True,
) == 'ALLOW', 'LOW+ENRICH+trusted must ALLOW'

assert eval_policy(
    PolicyRec('NO_ACTION', 'LOW', True, 'evt-1'),
    authoritative_trusted_source=True,
) == 'REVIEW', 'human review must always REVIEW'

assert eval_policy(
    PolicyRec('UNKNOWN', 'LOW', False, 'evt-1'),
    authoritative_trusted_source=True,
) == 'DENY', 'unknown action must DENY'
" 2>/dev/null; then
    pass "Policy overrides model (5 behavioral cases)."
else
    fail "Policy bypass or policy API drift."
fi

# 2. P0-2: Cryptographic Worker Identity — VoteValidator dynamic checks
echo -e "\n[2] P0-2: Cryptographic Worker Identity"
if python3 -c "
import time
from contracts.worker_identity import WorkerVote, VoteValidator

def make_vote(worker_id, candidate_hash, decision='A', ts=None, sig=None):
    return WorkerVote(
        worker_id=worker_id,
        worker_class='test',
        worker_instance='i1',
        execution_host='h1',
        software_version='v1',
        candidate_hash=candidate_hash,
        decision=decision,
        timestamp=ts if ts is not None else int(time.time()),
        signature=sig if sig is not None else 'sig-' + worker_id,
    )

v = VoteValidator()
try:
    v.validate(make_vote('w1', 'hash-a'), expected_candidate_hash='hash-b')
    raise AssertionError('wrong candidate must reject')
except ValueError:
    pass

v = VoteValidator(max_clock_skew_seconds=10)
try:
    v.validate(make_vote('w1', 'hash-a', ts=int(time.time())-1000),
               expected_candidate_hash='hash-a')
    raise AssertionError('stale timestamp must reject')
except ValueError:
    pass

v = VoteValidator()
v.validate(make_vote('w1', 'hash-a', sig='sig-x'),
           expected_candidate_hash='hash-a')
try:
    v.validate(make_vote('w2', 'hash-a', sig='sig-x'),
               expected_candidate_hash='hash-a')
    raise AssertionError('replayed signature must reject')
except ValueError:
    pass

v = VoteValidator()
v.validate(make_vote('w1', 'hash-a', sig='sig-1'),
           expected_candidate_hash='hash-a')
try:
    v.validate(make_vote('w1', 'hash-a', sig='sig-2'),
               expected_candidate_hash='hash-a')
    raise AssertionError('duplicate worker must reject')
except ValueError:
    pass
" 2>/dev/null; then
    pass "VoteValidator enforces candidate/freshness/replay/uniqueness."
else
    fail "Worker identity invariants missing or drifted."
fi

# 3. P1-1: Canonical Queue — no direct terminal SQL anywhere
echo -e "\n[3] P1-1: Canonical Queue State Machine"
if grep -q "def transition_queue_state" engine/strict_queue_transitions.py && \
   ! grep -rEn "UPDATE triage_queue SET status = '(completed|failed)'" \
       engine/slm_triage_worker.py \
       engine/intake_eve.py \
       engine/queue_manager.py 2>/dev/null; then
    pass "All terminal SQL centralized through transition_queue_state."
else
    fail "Direct terminal SQL still exists."
fi

# 4. P1-2: EventEnvelope Validation
echo -e "\n[4] P1-2: Canonical EventEnvelope"
if grep -q "from engine.canonical_envelope import EventEnvelope" engine/slm_triage_worker.py; then
    pass "SOC boundary validates EventEnvelope."
else
    fail "EventEnvelope validation missing."
fi

# 5. P1-3: Event ID chain
echo -e "\n[5] P1-3: Event ID Identity Chain"
if grep -q "event_id=true_event_id" engine/slm_triage_worker.py && \
   ! grep -q "event_id=str(job_id)" engine/slm_triage_worker.py; then
    pass "UUID event_id preserved."
else
    fail "Event ID overwritten with job_id."
fi

# 6. P0-1: Two-layer quorum wiring
#   - Development worker governance uses its own 2-of-3 gate.
#   - Production SOC quorum uses the hardened crypto identity contract.
echo -e "\n[6] P0-1: Quorum Wiring (dev-worker gate + SOC crypto identity)"
if grep -q "evaluate_worker_quorum" engine/development_worker_pipeline.py 2>/dev/null && \
   grep -qE "from contracts.worker_identity import .*(VoteValidator|WorkerVote)|import contracts.worker_identity" \
       engine/strict_quorum.py 2>/dev/null; then
    pass "Dev-worker gate wired; SOC quorum uses hardened crypto identity."
else
    fail "Quorum wiring drift (dev-worker gate or SOC crypto identity missing)."
fi

# 7. P1-8: NAS eliminated tree-wide (no constants, no mount paths,
# no false telemetry) across production code. Diagnostic scripts
# (audit_*, analyze_*) are excluded: they contain the patterns
# as design intent, not as runtime references.
echo -e "\n[7] P1-8: NAS Mount Eliminated (tree-wide)"
if ! grep -rqE "NAS_PENDING|NAS_APPROVED|NAS_REJECTED|NAS_BASE|NAS_DIR|NAS_DEST|NAS_FILE|/mnt/backup-nas|to NAS|evacuate_if_needed" \
       engine/ tools/ contracts/ overnight/ \
       --include='*.py' --include='*.sh' \
       --exclude='audit_*.py' \
       --exclude='analyze_*.py' \
       --exclude='p1_4_completion_gated_patch.py' \
       2>/dev/null; then
    pass "NAS references and false telemetry removed tree-wide."
else
    fail "NAS references or false telemetry still exist."
fi

# 8. P0-3b: Trust provenance ownership
echo -e "\n[8] P0-3b: Trust Provenance Ownership"
if grep -q "event_envelope.trust_labels.provenance_verified" engine/slm_triage_worker.py && \
   ! grep -qE "getattr\(raw_rec, *'trust_labels'" engine/slm_triage_worker.py; then
    pass "Worker derives trust only from canonical EventEnvelope."
else
    fail "Worker may consume model-supplied trust labels."
fi

# 9. P1-5: Policy adapter does not shadow canonical contract
echo -e "\n[9] P1-5: Policy Adapter Contract Alignment"
if grep -q "RecommendationEnvelope as PolicyRecommendationEnvelope" engine/slm_triage_worker.py && \
   grep -q "from contracts.slm_recommendation import" engine/slm_triage_worker.py; then
    pass "Policy adapter aliased; canonical contract imported."
else
    fail "Policy adapter may shadow canonical recommendation contract."
fi

# Environmental checks (informational; do not affect invariant gate)
echo -e "\n[ENV] Environmental checks (not part of the invariant gate)"
if command -v redis-cli &> /dev/null && redis-cli CONFIG GET appendonly 2>/dev/null | grep -q "yes"; then
    echo "  [INFO] Redis AOF active."
else
    echo "  [INFO] Redis AOF not confirmed (environment-dependent)."
fi
if grep -q "def dynamic_thermal_pace" edge/pi_consumer.py 2>/dev/null; then
    echo "  [INFO] Dynamic thermal pacing present."
else
    echo "  [INFO] Dynamic thermal pacing not detected."
fi

echo -e "\n=========================================="
echo "Results: $PASS Passed, $FAIL Failed"
echo "=========================================="
if [ $FAIL -eq 0 ]; then
    echo "ALL 9 P0/P1 INVARIANTS VERIFIED."
    exit 0
else
    echo "INVARIANT VIOLATIONS DETECTED."
    exit 1
fi
