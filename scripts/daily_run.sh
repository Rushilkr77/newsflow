#!/bin/bash
# Daily NewsFlow pipeline wrapper — invoked by launchd every 10 minutes.
# Queries Supabase for active users whose delivery window has started, runs
# per-user pipeline if no episode exists for today yet.
# caffeinate prevents idle sleep mid-run.
set -euo pipefail

REPO="/Users/rushilkr/Projects/newsflow"
VENV="$REPO/venv"
TODAY="$(date +%Y-%m-%d)"

# launchd exports a minimal PATH
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

cd "$REPO"

LOG="$REPO/workspace/launchd_${TODAY}.log"
mkdir -p "$REPO/workspace"

exec >> "$LOG" 2>&1
echo "=== NewsFlow tick $(date '+%Y-%m-%d %H:%M:%S') ==="

# Activate virtualenv
if [[ -f "$VENV/bin/activate" ]]; then
    source "$VENV/bin/activate"
else
    echo "ERROR: venv not found at $VENV"
    exit 1
fi

# Load env vars from .env (Supabase keys needed for user query below)
if [[ -f "$REPO/.env" ]]; then
    set -o allexport
    source "$REPO/.env"
    set +o allexport
fi

# Query active users whose pipeline start window has arrived:
#   pipeline_start = delivery_local_time - 30min
#   fire when: now_local >= pipeline_start AND no episode for today yet
USERS=$(python3 - <<'PYEOF'
import os, json
from datetime import datetime, timedelta
import pytz

try:
    from supabase import create_client
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("[]")
        raise SystemExit(0)

    db = create_client(url, key)
    today = datetime.now(pytz.utc).strftime("%Y-%m-%d")

    users = db.table("users").select("id, delivery_local_time, tz").eq("active", True).eq("episode_generation_enabled", True).execute().data
    ready = []
    for u in users:
        tz = pytz.timezone(u.get("tz") or "Asia/Kolkata")
        now_local = datetime.now(tz)
        delivery_str = u.get("delivery_local_time") or "07:00"
        hh, mm = map(int, delivery_str.split(":"))
        delivery_dt = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        pipeline_start = delivery_dt - timedelta(minutes=30)

        if now_local < pipeline_start:
            continue  # not yet

        # Check if episode already exists for today
        ep_result = db.table("episodes").select("id, status").eq("user_id", u["id"]).eq("date", today).limit(1).execute()
        if ep_result.data and ep_result.data[0].get("status") not in ("failed",):
            continue  # already done (or in progress)

        ready.append(u["id"])

    print(json.dumps(ready))
except Exception as e:
    import sys
    print(f"User query failed: {e}", file=sys.stderr)
    print("[]")
PYEOF
)

if [[ "$USERS" == "[]" || -z "$USERS" ]]; then
    echo "No users ready to run. Exiting."
    exit 0
fi

echo "Users to run: $USERS"

# Run pipeline per user
USERS_JSON="$USERS" REPO="$REPO" python3 -c "
import sys, json, subprocess, os, datetime
from supabase import create_client
url = os.environ.get('NEXT_PUBLIC_SUPABASE_URL') or os.environ.get('SUPABASE_URL', '')
key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
db = create_client(url, key)
today = datetime.date.today().isoformat()

# Reset episodes stuck in 'generating' for more than 3 hours — pipeline died before status update.
from datetime import timezone
cutoff = (datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=3)).isoformat()
stale = db.table('episodes').select('user_id').eq('date', today).eq('status', 'generating').lt('created_at', cutoff).execute()
for row in (stale.data or []):
    db.table('episodes').update({'status': 'failed'}).eq('user_id', row['user_id']).eq('date', today).execute()
    print(f'Reset stale generating episode for user {row[\"user_id\"]}')

user_ids = json.loads(os.environ.get('USERS_JSON', '[]'))
PIPELINE_TIMEOUT_SEC = 7200  # 2 hours max per user pipeline

for uid in user_ids:
    print(f'Starting pipeline for user {uid}...')
    db.table('episodes').upsert({'user_id': uid, 'date': today, 'status': 'generating'}, on_conflict='user_id,date').execute()
    try:
        result = subprocess.run(
            ['caffeinate', '-dimsu', sys.executable, '-m', 'orchestrator.pipeline', '--user-id', uid],
            cwd=os.environ.get('REPO', '.'),
            timeout=PIPELINE_TIMEOUT_SEC,
        )
        status = 'ready' if result.returncode == 0 else 'failed'
        msg = 'Pipeline complete' if result.returncode == 0 else f'Pipeline FAILED (exit {result.returncode})'
    except subprocess.TimeoutExpired:
        status = 'failed'
        msg = f'Pipeline TIMEOUT after {PIPELINE_TIMEOUT_SEC // 60}min'
    db.table('episodes').update({'status': status}).eq('user_id', uid).eq('date', today).execute()
    print(f'{msg} for user {uid}')
"

echo "=== Tick complete $(date '+%Y-%m-%d %H:%M:%S') ==="
