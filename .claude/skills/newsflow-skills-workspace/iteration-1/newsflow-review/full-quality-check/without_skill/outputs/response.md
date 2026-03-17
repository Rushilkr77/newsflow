# WITHOUT SKILL Baseline: Full Quality Review

## NewsFlow Pipeline Quality Assessment — 2026-03-12 | Overall: 3/10

### Stage 1 — Ingestion (37 articles, Score: 5/10)
- HIGH: Section headers bleeding into titles (e.g. "TechCrunch Top 3 Former Apple engineer raises $5M...")
- HIGH: TLDR ALL-CAPS titles are section headings, not article titles (TTS will shout them)
- MEDIUM: Stub titles: "STEERING", "COMPANY", "MULTI-CLOUD DEAL"
- MEDIUM: full_text null for all articles

### Stage 2 — Curation (24 articles, Score: 4/10)
- HIGH: No dedup fired at all — every article has dedup_group_id: null
- HIGH: Priority/score inconsistency — "COMPANY" (YouTube stub) rated P0 at 95; "RELIC JAVA AGENT" P2 at 85
- MEDIUM: Discussion hooks mismatched to articles (off-by-one indexing bug in curator.py)
- MEDIUM: Pokemon Pokopia game review rated P1 with no AI angle

### Stage 3 — Summarization (24 articles, Score: 5/10)
- HIGH: Hallucination — Gemini Chrome India summary invents "Nano Banana 2 generative AI tool"
- MEDIUM: Markdown ** artifacts in key_takeaways (TTS will read them)
- MEDIUM: Pokemon key_takeaways is just "**" — empty
- P2 summaries extremely thin (17-39 words)

### Stage 4 — Script Writing (12 min vs 60-90 target, Score: 2/10)
- CRITICAL: 12 min episode (target 60-90)
- CRITICAL: Funding segment fabricates "$150M fintech investment", "Microsoft acquires AI cybersecurity co", "Google-NVIDIA partnership", "IBM AI hybrid cloud platform" — none in source articles
- CRITICAL: Cold open entirely fabricated — "AI security vulnerability affecting 90% of server admins" doesn't exist in sources
- HIGH: india_tech invents Niti Aayog ed-tech stats — no India articles ingested
- HIGH: Closing references "NovaSparks" company — fabricated
- HIGH: Broken SSML — non-self-closing break, <a href> in SSML, <audio-container> hallucination
- MEDIUM: source_article_ids uses "article_id_1" placeholders in 4/8 segments

### Top Fixes Recommended
1. Hallucination guard in script writer — "Only include events from provided summaries. Never invent news."
2. Generate per-article content blocks (not per-category)
3. SSML validation before sending to TTS
4. TechCrunch title prefix-stripping
5. TLDR title normalization
6. Semantic dedup verification
7. Gate india_tech segment on whether india-tagged articles exist

### Summary Table
| Stage | In | Out | Score |
|---|---|---|---|
| Ingestion | — | 37 | 5/10 |
| Curation | 37 | 24 | 4/10 |
| Summarization | 24 | 24 | 5/10 |
| Script | 24 | 12 min | 2/10 |
| Overall | | | 3/10 |

## Assertions check
1. Reads raw_articles.json + count per source: PARTIAL — total count only, no per-source breakdown ✗
2. Reports P0/P1/P2/P3 breakdown: NOT explicitly stated ✗
3. Checks summary word count: NOT explicitly checked ✗
4. Reports total_estimated_duration_min: ✓ (12 min stated)
5. Structured PASS/FAIL rating: PARTIAL — gives 3/10 per stage but not PASS/NEEDS ATTENTION/FAIL ✗

## Notable findings vs. with-skill
- DEEPER: Found discussion hook off-by-one bug in curator.py
- DEEPER: Found Pokemon game article slipped through curation
- DEEPER: Identified specific fabricated news items in funding segment
- MISSING: No per-source article count table
- MISSING: No explicit P0/P1/P2 word count table
- MISSING: No source coverage check (which sources had 0 articles)

## Metrics
- Tool calls: ~8 (per task summary — Read=4, Bash=1, others)
- Errors: Write/Bash to workspace denied
