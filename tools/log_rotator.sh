#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$REPO_ROOT/overnight"
ARCHIVE_DIR="$REPO_ROOT/overnight/archive/logs"
LOCK_FILE="/tmp/soc_log_rotator.lock"
MAX_SIZE=$((50 * 1024 * 1024))

exec 200>"$LOCK_FILE"
flock -n 200 || { echo "Another rotation is running."; exit 0; }

mkdir -p "$ARCHIVE_DIR" || { echo "$(date '+%Y-%m-%d %H:%M:%S') - FAIL: cannot create $ARCHIVE_DIR"; exit 1; }
if [ ! -w "$ARCHIVE_DIR" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - FAIL: $ARCHIVE_DIR is not writable"
    exit 1
fi

ROTATABLE_LOGS=("improvement_ledger.jsonl" "reasoning_ledger.jsonl" "failed_fixes.jsonl" "proven_fixes.jsonl")

for fname in "${ROTATABLE_LOGS[@]}"; do
    SRC="$LOG_DIR/$fname"
    if [ ! -f "$SRC" ]; then continue; fi
    SIZE=$(stat -c%s "$SRC" 2>/dev/null || echo 0)
    if [ "$SIZE" -gt "$MAX_SIZE" ]; then
        TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
        DEST="$ARCHIVE_DIR/${fname}.${TIMESTAMP}.jsonl"
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Rotating $fname ($SIZE bytes)..."
        if rsync -a "$SRC" "$DEST"; then
            DEST_SIZE=$(stat -c%s "$DEST" 2>/dev/null || echo 0)
            if [ "$DEST_SIZE" -eq "$SIZE" ]; then
                SRC_MD5=$(md5sum "$SRC" | awk '{print $1}')
                DEST_MD5=$(md5sum "$DEST" | awk '{print $1}')
                if [ "$SRC_MD5" = "$DEST_MD5" ]; then
                    : > "$SRC"
                    echo "$(date '+%Y-%m-%d %H:%M:%S') - SUCCESS: Rotated $fname"
                else
                    echo "$(date '+%Y-%m-%d %H:%M:%S') - FAIL: MD5 mismatch for $fname. NOT truncated."
                fi
            else
                echo "$(date '+%Y-%m-%d %H:%M:%S') - FAIL: Size mismatch for $fname. NOT truncated."
            fi
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') - FAIL: rsync failed for $fname. NOT truncated."
        fi
    fi
done
