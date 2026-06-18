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
| `curated_articles_enriched.json` | Full scrape analysis — see Step 2b | Fetch source breakdown |
| `summaries.json` | Count total summaries | Should match P0+P1+P2 count |
| `podcast_script.json` | Count segments, total_estimated_duration_min | Report duration (no target range — flexible) |

**Expected funnel:**
- Raw: 60-80 articles
- Curated: 15-25 articles (P0: ≤3, P1: ≤5, P2: ≤5, plus all India articles)
- P0+P1 full-text scraped: >80% (flag if <60%)
- Snippet-only P0: 0 (any is a quality risk — flag by name)
- Summaries: same count as curated P0+P1+P2
- Episode: report duration as-is; **length is flexible, not a pass/fail target**

Flag any stage where counts fall outside expected range (except episode duration).

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
Count: `primary: N | ddg: N | snippet-only: N` from the log if available.

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

**Structured header check** — count section headers in `summary_text` per priority tier:

| Priority | Required headers | Min expected |
|---------|-----------------|--------------|
| P0 | CORE NEWS, SURROUNDING IMPACT, COMPETITOR CONTEXT, LAUNCH RATIONALE, HOW IT WORKS, PM INTERVIEW EDGE | 6 |
| P1 | CORE NEWS + IMPACT, HOW + WHY, PM EDGE | 3 |
| P2 | CORE NEWS, PM EDGE | 2 |

Flag any summary where header count falls below minimum.

## Step 4 — Script quality check

From `podcast_script.json`:

1. **Duration**: `total_estimated_duration_min` — report value only; **episode length is flexible, not flagged**.
   - Estimated duration uses `_CHARS_PER_SEC=19` (Chatterbox/F5-TTS pace, calibrated 2026-05-12).
     At 19 chars/sec the estimate should closely match actual audio. Cross-check with
     `duration_sec` in `episode_metadata.json` (actual audio) if it exists.
2. **Segment coverage**: Are all expected segment types present?
   - Required: `opener`, `ai_updates`, `closing`
   - Expected: at least 3 of `funding`, `india_tech`, `product_strategy`, `quick_hits`
3. **Discussion hooks**: Count `top_takeaways` — target is 3
4. **SSML check**: Sample `content_ssml` from the `ai_updates` segment — does it contain `<break` tags? Does `content_plain` exist and differ from SSML?
5. **Opener quality**: Read the `opener` segment — does it hook with a specific story, or is it generic?

**Note**: Episode length is flexible — do not flag overruns or underruns. There is no tighten-pass in the current codebase.

## Step 5 — Source coverage check

From `curated_articles.json`, verify each enabled source contributed at least 1 article:
- `tldr_ai` — expected daily
- `tldr_tech` — expected daily
- `tldr_dev` — expected daily
- `techcrunch` — expected daily (may appear as morning + afternoon edition)
- `ettech` — expected daily
- `et_ai` — expected daily
- `harper_carroll` — weekly (Wed/Thu only; skip check Mon/Tue/Fri/Sat/Sun)

If any daily source has 0 articles, flag as likely parser or Gmail fetch issue.

## Step 5b — Expansion / Coverage report

Check for `workspace/{date}/logs/expansion_diff.json`.

**If file does not exist**: expansion was not triggered. Report: `Expansion: not triggered`.

**If file exists**, read it. Report:
1. Duration gain: pre → post (+N min)
2. Gap resolution: gaps_before → gaps_after; list gaps_filled and gaps_remaining
3. Per-segment delta for expanded segment only (expansion is now localized)
4. Trigger: gap-driven only (P0 article skipped from narration)
5. Flag if gaps_remaining > 0 (cross-check article titles in curated_articles.json — may be paraphrase false-positive)

Note: `undercovered` bucket no longer used. Only `skipped` P0 articles trigger expansion.

## Step 5c — Dedup Validation report

Read `workspace/{date}/logs/validation_report.json` (if exists):

Report:
- Offenders detected in first pass (articles in 2+ deep segments)
- Regenerations performed (segment IDs + iteration count)
- Final offender count — 0 = pass, >0 = "dedup did not converge" ISSUE
- History of each iteration

If file does not exist: "validation not run (script loaded from checkpoint)".

## Step 5d — Tighten-pass report

Read `workspace/{date}/logs/tighten_diff.json` (if exists):

If exists: report pre/post duration, which P1/P2 stories were compressed. Label as `tighten-pass applied` — this is expected behavior, not a failure.

If not exists: report "tighten-pass: not needed".

## Step 5e — Audio cleanup report

Parse `workspace/{date}/logs/pipeline.log` for `audio_cleanup_applied` and `audio_cleanup_fallback` events:

- Report: cleanup enabled/disabled, noise-reduce + highpass applied per segment
- Flag if cleanup fell back to highpass-only on >1 segment (noisereduce import issue)
- Flag if `audio_cleanup_disabled` appears (config disabled)

## Step 6 — Output the quality report

Format:
```
## NewsFlow Quality Report — {date}

### Article Funnel
Raw: X | Curated: X (P0:X P1:X P2:X P3:X) | Summaries: X | Duration: X min

### Content Fetch Quality
Fetch source:  primary: X | ddg: X | snippet-only: X
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
Duration: 47 min
Segments: opener ✓ ai_updates ✓ funding ✓ india_tech ✗ product_strategy ✓ quick_hits ✓ closing ✓
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
