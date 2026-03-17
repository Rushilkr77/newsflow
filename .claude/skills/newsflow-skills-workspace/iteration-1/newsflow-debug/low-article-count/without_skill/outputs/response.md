# WITHOUT SKILL Baseline: Low Article Count

## Approach
Agent read curator.py, ingestion.py, senders.yaml, preferences.yaml, pipeline.py, and real log files (workspace/2026-03-14/logs/2_curation.txt) before diagnosing.

## Key finding from real log
workspace/2026-03-14/logs/2_curation.txt: 66 raw → 26 curated (P0:6, P1:6, P2:14, Dropped:40) — NORMAL run
workspace/2026-03-09/: 9 raw → 9 curated (all TechCrunch, all P2) — ingestion problem, not curation

## Diagnosis framework provided

**Step 1:** Check raw_articles.json count first (correctly identified this as first step)

**If raw ~3:** Ingestion problem (weekend, missing newsletters)
**If raw 25+ but curated 3:** Curator failure — keep diagnosing

**Filter analysis in curator.py:**
- Filter 1 (_is_garbage_title, lines 174-185): removes parsing artifacts — can't explain 22+ drop
- Filter 2 (LLM classification dropping P3, lines 187-218): ONLY filter that can cause 25→3 drop
- Filter 3 (time budget, lines 393-436): caps articles, can't drop to 3 on its own

**Most likely root causes:**
1. LLM aggressively classifying as P3 (primary suspect)
2. Ollama returning partial JSON with P3 (not caught by exception handler)
3. CURATOR_LOCAL_MODEL pointing to missing model

## Concrete next steps provided
1. Check P0/P1/P2/P3 breakdown in logs/2_curation.txt
2. Check pipeline.log structlog entries (title_prefilter_done, classification_complete, time_budget_applied)
3. Check Ollama: `ollama list` + test query
4. Examine the 3 curated articles — if all P2 with relevance 40.0, _fallback_curated() was invoked

## Recovery command
```bash
del workspace\{date}\curated_articles.json
del workspace\{date}\summaries.json [...]
python -m orchestrator.pipeline --date {date}
```

## Assertions check (updated methodology assertions)
1. Reads actual checkpoint file before diagnosing ✓ (read real 2_curation.txt log)
2. Reports article counts at multiple pipeline stages ✓ (66→26 from real log, 9→9 weekend example)
3. Identifies correct stage (ingestion vs curation) ✓ (instructs checking raw first, then curator)
4. Gives concrete specific root cause ✓ (P3 over-classification with specific code locations)
5. Provides actionable fix with specific commands ✓

## Key difference vs. WITH SKILL
- WITHOUT SKILL: Generic code analysis + recovery plan, didn't find the REAL root cause (it's Sunday, no TLDR)
- WITH SKILL: Read workspace/2026-03-15/ (doesn't exist yet), checked what day it is, found actual root cause

## Metrics
- Tool calls: ~38 (per task summary — very thorough code reading)
- Files read: curator.py, ingestion.py, senders.yaml, preferences.yaml, pipeline.py, real log files
