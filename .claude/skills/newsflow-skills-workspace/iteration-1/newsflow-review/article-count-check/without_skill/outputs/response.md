# WITHOUT SKILL Baseline: Article Count Check

## Article Counts by Newsletter

| Newsletter | Source ID | Raw Count |
|---|---|---|
| TechCrunch Daily | techcrunch | 18 |
| TLDR Tech | tldr_tech | 15 |
| TLDR AI | tldr_ai | 8 |
| **Total raw** | | **41** |

After dedup + curation: 23 articles (6 P0 / 11 P1 / 6 P2). All 8 tldr_ai articles dropped by curator.
TechCrunch high count (18) expected — AM + PM editions both captured.
No Harper Carroll, ETtech, ET AI — not fetched for this test run.

## P0 Summary Word Count Check

Target: 300-500 words

| Article | Words | Status |
|---|---|---|
| Amazon healthcare AI | 184 | FAIL |
| Google Gemini Chrome India | 207 | FAIL |
| YouTube world's largest media | 212 | FAIL |
| Canopii indoor farms | 222 | FAIL |
| WhatsApp parent-linked accounts | 216 | FAIL |
| Google acquires Wiz ($32B) | 219 | FAIL |

0 of 6 P0 summaries hit 300-word floor. All in 184-222 word band (~40-60% of minimum).

## Root cause identified
All articles have `full_text: null` — scraper didn't run. Summarizer only had short snippets as input. qwen2.5:7b can't produce 300+ words from 1-3 sentence snippets.

Secondary: P0 prompt says "Stay within 300-500 words strictly" — local models treat this as upper bound.

## Fix suggested
1. Ensure trafilatura runs before summarization — full_text must be populated for P0
2. Add word count gate: if word_count < 250 on P0, retry or flag
3. Rephrase prompt: "Write AT LEAST 300 words, no more than 500"

## Assertions check
- Reports source breakdown ✓
- Reads summaries.json and finds P0 summaries ✓
- Reports word count for at least one P0 ✓
- Compares against 300-500 target ✓
- Flags out-of-range P0 summaries ✓
- Missing: structured PASS/FAIL report format, script quality check, segment analysis ✗
- Missing: did NOT check podcast_script.json at all ✗

## Metrics
- Tool calls: ~13 (per task summary)
- Errors: 2 (Write/Bash permission denied)
