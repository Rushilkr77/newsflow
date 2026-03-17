---
name: newsflow-debug
description: Diagnose NewsFlow pipeline failures and bad outputs. Activate when the user says "pipeline failed", "debug", "something's wrong", "0 articles", "nothing scraped", "bad output", "broken", or describes unexpected results from any pipeline stage.
---

# NewsFlow: Pipeline Debugger

Diagnose failures by reading checkpoint files in order. Never guess — always read the actual data.

## Step 1 — Identify the date

If the user didn't specify a date, default to today (`2026-03-14`). The workspace is at `workspace/{date}/`.

## Step 2 — Map what completed vs. what's missing

Check which checkpoint files exist in `workspace/{date}/`:

| File | Stage | If missing |
|------|-------|-----------|
| `raw_articles.json` | Ingestion | Ingestion failed or never ran |
| `curated_articles.json` | Curator | Curator failed |
| `curated_articles_enriched.json` | Article scraper | Scraper failed (non-fatal — may be partial) |
| `summaries.json` | Summarizer | Summarizer failed |
| `podcast_script.json` | Script Writer | Script Writer failed |
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
- If using local model: is Ollama running? `ollama list` to check qwen2.5:3b is available
- If all articles are P3: the curator prompt may be misclassifying — check `config/preferences.yaml` priority rules
- Count breakdown: how many P0/P1/P2/P3? If P3 count is >50%, the classifier is broken

### Scraper failures (`curated_articles_enriched.json` has null full_text)
- This is expected for paywalled articles (ET, ETtech) — check if it's only those sources
- Count articles where `full_text is null` — if >70%, general scraping is broken
- Common: requests timeout, trafilatura returning None, newspaper3k import error
- Check `scraper/article_scraper.py` — is the 10s timeout too short?

### Summarizer failures (`summaries.json` missing or truncated)
- Check article count: should be roughly same as curated (P0+P1+P2)
- If count drops dramatically: LLM producing empty output or exception mid-batch
- If using qwen2.5:7b with CPU offload: may be timing out — check model output
- Word count violations (P0 summaries <100 words): prompt not being followed → log a prompt-tuning issue

### Script Writer failures (`podcast_script.json` missing or malformed)
- This is the most fragile stage when using llama3.2:3b
- Read `agents/script_writer.py` — check `_clean_json()` and `_MAX_RETRIES`
- Common JSON issues:
  - Unescaped control chars in strings → `_clean_json()` should catch this
  - SSML `<break time="500ms"/>` producing `\<` escape → check the invalid-escape fixer
  - Response truncated mid-JSON → `_extract_first_object()` should handle
  - If all 5 retries fail: the summaries input may be too long — check token budget
- If using Anthropic API fallback: check ANTHROPIC_API_KEY in .env

### Audio failures (`episode_*.mp3` missing)
- Read `agents/audio_producer.py` — check `_ensure_ffmpeg()` auto-discovery
- ffmpeg path: `AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*` — verify it exists
- TTS failure: gTTS requires internet; Chatterbox requires HuggingFace access
- pydub AudioSegment error: usually means a TTS chunk returned silence or wrong format

## Step 4 — Report findings

Summarize:
1. Which stages completed successfully (with article counts)
2. Where the pipeline stopped
3. The specific failure mode
4. A targeted fix (code change, config change, or environment fix)

Do not suggest broad rewrites. Find the exact line that failed.

## Quick Commands

```bash
# Re-run a specific stage only (checkpoints skip completed stages)
python -m orchestrator.pipeline --date 2026-03-14

# Check Ollama models
ollama list

# Verify ffmpeg
where ffmpeg  # or check AppData path

# Validate a checkpoint file
python -c "import json; d = json.load(open('workspace/2026-03-14/raw_articles.json')); print(f'{len(d)} articles'); print({a['source'] for a in d})"
```
