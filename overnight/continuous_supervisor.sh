#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."

set -a
source .env
set +a

LOG="overnight/continuous_supervisor.log"

cleanup() {
    echo "[$(date)] Supervisor stopping." >> "$LOG"

    if [[ -n "${CHILD_PID:-}" ]] && kill -0 "$CHILD_PID" 2>/dev/null; then
        echo "[$(date)] Stopping child PID $CHILD_PID." >> "$LOG"
        kill "$CHILD_PID" 2>/dev/null || true
        wait "$CHILD_PID" 2>/dev/null || true
    fi

    exit 0
}

trap cleanup INT TERM

echo "============================================================" >> "$LOG"
echo "[$(date)] Continuous supervisor started." >> "$LOG"
echo "============================================================" >> "$LOG"

while true; do
    echo "[$(date)] Starting self-improver cycle." >> "$LOG"

    PYTHONUNBUFFERED=1 python3 overnight/self_improver.py --fixes-per-pass 10 >> "$LOG" 2>&1 &
    CHILD_PID=$!

    echo "[$(date)] Child PID: $CHILD_PID" >> "$LOG"

    wait "$CHILD_PID"
    STATUS=$?

    echo "[$(date)] Child exited with status $STATUS." >> "$LOG"

    # Prevent rapid crash/restart loops.
    sleep 30
done
