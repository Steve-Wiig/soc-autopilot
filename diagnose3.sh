#!/bin/bash
OUT="diagnose3.out"
: > "$OUT"

{
echo "=== SOURCE SEARCH: LOCK / QUOTA / RATE LIMIT ==="
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' -E 'locked/exhausted|locked|exhausted|remaining|quota|budget|rate.?limit|backoff|cooldown' . 2>/dev/null | head -n 500

echo
echo "=== SOURCE SEARCH: OPENROUTER ==="
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' 'OpenRouter' . 2>/dev/null | head -n 300

echo
echo "=== SOURCE SEARCH: PATCH PARSER ==="
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' 'SEARCH/REPLACE' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' 'blocks parsed' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' 'Aider' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' '<<<<<<<' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' '=======' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' '>>>>>>>' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' 'last_failed_raw' . 2>/dev/null | head -n 200

echo
echo "=== SOURCE SEARCH: GHOST NAMES ==="
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' -Ei 'ghost|NAMES DETECTED' . 2>/dev/null | head -n 300

echo
echo "=== SOURCE SEARCH: TDD RED PHASE ==="
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' -E 'Red Phase|vacuous|Baseline failure|pytest cache hit|fingerprint|TDD' . 2>/dev/null | head -n 300

echo
echo "=== SOURCE SEARCH: HALLUCINATED EVE TEST ==="
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' 'eve_rows' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' 'test_process_eve_file_bulk_insert_memory' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' -F 'process_eve_file(path, conn=conn)' . 2>/dev/null | head -n 200
grep -rn --include='*.py' --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude='*.log' --exclude='*.out' 'triage_queue' . 2>/dev/null | head -n 300

echo
echo "=== FUNCTION MAP: overnight/self_improver.py ==="
grep -n -E '^(class |def |    def )' overnight/self_improver.py 2>/dev/null | head -n 300

echo
echo "=== SELF_IMPROVER: lines 1-120 ==="
awk 'NR>=1 && NR<=120 {printf "%d: %s\n", NR, $0}' overnight/self_improver.py 2>/dev/null

echo
echo "=== SELF_IMPROVER: lines 450-750 ==="
awk 'NR>=450 && NR<=750 {printf "%d: %s\n", NR, $0}' overnight/self_improver.py 2>/dev/null

echo
echo "=== FUNCTION MAP: overnight/llm_client.py ==="
grep -n -E '^(class |def |    def )' overnight/llm_client.py 2>/dev/null | head -n 300

echo
echo "=== LLM_CLIENT: relevant lines ==="
grep -n -E 'OpenRouter|locked|exhausted|remaining|quota|budget|rate|limit|backoff|cooldown|model|fallback' overnight/llm_client.py 2>/dev/null | head -n 500

echo
echo "=== FUNCTION MAP: overnight/budget_manager.py ==="
grep -n -E '^(class |def |    def )' overnight/budget_manager.py 2>/dev/null | head -n 200

echo
echo "=== FILE: overnight/verifier.py ==="
awk '{printf "%d: %s\n", NR, $0}' overnight/verifier.py 2>/dev/null

echo
echo "=== FILE: overnight/openrouter_quota.py ==="
awk '{printf "%d: %s\n", NR, $0}' overnight/openrouter_quota.py 2>/dev/null

echo
echo "=== FILE: overnight/budget_manager.py ==="
awk '{printf "%d: %s\n", NR, $0}' overnight/budget_manager.py 2>/dev/null

echo
echo "=== FILE: tests/pipeline/test_tdd_red_phase.py ==="
awk '{printf "%d: %s\n", NR, $0}' tests/pipeline/test_tdd_red_phase.py 2>/dev/null || echo "not found"

echo
echo "=== ENGINE: intake_eve.py first 250 lines ==="
awk 'NR>=1 && NR<=250 {printf "%d: %s\n", NR, $0}' engine/intake_eve.py 2>/dev/null || echo "not found"

echo
echo "=== STATE: openrouter_quota.json ==="
cat overnight/openrouter_quota.json 2>/dev/null || echo "not found"

echo
echo "=== STATE: model_fallback_cache.json ==="
cat overnight/model_fallback_cache.json 2>/dev/null || echo "not found"

echo
echo "=== STATE: groq_model_cache.json ==="
cat overnight/groq_model_cache.json 2>/dev/null || echo "not found"

echo
echo "=== STATE: api_usage.json first 200 lines ==="
head -n 200 overnight/api_usage.json 2>/dev/null || echo "not found"

echo
echo "=== STATE: fix_backlog.json first 20000 chars ==="
head -c 20000 overnight/fix_backlog.json 2>/dev/null || echo "not found"
echo

echo
echo "=== STATE: failed_fixes.jsonl last 3 lines truncated ==="
tail -n 3 overnight/failed_fixes.jsonl 2>/dev/null | cut -c1-2000 || echo "not found"

echo
echo "=== STATE: improvement_ledger.jsonl last 5 lines truncated ==="
tail -n 5 overnight/improvement_ledger.jsonl 2>/dev/null | cut -c1-2000 || echo "not found"
} > "$OUT"

echo "Done. Output written to diagnose3.out"
