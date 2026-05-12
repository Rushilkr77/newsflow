---
name: newsflow-debug
description: Use this skill to diagnose and fix NewsFlow pipeline errors. Activate when the user reports an exception, traceback, or error message from any pipeline script (script_writer.py, curator.py, ingestion.py, audio_producer.py, etc.), or when a pipeline stage produced wrong/missing output. This includes: LLM producing malformed JSON, retries failing, missing checkpoint files, unexpected article counts, truncated output, or any runtime error during a pipeline run. Do NOT activate for: reviewing output quality, explaining how the pipeline works, changing configuration/preferences, or fixing parser logic for a specific source.
---

# NewsFlow: Pipeline Debugger

Diagnose failures by reading checkpoint files in order. Never guess — always read the actual data.

## Step 1 — Identify the date

If not specified, default to today. Workspace: `workspace/{date}/`.

## Step 2 — Map what completed vs. what's missing

Check which checkpoint files exist in `workspace/{date}/`:

| File | Stage | If missing |
|------|-------|-----------|
| `raw_articles.json` | Ingestion | Ingestion failed or never ran |
| `curated_articles.json` | Curator | Curator failed |
| `curated_articles_enriched.json` | Article scraper | Scraper failed (non-fatal — may be partial) |
| `summaries.json` | Summarizer | Summarizer failed |
| `podcast_script.json` | Script Writer | Script Writer failed |
| `logs/validation_report.json` | Script Validator | Validator not reached or failed silently |
| `logs/tighten_diff.json` | Tighten pass | Episode was under 50 min — expected absence |
| `episode_metadata.json` | Audio Producer | Audio failed |
| `episode_*.mp3` | Audio Producer | MP3 not produced |

Read the files that DO exist to understand what data made it through.

## Step 3 — Diagnose by stage

### Ingestion failures (`raw_articles.json` missing or near-empty)
- Read `agents/ingestion.py` — check Gmail query and parser registry
- Check if `.env` has valid credentials (`GMAIL_CREDENTIALS_PATH`, `GMAIL_TOKEN_PATH`)
- Count articles per source in `raw_articles.json` — which sources produced 0?
- Common failures:
  - `want_plain=True` missing for harper_carroll → HTML body passed to plain-text parser
  - Gmail OAuth token expired → look for 401 in logs
  - Parser exception → one source fails silently, others succeed
  - CP1252 encoding crash on emoji in TLDR subject → check `sys.stdout` reconfiguration in pipeline.py

### Curation failures (`curated_articles.json` missing or all P3)
- Read the raw articles — were they actually parsed correctly (non-empty snippets, valid URLs)?
- Check `agents/curator.py` — look at the LLM classification prompt and model
- If all articles are P3: the curator prompt may be misclassifying — check `config/preferences.yaml` priority rules
- Count breakdown: how many P0/P1/P2/P3? If P3 count is >50%, the classifier is broken

### Scraper failures (`curated_articles_enriched.json` has null full_text)

**Ground-truth check first** — read `curated_articles_enriched.json` and categorise every P0/P1 article:
```python
import json
arts = json.load(open('workspace/{date}/curated_articles_enriched.json'))
for a in arts:
    if a.get('priority') not in ('P0','P1'): continue
    ft = a.get('full_text') or ''
    status = 'scraped' if len(ft)>500 else ('thin' if len(ft)>150 else 'SNIPPET-ONLY')
    print(f"{a['priority']} {status:12} [{a['source']:15}] {a['title'][:60]}")
```

**Log-based fetch trace** — parse `pipeline.log` for per-article fetch events:
- `article_fetched` → primary trafilatura/newspaper3k succeeded
- `inc42_fallback_used` → ET paywall bypassed via Inc42 ✓
- `inc42_no_result` → Inc42 didn't have the story
- `inc42_text_too_short` → Inc42 found page but extracted <150 chars (category page / stub)
- `inc42_error` → Inc42 request failed (timeout, parse error)
- `ddg_fallback_used` → DuckDuckGo found alternative source ✓
- `ddg_no_result` / `ddg_search_error` → DDG also failed
- `fetch_fallback_to_snippet` → **ALL scraping failed** — article summarised from email snippet only

**Diagnose by failure pattern:**

| Pattern | Root cause | Fix |
|---|---|---|
| Only ET/ETtech articles snippet-only | Inc42 + DDG both missed | Check Inc42 search URL manually; add story keywords to DDG query |
| All sources snippet-only (>30%) | trafilatura broken / rate-limited | Check `requests` version; try `USE_TRAFILATURA_FRESH_DOWNLOAD=true` |
| `inc42_text_too_short` on every ET article | Inc42 returning category page not article | Review `_VALID_PATH_SEGMENTS` in `scraper/inc42_scraper.py` |
| `ddg_search_error` | DDGS rate limit or network | Retry next run; DDGS has daily limits |
| thin scrape (150-500 chars) for non-ET | Paywall stub returned as valid | Lower `_MIN_CHARS` threshold won't help — need cookie/session |

**Cross-reference thin content impact on summaries:**
For each snippet-only P0, read its entry in `summaries.json` and check:
- `summary_text` word count < 200 → thin summary — will produce weak script narration
- Section header count < 4 → P0 summarizer retry may have also failed
- Flag: `CRITICAL — {title} is P0 snippet-only with thin summary`

