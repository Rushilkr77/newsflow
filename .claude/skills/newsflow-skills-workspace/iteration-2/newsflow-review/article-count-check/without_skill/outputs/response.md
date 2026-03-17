# WITHOUT SKILL (Iter-2): Article Count Check

## Article Counts by Source (from raw_articles.json, 39 total)
| Source | Count | Notes |
|---|---|---|
| techcrunch | 18 | AM + PM editions |
| tldr_tech | 13 | Multiple send timestamps |
| tldr_ai | 8 | Single timestamp |
| tldr_dev | 0 | No emails fetched |
| harper_carroll | 0 | No emails fetched |
| ettech | 0 | Not in raw |
| et_ai | 0 | Not in raw |
| TOTAL | 39 | |

Curated: 23 (P0:6 P1:11 P2:6)

## P0 Word Counts (all 6, from summaries.json word_count field)
| Article | Words | Target | Status |
|---|---|---|---|
| Amazon Health AI | 184 | 300-500 | FAIL (-116) |
| Google Gemini Chrome India | 207 | 300-500 | FAIL (-93) |
| YouTube (COMPANY) | 212 | 300-500 | FAIL (-88) |
| Canopii indoor farms | 222 | 300-500 | FAIL (-78) |
| WhatsApp pre-teen accounts | 216 | 300-500 | FAIL (-84) |
| Google/Wiz $32B | 219 | 300-500 | FAIL (-81) |

Pass rate: 0/6 (0%)

## Root Cause
A. No scraping occurred (primary) — full_text: null on all articles, summarizer had only email snippets (~30-60 words)
B. Summarizer prompt/token budget under-constrains output length — model produced ~210 words avg vs 350+ target

## Structured PASS/FAIL Output: YES ✓
Produced structured PASS/FAIL block for all sources and all P0 word counts.
