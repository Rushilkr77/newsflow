---
name: newsflow-review
description: Review today's NewsFlow pipeline output quality against DESIGN.md targets. Activate when the user says "review today's output", "check quality", "how did the pipeline do", "quality check", "review the episode", "check summaries", "how many articles", or asks about episode quality metrics.
---

# NewsFlow: Output Quality Reviewer

Read the actual checkpoint files. Report numbers. Flag violations. Do not guess.

## Step 1 — Identify the date

If not specified, use today (`2026-03-14`). Workspace: `workspace/{date}/`.

## Step 2 — Article funnel report

Read these files in order and report counts at each stage:

| Checkpoint | Read | Report |
|-----------|------|--------|
| `raw_articles.json` | Count total + count per source | "X articles from Y sources" |
| `curated_articles.json` | Count P0/P1/P2/P3 per category | Priority breakdown table |
| `curated_articles_enriched.json` | Count where full_text is not null | "X of Y articles scraped successfully" |
| `summaries.json` | Count total summaries | Should match P0+P1+P2 count |
| `podcast_script.json` | Count segments, total_estimated_duration_min | Duration vs 60-90 min target |

**Expected funnel** (from DESIGN.md):
- Raw: 60-80 articles
- Curated: 25-35 articles (P0: ≤6, P1: ≤12, P2: ≤15)
- Scraper success: >60% of P0+P1 articles
- Summaries: same count as curated P0+P1+P2
- Episode: 60-90 minutes

Flag any stage where numbers fall outside expected range.

## Step 3 — Summary quality spot-check

From `summaries.json`, pick:
- 1 random P0 article (deep dive)
- 1 random P1 article (standard)
- 1 random P2 article (quick hit)

For each, report:
- Word count of `summary_text`
- Count of `key_takeaways`
- Count of `discussion_points`
- Flag violations:

| Priority | Target words | Min takeaways | Min discussion points |
|---------|-------------|---------------|----------------------|
| P0 | 300-500 | 3 | 1 |
| P1 | 100-200 | 2 | 1 |
| P2 | 30-50 | 1 | 0 |

Also check: does the summary sound like it was written for ears (short sentences, no bullet points in the text itself)?

## Step 4 — Script quality check

From `podcast_script.json`, check:

1. **Duration**: `total_estimated_duration_min` — flag if outside 60-90 min
2. **Segment coverage**: Are all expected segment types present?
   - Required: `cold_open`, `intro`, `ai_updates`, `closing`
   - Expected: at least 3 of `funding_ma`, `india_tech`, `product_strategy`, `quick_hits`
3. **Discussion hooks**: Count `top_takeaways` — target is 3
4. **SSML check**: Sample `content_ssml` from the `ai_updates` segment — does it contain `<break` tags? Does `content_plain` exist and differ from SSML?
5. **Cold open quality**: Read the `cold_open` segment — does it hook with a specific story, or is it generic?

## Step 5 — Source coverage check

From `curated_articles.json`, verify each enabled source contributed at least 1 article:
- `tldr_ai` — expected daily
- `tldr_tech` — expected daily
- `tldr_dev` — expected daily
- `techcrunch` — expected daily (may appear as morning + afternoon edition)
- `harper_carroll` — weekly (Wed/Thu only; skip check Mon/Tue/Fri)

If any daily source has 0 articles, flag it as a likely parser or Gmail fetch issue.

## Step 6 — Output the quality report

Format:
```
## NewsFlow Quality Report — {date}

### Article Funnel
Raw: X | Curated: X (P0:X P1:X P2:X P3:X) | Scraped: X/Y | Summaries: X | Duration: X min

### Source Coverage
✓ tldr_ai: X articles
✓ techcrunch: X articles
✗ harper_carroll: 0 articles ← ISSUE

### Summary Quality (spot-check)
P0 "{title}": 342 words ✓, 3 takeaways ✓, 1 discussion point ✓
P1 "{title}": 87 words ✗ (target 100-200)
P2 "{title}": 41 words ✓

### Script Quality
Duration: 78 min ✓
Segments: cold_open ✓ intro ✓ ai_updates ✓ funding_ma ✓ india_tech ✗ product_strategy ✓ quick_hits ✓ closing ✓
Top takeaways: 3 ✓
SSML present: ✓

### Issues Found
1. harper_carroll: 0 articles (is today Wed/Thu? if yes, investigate parser)
2. P1 summary word count too low: 87 words for "{title}"

### Overall: PASS / NEEDS ATTENTION / FAIL
```

## Quick Dedup Check (bonus)

If there are articles with very similar titles in `curated_articles.json`, check `dedup_group_id` — if two articles about the same story both appear in P0/P1 without a shared group_id, dedup may have missed them. Report the pair if found.
