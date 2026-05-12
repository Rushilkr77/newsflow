---
name: newsflow-review
description: Review today's NewsFlow pipeline output quality against DESIGN.md targets. Activate when the user says "review today's output", "check quality", "how did the pipeline do", "quality check", "review the episode", "check summaries", "how many articles", or asks about episode quality metrics.
---

# NewsFlow: Output Quality Reviewer

Read the actual checkpoint files. Report numbers. Flag violations. Do not guess.

## Step 0 — Calibration check (run once per session)

Read `agents/script_writer.py` and find `_CHARS_PER_SEC`. Report its value.
Current expected value: **19** (calibrated for Chatterbox/ElevenLabs, 2026-05-12).
If the value differs from 19, flag it — duration estimates will be off.

## Step 1 — Identify the date

Use today's date from `currentDate` in context unless the user specifies otherwise.
Workspace: `workspace/{date}/`.

## Step 2 — Article funnel report

Read these files in order and report counts at each stage:

| Checkpoint | Read | Report |
|-----------|------|--------|
| `raw_articles.json` | Count total + count per source | "X articles from Y sources" |
| `curated_articles.json` | Count P0/P1/P2/P3 per category | Priority breakdown table |
| `curated_articles_enriched.json` | Count where full_text is not null | "X of Y articles scraped successfully" |
| `summaries.json` | Count total summaries | Should match P0+P1+P2 count |
| `podcast_script.json` | Count segments, total_estimated_duration_min | Duration vs 40-50 min target |

**Expected funnel** (from DESIGN.md):
- Raw: 60-80 articles
- Curated: 25-35 articles (P0: ≤6, P1: ≤12, P2: ≤15)
- Scraper success: >60% of P0+P1 articles
- Summaries: same count as curated P0+P1+P2
- Episode: **40-90 minutes** (from `preferences.yaml` `time_budget.target_duration_min: 90`, min: 40)

Flag any stage where numbers fall outside expected range.

## Step 2b — Content fetch quality

From `curated_articles_enriched.json`, for each P0 and P1 article classify:
- `full_text` length ≥ 500 chars → **scraped** ✓
- `full_text` length 150–499 chars → **thin** ⚠ (possible paywall stub or truncated)
- `full_text` null or < 150 chars → **snippet-only** ✗ (no article content fetched)

Report counts per priority tier:
```
P0 (N): scraped: X ✓  thin: Y ⚠  snippet-only: Z ✗
P1 (N): scraped: X ✓  thin: Y ⚠  snippet-only: Z ✗
```

For each snippet-only P0/P1 article, list: `[P0] Title (source)` — these are content gaps.

Also check `workspace/{date}/logs/3_summarization.txt` if it exists — it has per-article
content source labels ("TRAFILATURA — N chars" vs "snippet only") which map fallback chain.
Count: `primary: N | inc42: N | ddg: N | snippet-only: N` from the log if available.

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

**Structured header check** — the summarizer produces section headers in `summary_text`. Count how many are present per priority tier:

| Priority | Required headers | Min expected |
|---------|-----------------|--------------|
| P0 | CORE NEWS, SURROUNDING IMPACT, COMPETITOR CONTEXT, LAUNCH RATIONALE, HOW IT WORKS, PM INTERVIEW EDGE | 6 |
| P1 | CORE NEWS + IMPACT, HOW + WHY, PM EDGE | 3 |
| P2 | CORE NEWS, PM EDGE | 2 |

