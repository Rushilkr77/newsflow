#!/bin/bash
# Daily LinkedIn-post brief — invoked by launchd (com.newsflow.post.plist).
# Phase A (ingest + dedup + scrape) is idempotent, so this is safe alongside daily_run.sh.
# Output: workspace/post/<date>/brief.md — consumed by the /newsflow-post Claude skill.
set -euo pipefail

REPO="/Users/rushilkr/Projects/newsflow"
TODAY="$(date +%Y-%m-%d)"

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$REPO"
mkdir -p "$REPO/workspace"
exec >> "$REPO/workspace/launchd_post_${TODAY}.log" 2>&1
echo "=== NewsFlow post run $(date '+%Y-%m-%d %H:%M:%S') ==="

source "$REPO/venv/bin/activate"
if [[ -f "$REPO/.env" ]]; then
    set -o allexport
    source "$REPO/.env"
    set +o allexport
fi

# caffeinate: keep the Mac awake for the run
caffeinate -i python -m orchestrator.pipeline --phase global --date "$TODAY"
caffeinate -i python -m orchestrator.pipeline --mode post --date "$TODAY"
