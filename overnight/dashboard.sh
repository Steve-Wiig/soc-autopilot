#!/usr/bin/env bash
cd "$(dirname "$0")/.."
echo "=== Overnight Drain Status  $(date +%H:%M:%S) ==="
python3 -c "import json;b=len(json.load(open('overnight/fix_backlog.json')));d=len(json.load(open('overnight/fix_backlog_deferred.json')));print(f'Backlog: {b}   Deferred: {d}')"
RECENT=$(git log --oneline --since='30 minutes ago' 2>/dev/null | wc -l)
echo "Auto-fix commits (last 30min): $RECENT"
ALIVE=$(pgrep -f 'self_improver.py --drain-backlog' >/dev/null && echo RUNNING || echo STOPPED)
echo "Drain process: $ALIVE"
echo ""
echo "=== Recent commits ==="
git log --oneline -4
