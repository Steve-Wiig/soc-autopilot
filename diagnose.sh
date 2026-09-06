#!/bin/bash
OUT="diagnose.out"
echo "=== GIT STATUS ===" > $OUT
git status >> $OUT 2>&1
echo "=== GIT DIFF STAT ===" >> $OUT
git diff --stat >> $OUT 2>&1
echo "=== RAW FAILED PATCH ===" >> $OUT
[ -f "overnight/last_failed_raw.txt" ] && head -n 200 overnight/last_failed_raw.txt >> $OUT 2>&1 || echo "Not found" >> $OUT

echo "=== LOCK LOGIC ===" >> $OUT
grep -rn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude-dir=logs --exclude-dir=overnight --exclude="*.log" --exclude="*.out" "locked/exhausted" . >> $OUT 2>&1 || true

echo "=== GHOST NAMES ===" >> $OUT
grep -rn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude-dir=logs --exclude-dir=overnight --exclude="*.log" --exclude="*.out" "GHOST NAMES DETECTED" . >> $OUT 2>&1 || true

echo "=== SEARCH/REPLACE PARSER ===" >> $OUT
grep -rn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude-dir=logs --exclude-dir=overnight --exclude="*.log" --exclude="*.out" "SEARCH/REPLACE blocks parsed" . >> $OUT 2>&1 || true

echo "=== VACUOUS TEST LOGIC ===" >> $OUT
grep -rn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude-dir=logs --exclude-dir=overnight --exclude="*.log" --exclude="*.out" "vacuous test" . >> $OUT 2>&1 || true

echo "=== POISONED CACHE ===" >> $OUT
grep -rn --exclude-dir=.git --exclude-dir=.venv --exclude-dir=venv --exclude-dir=__pycache__ --exclude-dir=logs --exclude-dir=overnight --exclude="*.log" --exclude="*.out" "d64ff97f" . >> $OUT 2>&1 || true

echo "=== OVERNIGHT DIR ===" >> $OUT
ls -la overnight/ >> $OUT 2>&1 || true

echo "Script finished. Output saved to diagnose.out"
