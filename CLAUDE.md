# NewsFlow AI

Multi-agent pipeline that transforms daily email newsletters into a single-host AI-narrated podcast (~60-90 min), delivered every morning.

## What This Project Does

1. Fetches newsletters from Gmail (7 sources, 4 sender addresses)
2. Parses email HTML → extracts article URLs and snippets
3. Scrapes full article content from URLs (not just email snippets)
4. Deduplicates across sources (30-40% overlap observed)
5. Classifies & ranks articles for an SDE→AI PM career transition
6. Generates tiered summaries grouped by topic
7. Writes a conversational podcast script with SSML
8. Produces a final MP3 via TTS

## User Context

- **User**: Rushil (rushilmisc77@gmail.com)
- **Use case**: Listen during gym sessions, stay current on AI/tech for PM interviews
- **Location**: India (IST timezone)
- **Schedule**: Pipeline runs at 5:00 AM IST daily

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Email | Gmail API (OAuth 2.0) — direct API, NOT MCP |
| HTML Parsing | BeautifulSoup4 + lxml |
| Article Scraping | trafilatura (primary), newspaper3k (fallback) |
| Embeddings (Dedup) | sentence-transformers/all-MiniLM-L6-v2 (local, free) |
| LLM (Classification) | Claude Haiku 4.5 via Anthropic API |
| LLM (Summarization) | Claude Sonnet 4.5 via Anthropic API |
| LLM (Script Writing) | Claude Sonnet 4.5 via Anthropic API |
| TTS (Primary) | Chatterbox TTS via HuggingFace (free) |
| TTS (Fallback) | ElevenLabs API (paid, higher quality) |
| Audio Processing | pydub + ffmpeg |
| Data Validation | Pydantic v2 |
| Scheduling | APScheduler / cron |
| Delivery | Podcast RSS feed + Telegram bot |

## Project Structure

```
newsflow-ai/
├── CLAUDE.md                     # This file
├── docs/
│   └── DESIGN.md                 # Detailed implementation spec (READ THIS)
├── config/
│   ├── senders.yaml              # Newsletter sender whitelist + variant rules
│   ├── preferences.yaml          # Priority matrix + scoring weights
│   └── tts_config.yaml           # Voice settings, fallback config
├── agents/
│   ├── ingestion.py              # Gmail fetch + HTML parsing + variant detection
│   ├── curator.py                # Dedup + classification + ranking
│   ├── summarizer.py             # Tiered summarization + topic clustering
│   ├── script_writer.py          # Podcast script generation + SSML
│   └── audio_producer.py         # TTS + audio processing + delivery
├── parsers/
│   ├── base_parser.py            # Abstract base class for all parsers
│   ├── tldr_parser.py            # TLDR newsletter HTML parser (AI, Tech, Dev)
│   ├── techcrunch_parser.py      # TechCrunch Top 3 + Must-Reads parser
│   ├── harper_carroll_parser.py  # Weekly digest section parser
│   ├── ettech_parser.py          # ETtech Top 5 parser
│   └── et_ai_parser.py           # ET AI daily parser
├── scraper/
│   ├── article_scraper.py        # Full article content fetcher
│   └── content_cleaner.py        # Strip ads, nav, extract article body
├── orchestrator/
│   ├── pipeline.py               # Sequential pipeline runner with checkpoints
│   └── scheduler.py              # Cron/APScheduler config (5 AM IST)
├── models/
│   ├── article.py                # Pydantic: RawArticle, CuratedArticle
│   ├── podcast.py                # Pydantic: PodcastScript, Segment, Episode
│   └── enums.py                  # Priority, Source, Category enums
├── evals/
│   ├── curator_eval.py           # Relevance accuracy tests
│   ├── summarizer_eval.py        # Factual accuracy checks
│   └── e2e_eval.py               # End-to-end pipeline tests
├── delivery/
│   ├── rss_feed.py               # Podcast RSS generator
│   └── telegram_bot.py           # Notification + feedback bot
├── workspace/                    # Daily pipeline outputs (gitignored)
├── tests/
│   ├── test_parsers/
│   ├── test_agents/
│   └── fixtures/                 # Sample email HTML for testing
├── .env                          # API keys (NEVER commit)
├── .gitignore
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Coding Conventions

- Type hints on all function signatures
- Pydantic v2 models for all data contracts between agents
- Each agent is a class with a `run()` method that reads input JSON and writes output JSON
- Checkpoint files saved to `workspace/{date}/` after each agent completes
- Logging via `structlog` — every agent logs article counts, timing, errors
- Config loaded from YAML files, secrets from .env
- Tests use pytest with fixtures from `tests/fixtures/` (sample email HTML)

## Implementation Order

Build and test in this order (see docs/DESIGN.md for details):

1. **Phase 1 (Week 1-2)**: Models → Config → Parsers → Ingestion Agent → basic Curator → basic Summarizer → gTTS test
2. **Phase 2 (Week 3-4)**: Article scraper → semantic dedup → Script Writer → Chatterbox TTS → audio pipeline
3. **Phase 3 (Week 5-6)**: Scheduler → RSS feed → Telegram bot → monitoring
4. **Phase 4 (Week 7+)**: Feedback loop → trend detection → weekend digest mode

Always start a new agent by reading the relevant section in docs/DESIGN.md first.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes � gives risk-scored analysis |
| `get_review_context` | Need source snippets for review � token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
