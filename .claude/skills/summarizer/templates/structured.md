---
format_id: structured
format_name: Structured Summary
description: Full structured summary with YAML frontmatter, five mandatory sections, and inline source references. Default format when no format is specified.
fidelity_sections_required:
- Summary
- What Was Found
- What Was NOT Found
- Uncertain
- Sources
metadata_preserved:
- source_type
- source_path
- summarized_at
- method
- word_count_source
- word_count_summary
- compression_ratio
- confidence
- confidence_notes
---

# Structured Summary Format

Default output format for all summarization operations. Produces a complete, machine-parseable summary with YAML frontmatter and five mandatory body sections.

## When to Use

- Default format when no specific format is requested
- When downstream consumers need machine-parseable metadata
- When fidelity audit trail is required (What Was Found / What Was NOT Found / Uncertain sections)
- When the user asks for "full summary", "detailed summary", or "complete summary"

## Schema

### YAML Frontmatter

```yaml
---
source_type: file | url | image | multi-source
source_path: "<exact path, URL, or list of sources>"
summarized_at: "<ISO 8601 timestamp>"
method: extractive | abstractive | hybrid
word_count_source: <integer or null if not applicable>
word_count_summary: <integer>
compression_ratio: <float or null>
confidence: high | medium | low
confidence_notes: "<why this confidence level>"
---
```

### Field Definitions

| Field | Required | Description |
|-------|----------|-------------|
| `source_type` | Yes | What kind of source was summarized |
| `source_path` | Yes | Exact path or URL. For multi-source, use YAML list |
| `summarized_at` | Yes | When the summary was generated |
| `method` | Yes | `extractive` = selected passages. `abstractive` = new text generated. `hybrid` = combination |
| `word_count_source` | Yes | Word count of original. `null` for images or inaccessible sources |
| `word_count_summary` | Yes | Word count of the summary section |
| `compression_ratio` | No | `word_count_summary / word_count_source`. Omit for images |
| `confidence` | Yes | Overall confidence in summary accuracy |
| `confidence_notes` | Yes | Explanation of confidence level |

### Confidence Level Criteria

| Level | Criteria |
|-------|----------|
| `high` | Full source was read. Content is factual/structured. No ambiguity in interpretation |
| `medium` | Source partially accessible, or content requires interpretation, or source is dated |
| `low` | Source inaccessible/truncated, content ambiguous, conflicting information present |

### Body Sections

The body MUST contain these sections in this order:

**1. Summary** - The condensed content (BLUF -- Bottom Line Up Front). Use the source's own terminology. Attribute claims to source sections. Do NOT add information not in the source.

**2. What Was Found** - Bulleted list of key items with source references (section, line number, or location).

**3. What Was NOT Found** - Items searched for or expected but absent. CRITICAL: "Not found in source" is NOT "does not exist." Use: "The document does not mention X" not "X is not supported."

**4. Uncertain** - Items where the source was ambiguous or interpretation may not be accurate.

**5. Sources** - Full attribution with access dates.

## Example

```yaml
---
source_type: file
source_path: "./src/auth.py"
summarized_at: "2026-02-06T14:30:00Z"
method: hybrid
word_count_source: 1250
word_count_summary: 180
compression_ratio: 0.144
confidence: high
confidence_notes: "Full file read, structured code with clear documentation"
---
```

## Summary

Python module implementing JWT authentication with automatic token refresh. Exports `AuthClient` class and `refresh_token()` function.

## What Was Found

- Class `AuthClient` (lines 15-87): JWT-based HTTP client with token refresh
- Function `refresh_token()` (lines 92-105): Retries up to 3 times on 401 errors
- Dependencies: `httpx`, `jwt`, `tenacity` (lines 1-3)

## What Was NOT Found

- No test coverage information in this file
- No error handling for network failures

## Uncertain

- N/A

## Sources

- ./src/auth.py (read 2026-02-06 at 14:30 UTC)

## Fidelity Constraints

- All 5 body sections are mandatory. If nothing belongs in a section, write "N/A"
- "Not found in source" language MUST distinguish absence from nonexistence
- Exact counts and specifics MUST be preserved (Rule 3)
- Every summary claim MUST trace to an extracted passage (Rule 2)
- Confidence assessment MUST appear in frontmatter (Rule 6)

## Metadata

- **Origin**: Migrated from `references/output-format.md` (lines 1-110)
- **Format version**: 1.0
- **Plugin**: summarizer
