# NewsFlow AI

An autonomous multi-agent pipeline that ingests daily tech newsletters from Gmail, deduplicates and ranks articles using LLMs, writes a conversational podcast script, and synthesizes a narrated MP3 — delivered to your inbox every morning before you wake up.

> Built to solve a personal problem: staying current on AI/tech without spending 2 hours reading newsletters. The output is a ~45-minute podcast, ready at 10 AM IST.

---

## What It Does

```
Gmail (newsletters) → Parse → Scrape → Deduplicate → Classify & Rank
                                                            ↓
                                          MP3 → TTS ← Script ← Summarize
                                           ↓
                              Google Drive + Email delivery
```

**End-to-end, fully automated. Zero manual steps after setup.**

---

## Pipeline Stages

| Stage | What happens |
|---|---|
| **Ingestion** | Fetches newsletters via Gmail API, detects sender variants, parses HTML per source |
| **Scraping** | Fetches full article text (trafilatura → newspaper3k → DDG fallback) |
| **Curation** | Semantic dedup with sentence-transformers, LLM classification, priority scoring |
| **Summarization** | Tiered summaries (P0 deep-dive / P1 standard / P2 brief) per article |
| **Script Writing** | Conversational podcast script with SSML prosody, grouped by topic |
| **Audio** | Google Cloud Neural2 TTS → pydub stitching → final MP3 |
| **Delivery** | Upload to Google Drive, send email with link + quality report |

---

## Technical Highlights

**Multi-agent architecture** — each stage is an isolated agent with a typed Pydantic contract, checkpoint file, and structured logs. A failed stage can be re-run without reprocessing earlier stages.

**Resilient LLM fallback chain** — calls route through OpenRouter free-tier models in sequence (gpt-oss-120b → hermes-405b → llama-70b → gemma-31b). Models that return 404 or hit daily limits are session-blacklisted after first failure, eliminating redundant retries.

**Smart deduplication** — URL-level dedup first, then semantic similarity via `all-MiniLM-L6-v2` embeddings. Handles 30–40% article overlap across sources without dropping unique coverage.

**Source-aware parsing** — each newsletter has a dedicated parser (TLDR, TechCrunch, ETtech, ET AI, Harper's Carroll) tuned to its HTML structure and variant detection for A/B subject lines.

**Grounding check** — script writer validates numeric claims (dollar amounts, percentages) against source summaries. Regenerates the segment if ≥3 unmatched facts detected.

**SSML audio quality** — script uses `<prosody>`, `<emphasis>`, `<break>`, and `<say-as>` tags. Markdown artifacts from LLM output are stripped before TTS synthesis.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Email | Gmail API (OAuth 2.0) |
| HTML Parsing | BeautifulSoup4 + lxml |
| Article Scraping | trafilatura, newspaper3k, DDG fallback |
| Deduplication | sentence-transformers/all-MiniLM-L6-v2 |
| LLM | OpenRouter (multi-model fallback chain) + Anthropic Claude |
| Data Validation | Pydantic v2 |
| TTS | Google Cloud Neural2 (primary), Chatterbox (fallback) |
| Audio | pydub + ffmpeg |
| Delivery | Google Drive API + Gmail SMTP |
| Scheduling | launchd (macOS) |
| Logging | structlog |

---

## Project Structure

```
agents/          # Ingestion, Curator, Summarizer, ScriptWriter, AudioProducer
parsers/         # Per-newsletter HTML parsers (TLDR, TechCrunch, ETtech, ET AI, Harper Carroll)
scraper/         # Article fetcher + content cleaner
orchestrator/    # Pipeline runner with checkpoint/recovery
delivery/        # Drive uploader + email sender
models/          # Pydantic schemas (RawArticle, CuratedArticle, PodcastScript)
config/          # senders.yaml, preferences.yaml, tts_config.yaml
workspace/       # Daily outputs (gitignored) — JSON checkpoints + logs + MP3
```

---

## Running It

```bash
# One-off run
python -m orchestrator.pipeline

# Runs automatically at 10:00 AM IST via launchd
launchctl load scripts/com.newsflow.daily.plist
```

Requires: `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, Google Cloud service account, Gmail OAuth credentials.

---

## Why I Built This

I'm transitioning from SDE to AI PM. Keeping up with the pace of AI news across multiple sources was taking 1–2 hours daily. This project let me apply engineering skills toward a real personal workflow problem — and gave me hands-on experience with LLM orchestration, prompt engineering, and agentic pipelines in a production-like setting.
