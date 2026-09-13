#!/usr/bin/env bash
# Overnight loop: budget-gated single drain (internal loop handles passes), morning report.
cd "$(dirname "$0")/.."

LOG="overnight/run_$(date +%Y%m%d_%H%M%S).log"
REPORT="overnight/morning_report.md"
MIN_DAILY=60

echo "Overnight run started: $(date)" | tee "$LOG"
START_BACKLOG=$(python3 -c "import json;print(len(json.load(open('overnight/fix_backlog.json'))))")
echo "Starting backlog: $START_BACKLOG" | tee -a "$LOG"

# Budget gate
echo "========== Budget check  $(date +%H:%M:%S) ==========" | tee -a "$LOG"
if python3 - "$MIN_DAILY" >>"$LOG" 2>&1 <<'PY'
import sys
sys.path.insert(0, '.')
from overnight.budget_manager import APIBudgetManager
min_daily = int(sys.argv[1])
b = APIBudgetManager()
for provider in ("gemini", "openrouter"):
    daily = b.get_remaining(provider).get("per_day", 9999)
    print(f"  budget[{provider}] daily remaining: {daily}")
    if daily < min_daily:
        print(f"  -> below {min_daily}, stopping"); sys.exit(1)
sys.exit(0)
PY
then
    echo "========== Drain  $(date +%H:%M:%S) ==========" | tee -a "$LOG"
    PYTHONUNBUFFERED=1 python3 overnight/self_improver.py --drain-backlog --fixes-per-pass 4 >>"$LOG" 2>&1
else
    echo "Budget gate tripped — ending." | tee -a "$LOG"
fi

# Morning report
END_BACKLOG=$(python3 -c "import json;print(len(json.load(open('overnight/fix_backlog.json'))))" 2>/dev/null || echo "?")
END_DEFERRED=$(python3 -c "import json;print(len(json.load(open('overnight/fix_backlog_deferred.json'))))" 2>/dev/null || echo "?")
FIXES=$(git log --oneline --grep="Auto-fix" --since="12 hours ago" | wc -l)
{
  echo "# Overnight Report — $(date)"; echo ""
  echo "| Metric | Value |"; echo "|---|---|"
  echo "| Auto-fix commits (12h) | $FIXES |"
  echo "| Backlog | $START_BACKLOG -> $END_BACKLOG |"
  echo "| Deferred | $END_DEFERRED |"; echo ""
  echo "Log: \`$LOG\`"; echo ""
  echo "## Errors"; grep -iE "traceback|❌|not valid Python" "$LOG" | tail -15 || echo "None."
} > "$REPORT"

echo "Overnight run finished: $(date)" | tee -a "$LOG"
