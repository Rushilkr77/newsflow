#!/bin/bash
# Daily NewsFlow pipeline wrapper — invoked by launchd at 10:00.
# caffeinate prevents idle sleep mid-run; Ollama is started if not already up.
set -euo pipefail

REPO="/Users/rushilkr/Projects/newsflow"
VENV="$REPO/venv"

# launchd exports a minimal PATH — explicitly include Homebrew, system bins
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$REPO"

LOG="$REPO/workspace/launchd_$(date +%Y-%m-%d).log"
mkdir -p "$REPO/workspace"

exec >> "$LOG" 2>&1
echo "=== NewsFlow daily run $(date '+%Y-%m-%d %H:%M:%S') ==="

# Activate virtualenv
if [[ -f "$VENV/bin/activate" ]]; then
    source "$VENV/bin/activate"
else
    echo "ERROR: venv not found at $VENV — run 'python -m venv .venv && pip install -r requirements.txt'"
    exit 1
fi

# Start Ollama if not already running
if ! pgrep -x ollama > /dev/null 2>&1; then
    echo "Starting Ollama..."
    nohup ollama serve > /dev/null 2>&1 &
    sleep 8
else
    echo "Ollama already running."
fi

# Run pipeline — caffeinate -i (prevent idle sleep) + -s (prevent system sleep on AC)
echo "Starting pipeline..."
caffeinate -is python -m orchestrator.pipeline

echo "=== Run complete $(date '+%Y-%m-%d %H:%M:%S') ==="
