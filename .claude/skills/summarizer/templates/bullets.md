---
format_id: bullets
format_name: Bullet Points
description: Concise bulleted list of key findings with inline source references. No YAML frontmatter in output. Preserves fidelity through mandatory Not-Found and Uncertain bullets.
fidelity_sections_required:
- Key Findings (bullets)
- Not Found (bullets)
- Uncertain (bullets)
metadata_preserved:
- source_path
- confidence
---

# Bullet Points Format

Concise bulleted output for quick consumption. Each bullet is a self-contained finding with inline attribution.

## When to Use

- User asks for "bullet points", "key points", "quick bullets"
- When brevity is prioritized over completeness
- When output will be read by humans in a conversational context
- When the user says "just the highlights"

## Schema

```text
## Key Findings

- [Finding 1] (source: [reference])
- [Finding 2] (source: [reference])

## Not Found

- [Item searched for but absent from source]

## Uncertain

- [Ambiguous item] (source: [reference])

---
Source: [path or URL] | Confidence: [high|medium|low] | [access date]
```

## Example

```text
## Key Findings

- REST API uses JWT authentication with 24-hour token expiry (source: Section 3.2, lines 45-67)
- Rate limiting set to 100 req/min per API key (source: Section 5.1, line 112)
- Deprecation notice for v1 endpoints effective 2025-06-01 (source: Header banner)

## Not Found

- No mention of WebSocket support in the API documentation
- No pricing information found on the page

## Uncertain

- "Custom limits" referenced for enterprise tier but values not specified (source: Section 6.1)

---
Source: https://example.com/docs/api | Confidence: high | Accessed 2026-02-06
```

## Fidelity Constraints

- Every bullet MUST include inline source reference
- "Not Found" section is mandatory even if empty ("None")
- "Uncertain" section is mandatory even if empty ("None")
- Exact counts preserved -- "7 of 10" not "most"
- Footer line MUST include source path, confidence level, and access date

## Metadata

- **Format version**: 1.0
- **Plugin**: summarizer