### Summarizer failures (`summaries.json` missing or truncated)
- Check article count: should be roughly same as curated (P0+P1+P2)
- If count drops dramatically: LLM producing empty output or exception mid-batch
- Word count violations (P0 summaries <100 words): prompt not being followed → log a prompt-tuning issue
- **P0 structured header check**: count section headers in `summary_text` — a correct P0 summary has 6 headers (`CORE NEWS`, `SURROUNDING IMPACT`, `COMPETITOR CONTEXT`, `LAUNCH RATIONALE`, `HOW IT WORKS`, `PM INTERVIEW EDGE`). Fewer than 4 means the summarizer was cut short (token budget too tight or scraping returned too little content). P1 should have 3 (`CORE NEWS + IMPACT`, `HOW + WHY`, `PM EDGE`); P2 should have 2 (`CORE NEWS`, `PM EDGE`).

### Script Writer failures (`podcast_script.json` missing or malformed)
**Coverage signal warning**: `source_article_ids` on a segment records what was *fed into the LLM*, not what was actually narrated. Do **not** use it to determine whether an article was covered. The real coverage check is to search the article's title keywords in `content_plain` of the relevant segments.

**Segment list change**: cold_open and intro are replaced by a single `opener` segment. If you see `cold_open` or `intro` in a new script, the code change was not picked up (check for stale `.pyc` or a checkpoint from an old run).

**Log events to search for in `pipeline.log`**:
- `coverage_gaps_detected` — P0 article not found in narration; expansion triggered
- `expansion_minimal_gain` — expansion ran but episode was already adequate length
- `script_validation_offenders` — validator found article in 2+ deep segments
- `validation_regenerate` — validator regenerated a segment with exclusions
- `validation_converged` — dedup resolved within max_iterations
- `validation_did_not_converge` — still had duplicates after max_iterations (log offender article IDs)
- `tighten_pass_applied` — episode exceeded 50 min, P1/P2 compressed
- `opener_overlength_retry` — opener exceeded 50s, regenerated with tighter budget

**Common JSON issues:**
- Unescaped control chars → `_clean_json()` should catch
- SSML `<break time="500ms"/>` producing `\<` escape → check invalid-escape fixer
- Response truncated mid-JSON → `_extract_first_object()` should handle
- If all 5 retries fail: summaries input may be too long — check token budget

### Script Validator failures (`validation_report.json` missing or converged=false)
- `logs/validation_report.json` missing: validator threw an unhandled exception — check pipeline.log for traceback
- `final_offender_count > 0` after 2 iterations: suspect one of:
  - (a) LLM ignored `excluded_article_ids` — try increasing exclusion list clarity in prompt
  - (b) Same article has multiple `article_id` aliases (dedup didn't merge them in curator)
  - (c) Validator false-positive: article appears in source_article_ids of two segments but was only narrated in one — check content_plain manually

### Audio cleanup failures
- `audio_cleanup_fallback` in logs: `noisereduce` not installed — run `pip install noisereduce>=3.0`
- Static still present after cleanup: increase `cleanup.noise_reduce_prop` (0.75 → 0.85) in `config/tts_config.yaml`
- `audio_cleanup_disabled`: cleanup.enabled=false in config — set to true

### Long-pause regressions (pauses still >3 seconds)
If pauses still feel long after the silence-trim fix:
- Verify `silence_between_articles_ms` resolved to 150ms not 800ms (check tts_config.yaml loaded correctly; look for `tts_config_load_failed` in logs)
- Check `_trim_silence` applied: audio_producer.py wraps each synth chunk with trim call; confirm that code path was reached
- Chatterbox model itself may emit long inter-word silences: try reducing `exaggeration` in tts_config.yaml (0.7 → 0.5)

### Audio failures (`episode_*.mp3` missing)
- Read `agents/audio_producer.py` — check `_ensure_ffmpeg()` auto-discovery
- ffmpeg path: `AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*` — verify it exists
- TTS failure: gTTS requires internet; Chatterbox requires HuggingFace access
- Audio cleanup chain order: `_trim_silence` → `_clean_audio` → join chunks → `_normalize_loudness` → export. If cleanup breaks, check noisereduce import.
- `pydub.AudioSegment.high_pass_filter` not available: ensure pydub version >=0.25

## Step 4 — Report findings

Summarize:
1. Which stages completed successfully (with article counts)
2. Where the pipeline stopped
3. The specific failure mode (exact log event or exception)
4. A targeted fix (code change, config change, or environment fix)

Do not suggest broad rewrites. Find the exact line that failed.

## Quick Commands

```bash
# Re-run pipeline (checkpoints skip completed stages)
source venv/bin/activate && python -m orchestrator.pipeline --date 2026-05-09

# Force re-scrape + re-summarize (delete checkpoints first)
rm workspace/{date}/curated_articles_enriched.json workspace/{date}/summaries.json

# Full scraping + fetch observability report
python -c "
import json
arts = json.load(open('workspace/{date}/curated_articles_enriched.json'))
p0p1 = [a for a in arts if a.get('priority') in ('P0','P1')]
for a in sorted(p0p1, key=lambda x: x['priority']):
    ft = a.get('full_text') or ''
    status = 'scraped' if len(ft)>500 else ('thin' if len(ft)>150 else 'SNIPPET-ONLY')
    print(f\"{a['priority']} {status:12} [{a['source']:15}] {len(ft):5} chars  {a['title'][:55]}\")
"

# Check pipeline log for all fetch events (scraping observability)
grep -E "article_fetched|inc42_fallback|inc42_no_result|inc42_error|ddg_fallback|ddg_no_result|fetch_fallback_to_snippet" workspace/{date}/logs/pipeline.log

# Check validation report
python -c "import json; r = json.load(open('workspace/{date}/logs/validation_report.json')); print(f'Converged: {r[\"converged\"]}, Offenders: {r[\"final_offender_count\"]}')"

# Check pipeline log for all key events
grep -E "coverage_gaps_detected|validation_offenders|validation_converge|audio_cleanup|tighten_pass|fetch_fallback" workspace/{date}/logs/pipeline.log
```
