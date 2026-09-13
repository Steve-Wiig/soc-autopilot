#!/bin/bash
# Ensures exactly one self_improver instance is running
cd "$(dirname "$0")/.."

if pgrep -f "self_improver.py" > /dev/null; then
    echo "⚠️  Already running: $(pgrep -fa self_improver.py)"
    echo "   Use 'pkill -f self_improver.py' to stop first."
    exit 1
fi

nohup python3 overnight/self_improver.py --loop --max-iterations 20 \
    >> overnight/improver_$(date +%Y%m%d).log 2>&1 &

echo "✅ Started PID: $!"
