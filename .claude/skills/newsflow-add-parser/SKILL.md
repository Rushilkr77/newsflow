---
name: newsflow-add-parser
description: Add a new newsletter parser to the NewsFlow pipeline. Activate when the user says "add parser", "build parser", "add new source", "implement ettech parser", "implement et_ai parser", or names any newsletter source that needs parsing.
---

# NewsFlow: Add New Parser

Follow this exact sequence. Do not skip steps.

## Step 0 — Check if the parser already exists

Before writing anything, check if the parser is already implemented:
- Look in `parsers/` for `{source_id}_parser.py`
- Grep for the class name in `parsers/`

If it exists:
- Read it and **validate** it rather than rewriting it
- Check `config/senders.yaml` — is the source `enabled: true`? If not, ask the user before enabling
- Check `agents/ingestion.py` — is it registered in the parser registry?
- Skip to Step 3 (fixture check) to validate it works with a real sample

Do not rewrite a parser that already exists. Validate it instead.

## Step 1 — Identify the target source

Ask the user which source they're adding if not already stated. Valid source IDs from `config/senders.yaml`:
- `ettech` — ETtech Top 5 (newsletter@ettech.com, multipart/mixed)
- `et_ai` — ET AI (newsletter@economictimesnews.com, multipart/mixed)
- Or a brand-new source not yet in senders.yaml

## Step 2 — Read the spec and reference files in parallel

Read ALL of these before writing any code:
1. `docs/DESIGN.md` — find the parser section for the target source (search for the source name)
2. `parsers/base_parser.py` — the interface to inherit from
3. The most similar existing parser:
   - Plain text sources → read `parsers/harper_carroll_parser.py`
   - HTML/structured sources → read `parsers/techcrunch_parser.py`
4. `agents/ingestion.py` — the parser registry and how parsers are registered
5. `config/senders.yaml` — check if the source is already configured

## Step 3 — Check for test fixtures

Look in `tests/fixtures/` for any existing email sample for this source.
- If found: read it to understand the real email structure before coding
- If not found: tell the user you need a real email sample. Ask them to:
  1. Open Gmail, find a recent email from this newsletter
  2. Save the raw body to `tests/fixtures/{source_id}_sample.txt` (plain text) or `tests/fixtures/{source_id}_sample.html` (HTML)
  3. Then resume — do NOT guess the email structure from the DESIGN.md alone

## Step 4 — Implement the parser

Create `parsers/{source_id}_parser.py` following these conventions:
- Class name: `{SourceId}Parser` (e.g., `ETtechParser`)
- Inherit from `BaseParser`
- Implement `parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]`
- Use `_clean_url()` from BaseParser for all URLs
- Set `extraction_confidence` honestly: 1.0 for well-structured, 0.85 for ambiguous
- Add structlog logging: article count per section, any skipped items with reasons
- Handle the specific MIME type (`want_plain` flag if plain text source)

**ETtech-specific rules from DESIGN.md**:
- Exactly 5 stories per edition
- MIME: multipart/mixed
- India-focused content
- Full article behind paywall — snippet is the fallback if scrape fails

**ET AI-specific rules from DESIGN.md**:
- MUST filter: From display name = "ET AI" OR subject starts with "ET AI:"
- Has table of contents at top, then full teasers below — parse the teasers section
- MIME: multipart/mixed
- ET paywall applies — same fallback strategy as ETtech

## Step 5 — Register the parser

In `agents/ingestion.py`, add the new parser to the parser registry. Follow the exact pattern used for existing parsers — find the `PARSER_REGISTRY` dict or equivalent and add the new entry.

In `config/senders.yaml`, verify the source entry has `enabled: true` (or add it if missing).

## Step 6 — Write a quick validation test

Create `tests/test_parsers/test_{source_id}_parser.py`:
```python
from parsers.{source_id}_parser import {SourceId}Parser
from models.article import RawArticle

def test_{source_id}_parser_returns_articles():
    body = open("tests/fixtures/{source_id}_sample.txt").read()  # or .html
    metadata = {"sender_email": "...", "date": "2026-03-12", "subject": "..."}
    articles = {SourceId}Parser().parse(body, metadata)
    assert len(articles) > 0
    for a in articles:
        RawArticle.model_validate(a.model_dump())  # Pydantic v2 validation

def test_{source_id}_parser_no_sponsors():
    # verify sponsor/ad articles are excluded
    ...
```

Run it: `python -m pytest tests/test_parsers/test_{source_id}_parser.py -v`

## Step 7 — Test with the live pipeline (optional)

```bash
python -m orchestrator.pipeline --date test --stage ingestion
```

Check `workspace/test/raw_articles.json` — filter for `source: "{source_id}"` to see extracted articles.

## Common Pitfalls to Avoid

- **Never hardcode section names** for sources where section names vary (e.g., Harper Carroll). Parse them dynamically.
- **ET paywall**: don't follow ET links expecting full content. The snippet IS the content. Scrapers will fail — that's expected.
- **Encoding**: ETtech and ET AI emails may contain Indian rupee symbols (₹) or Devanagari — ensure you handle non-ASCII cleanly.
- **multipart/mixed**: for ETtech and ET AI, use `want_plain=False` (HTML part). Check `ingestion.py` for how existing parsers specify this.
- **Don't duplicate dedup logic** in the parser. Parsers extract; the curator deduplicates.
