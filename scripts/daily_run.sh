#!/bin/bash
# Daily NewsFlow pipeline wrapper — invoked by launchd at scheduled times.
# caffeinate prevents idle sleep mid-run.
set -euo pipefail

REPO="/Users/rushilkr/Projects/newsflow"
VENV="$REPO/venv"
TODAY="$(date +%Y-%m-%d)"
LOCKFILE="$REPO/workspace/pipeline.lock"

# launchd exports a minimal PATH — explicitly include Homebrew, system bins
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$REPO"

LOG="$REPO/workspace/launchd_${TODAY}.log"
mkdir -p "$REPO/workspace"

exec >> "$LOG" 2>&1
echo "=== NewsFlow daily run $(date '+%Y-%m-%d %H:%M:%S') ==="

# Stale-run detection: kill any pipeline from a previous date still running
if [[ -f "$LOCKFILE" ]]; then
    LOCK_DATE="$(cut -d' ' -f1 "$LOCKFILE")"
    LOCK_PID="$(cut -d' ' -f2 "$LOCKFILE")"
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        if [[ "$LOCK_DATE" == "$TODAY" ]]; then
            echo "Pipeline already running for today (PID $LOCK_PID) — skipping."
            exit 0
        else
            echo "Killing stale run from $LOCK_DATE (PID $LOCK_PID)..."
            kill "$LOCK_PID" 2>/dev/null || true
            sleep 2
        fi
    fi
    rm -f "$LOCKFILE"
fi

# Write lock: date + this shell's PID (caffeinate child inherits it)
echo "$TODAY $$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

# Activate virtualenv
if [[ -f "$VENV/bin/activate" ]]; then
    source "$VENV/bin/activate"
else
    echo "ERROR: venv not found at $VENV — run 'python -m venv .venv && pip install -r requirements.txt'"
    exit 1
fi

# Run pipeline — caffeinate -dimsu covers display/disk/system/idle/user idle sleep
echo "Starting pipeline..."
caffeinate -dimsu python -m orchestrator.pipeline

echo "=== Run complete $(date '+%Y-%m-%d %H:%M:%S') ==="
