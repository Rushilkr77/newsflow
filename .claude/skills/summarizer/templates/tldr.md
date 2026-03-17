---
format_id: tldr
format_name: TL;DR
description: Single-paragraph executive summary -- 2-4 sentences maximum. Captures the single most important takeaway. Appends confidence and source as a footer line.
fidelity_sections_required:
- TL;DR paragraph
metadata_preserved:
- source_path
- confidence
---

# TL;DR Format

Ultra-concise single-paragraph summary for maximum brevity. Captures the essential takeaway in 2-4 sentences.

## When to Use

- User asks for "tl;dr", "one-liner", "in a nutshell", "quick summary"
- When extreme brevity is the priority
- As a preview before offering a more detailed format
- When summarizing for a status update or notification

## Schema

```text
**TL;DR**: [2-4 sentence summary capturing the single most important takeaway]

---
Source: [path or URL] | Confidence: [high|medium|low] | [access date]
```

## Example

```text
**TL;DR**: Python authentication module implementing JWT with automatic token refresh. Exports `AuthClient` class with retry logic (3 attempts on 401). Depends on httpx, jwt, and tenacity.

---
Source: ./src/auth.py | Confidence: high | Read 2026-02-06
```

## Fidelity Constraints

- MUST contain the single most important finding from the source
- Specific numbers and identifiers preserved where they appear in the summary
- Footer line MUST include source, confidence, and date
- If confidence is low, the TL;DR MUST say so: "**TL;DR** (low confidence): ..."
- No "What Was NOT Found" section -- but if critical gaps exist, note in the paragraph: "...though [X] was not addressed in the source."

## Metadata

- **Format version**: 1.0
- **Plugin**: summarizer
