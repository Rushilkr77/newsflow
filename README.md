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

**End-to-end, fully automated — zero manual steps after setup.**

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

**Multi-agent architecture.** Each stage runs as an isolated agent with a typed Pydantic contract, a checkpoint file, and structured logs, so a failed stage reruns without reprocessing everything before it.

**LLM fallback chain.** Calls route through OpenRouter's free-tier models in sequence — gpt-oss-120b, hermes-405b, llama-70b, gemma-31b. A model that 404s or hits its daily limit gets blacklisted for the session after one failure, so retries stop hitting a dead model.

**Deduplication.** URL matching catches exact repeats first; semantic similarity via `all-MiniLM-L6-v2` embeddings catches the rest. Sources overlap 30–40% day to day, and this keeps unique coverage intact.

**Per-source parsers.** TLDR, TechCrunch, ETtech, ET AI, and Harper's Carroll each get a dedicated parser tuned to their HTML structure, plus variant detection for A/B subject lines.

**Grounding check.** The script writer checks every numeric claim — dollar amounts, percentages — against the source summaries, and regenerates a segment if it finds 3 or more unmatched facts.

**SSML prosody.** Scripts use `<prosody>`, `<emphasis>`, `<break>`, and `<say-as>` tags instead of flat text, and markdown artifacts from the LLM get stripped before synthesis.

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

I'm transitioning from SDE to AI PM, and keeping up with AI news across multiple newsletters was eating 1–2 hours a day. Building this instead gave me a real problem to apply engineering skills to: orchestrating LLM calls, writing prompts that hold up against newsletter noise, and getting an agent pipeline to run unattended every morning.
