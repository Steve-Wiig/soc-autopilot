#!/bin/bash
OUT="diagnose2.out"
echo "=== SEARCH/REPLACE PARSER ===" > $OUT
grep -rn "SEARCH/REPLACE blocks parsed" overnight/ >> $OUT 2>&1 || echo "Not found" >> $OUT

echo "=== GHOST NAMES ===" >> $OUT
grep -rn "GHOST NAMES DETECTED" overnight/ >> $OUT 2>&1 || echo "Not found" >> $OUT

echo "=== VACUOUS TEST ===" >> $OUT
grep -rn "vacuous test" overnight/ >> $OUT 2>&1 || echo "Not found" >> $OUT

echo "=== LOCK LOGIC ===" >> $OUT
grep -rn "locked/exhausted" overnight/ >> $OUT 2>&1 || echo "Not found" >> $OUT

echo "=== TDD RED PHASE ===" >> $OUT
grep -rn "TDD Red Phase" overnight/ >> $OUT 2>&1 || echo "Not found" >> $OUT

echo "=== FILE LINE COUNTS ===" >> $OUT
wc -l overnight/self_improver.py overnight/verifier.py overnight/overnight_verify_and_develop.py overnight/llm_client.py overnight/budget_manager.py >> $OUT 2>&1 || true

echo "Script finished. Output saved to diagnose2.out"