Flag any summary where the header count falls below the minimum — this indicates a token budget or scraping issue (summarizer didn't produce the full structured output).

## Step 4 — Script quality check

From `podcast_script.json`, check:

1. **Duration**: `total_estimated_duration_min` — flag if outside **40-90 min**
   - Targets from `preferences.yaml`: `target_duration_min: 90`, `min_duration_min: 40`
   - Estimated duration uses `_CHARS_PER_SEC=19` (Chatterbox/F5-TTS pace, calibrated 2026-05-12).
     At 19 chars/sec the estimate should closely match actual audio. Cross-check with
     `duration_sec` in `episode_metadata.json` (actual audio) if it exists.
2. **Segment coverage**: Are all expected segment types present?
   - Required: `cold_open`, `intro`, `ai_updates`, `closing`
   - Expected: at least 3 of `funding_ma`, `india_tech`, `product_strategy`, `quick_hits`
3. **Discussion hooks**: Count `top_takeaways` — target is 3
4. **SSML check**: Sample `content_ssml` from the `ai_updates` segment — does it contain `<break` tags? Does `content_plain` exist and differ from SSML?
5. **Cold open quality**: Read the `cold_open` segment — does it hook with a specific story, or is it generic?

**Note**: There is no tighten-pass in the current codebase. If duration exceeds 50 min, flag it as an overrun but do not look for a tighten-pass — it is not implemented.

## Step 5 — Source coverage check

From `curated_articles.json`, verify each enabled source contributed at least 1 article:
- `tldr_ai` — expected daily
- `tldr_tech` — expected daily
- `tldr_dev` — expected daily
- `techcrunch` — expected daily (may appear as morning + afternoon edition)
- `ettech` — expected daily
- `et_ai` — expected daily
- `harper_carroll` — weekly (Wed/Thu only; skip check Mon/Tue/Fri/Sat/Sun)

If any daily source has 0 articles, flag it as a likely parser or Gmail fetch issue.

## Step 5b — Expansion quality report

Check for `workspace/{date}/logs/expansion_diff.json`.

**If the file does not exist**: expansion was not triggered (episode met duration target on first pass). Report: `Expansion: not triggered`.

**If the file exists**, read it. Its structure is:

```json
{
  "pre_expansion":  { "duration_min": N, "segments": { "segment_type": { "duration_sec": N, "article_ids": [...], "char_count": N }, ... }, "gaps": { "article_id": true, ... } },
  "post_expansion": { "duration_min": N, "segments": { ... }, "gaps": { ... } },
  "summary": {
    "gaps_before": N,
    "gaps_after": N,
    "gaps_filled": ["article_id_1", ...],
    "gaps_remaining": ["article_id_2", ...],
    "duration_gain_min": N
  }
}
```

Report all of these:

1. **Duration gain**: `pre_expansion.duration_min` → `post_expansion.duration_min` (+`summary.duration_gain_min` min)
2. **Gap resolution**:
   - `summary.gaps_before` gaps before expansion → `summary.gaps_after` gaps after
   - `gaps_filled`: list article IDs that are now narrated (✓ covered by expansion)
   - `gaps_remaining`: list article IDs still uncovered — **FLAG each one** as a content gap that survived expansion
3. **Per-segment duration delta**: for each segment present in both pre and post snapshots, compute:
   - `post_expansion.segments[seg].duration_sec - pre_expansion.segments[seg].duration_sec`
   - Report as `+Ns` gain or `unchanged`
   - Flag any segment with zero delta (expansion added no content to it)
4. **Expansion quality verdict**:
   - `gaps_remaining == 0` → ✓ all articles covered after expansion
   - `gaps_remaining > 0` → ✗ ISSUE: expansion did not cover all articles; list the IDs and look up their titles in `curated_articles.json`

**Note on `gaps_remaining`**: These are articles whose titles weren't found verbatim in `content_plain` after expansion. Can be a false positive when the script paraphrases. Cross-reference against `curated_articles.json` titles to judge severity before flagging.

**Expansion trigger reason** — determine from `summary.gaps_before`:
- **Gap-driven**: `gaps_before > 0` → specific articles were missing from narration before expansion
- **Duration-driven**: `gaps_before == 0` but expansion ran → episode was short, added depth to existing coverage

## Step 6 — Output the quality report

Format:
```
## NewsFlow Quality Report — {date}

### Article Funnel
Raw: X | Curated: X (P0:X P1:X P2:X P3:X) | Summaries: X | Duration: X min

### Content Fetch Quality
Fetch source:  primary: X | inc42: X | ddg: X | snippet-only: X
P0 (N):  scraped: X ✓  thin: Y ⚠  snippet-only: Z ✗
P1 (N):  scraped: X ✓  thin: Y ⚠  snippet-only: Z ✗
[list snippet-only P0/P1 articles with source]

### Source Coverage
✓ tldr_ai: X articles
✓ techcrunch: X articles
✗ harper_carroll: 0 articles ← ISSUE

### Summary Quality (spot-check)
P0 "{title}": 342 words ✓, 3 takeaways ✓, 1 discussion point ✓
P1 "{title}": 87 words ✗ (target 100-200)
P2 "{title}": 41 words ✓

### Script Quality
Duration: 47 min ✓  (target 40-90 min)
Segments: cold_open ✓ intro ✓ ai_updates ✓ funding_ma ✓ india_tech ✗ product_strategy ✓ quick_hits ✓ closing ✓
Top takeaways: 3 ✓
SSML present: ✓

### Expansion / Coverage
Expansion triggered: yes
Trigger reason: gap-driven (2 articles uncovered) / duration-driven / not triggered
Duration gain: 45 min → 67 min (+22 min)
Gaps before: 2 | Gaps after: 0
Gaps filled: article_abc ✓, article_xyz ✓
Gaps remaining: none ✓
Segment deltas: ai_updates +180s, quick_hits +90s, funding_ma unchanged ✗

### Issues Found
1. harper_carroll: 0 articles (is today Wed/Thu? if yes, investigate parser)
2. P1 summary word count too low: 87 words for "{title}"

### Overall: PASS / NEEDS ATTENTION / FAIL
```

## Quick Dedup Check (bonus)

If there are articles with very similar titles in `curated_articles.json`, check `dedup_group_id` — if two articles about the same story both appear in P0/P1 without a shared group_id, dedup may have missed them. Report the pair if found.
