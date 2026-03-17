# WITHOUT SKILL Baseline: ET AI Parser

## What was built

### `parsers/et_ai_parser.py` — Full rewrite of existing stub

Design decisions:
1. **Anchors on "Read More" links** — TOC entries never have "Read More"; story blocks always do. Primary filter.
2. **`_is_toc_link(href)`** — Skips hrefs starting with `#` or lacking `http` scheme.
3. **`_find_story_container(link_tag)`** — Walks up DOM from "Read More" anchor seeking container with ≥60 chars beyond link text.
4. **`_extract_title_and_snippet()`** — Strips "Read More" text and preambles, finds headline tag, splits remaining prose as snippet.
5. **URL deduplication** via `seen_urls` set.
6. **`extraction_confidence=0.8`** — Flags paywall-gated articles for scraper fallback.

### `config/senders.yaml` — Enabled et_ai
```yaml
- id: et_ai
  enabled: true
  lookback_days: 1
  variant_detection: from_display_name
  display_name_match: "ET AI"
  subject_prefix: "ET AI:"
```

### Already in place (no changes needed)
- `agents/ingestion.py` imports ETAIParser, has it in `_PARSER_INSTANCES`
- `models/enums.py` has `Source.ET_AI`
- `tests/test_parsers/test_et_ai_parser.py` exists with synthetic HTML tests

## Assertions check
1. Variant detection (display name "ET AI" / subject "ET AI:") ✓
2. Referenced existing parser as guide — NOT explicitly mentioned ✗
3. Addressed ToC-then-teasers structure ✓
4. Produced ETAIParser with method signatures ✓
5. Mentioned paywall fallback (extraction_confidence=0.8, scraper fallback) ✓

## Key differences vs. with-skill
- Did NOT read DESIGN.md spec first ✗
- Did NOT mention needing a real email fixture before implementation ✗
- Did NOT mention tests/fixtures/ workflow ✗
- DID produce a working implementation (32 tool uses)
- Modified real codebase (rewrote et_ai_parser.py, enabled in senders.yaml)

## Metrics
- Tool calls: ~32 (per task summary)
- Errors: file write to workspace denied
