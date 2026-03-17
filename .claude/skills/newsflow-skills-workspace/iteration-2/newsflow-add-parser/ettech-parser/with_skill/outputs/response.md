# WITH SKILL (Iter-2): ETtech Parser

## Step 0 — Checked parser existence FIRST
Yes — Glob on parsers/ettech_parser.py. Found immediately. Switched to validation mode (did NOT rewrite).

## Step 2 — Read spec and reference files
- DESIGN.md: YES — ETtech section: 5 stories, multipart/mixed, ET paywall → snippet fallback
- parsers/base_parser.py: YES — abstract parse(), _clean_url() confirmed
- agents/ingestion.py: YES — "ettech": ETtechParser() in _PARSER_INSTANCES (line 52), import at line 29
- config/senders.yaml: YES — enabled: true, sender_email: newsletter@ettech.com

## Step 3 — Fixture gate (HARD GATE)
YES — tests/fixtures/ettech_sample.html ABSENT. Hard gate triggered. Stopped and surfaced fixture request to user. Did NOT guess HTML structure.

## Step 4 — Parser validation
ETtechParser validated against DESIGN.md:
- Inherits BaseParser ✓
- parse() with correct signature ✓
- _clean_url() used ✓
- source=Source.ETTECH, section="top5" ✓
- Caps at 5 articles ✓
- Finds "Read More" links ✓
- No dedup logic (correctly left to curator) ✓
- ET paywall documented in module docstring ✓

## Step 5 — Registration (deliberate step)
YES — ingestion.py checked as named step. Import line 29, registry line 52, want_plain=False for multipart/mixed confirmed.

## Step 6 — Tests
tests/test_parsers/test_ettech_parser.py exists with 7 tests, all auto-skip when fixture absent.

## Checklist
1. Checked ettech_parser.py FIRST: YES ✓
2. Read DESIGN.md: YES ✓
3. Read base_parser.py: YES ✓
4. Stopped for fixture: YES ✓
5. ingestion.py registration as deliberate step: YES ✓
6. ET paywall/snippet fallback: YES ✓
