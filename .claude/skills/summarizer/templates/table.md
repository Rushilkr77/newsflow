---
format_id: table
format_name: Table
description: Findings presented as a markdown table with columns for item, detail, source reference, and status. Compact visual format for scanning many findings quickly.
fidelity_sections_required:
- Findings table
- Not Found (rows or section)
- Uncertain (rows or section)
metadata_preserved:
- source_path
- confidence
---

# Table Format

Tabular output for quick visual scanning of findings. Each row represents one finding with its source reference and status.

## When to Use

- User asks for "table", "tabular", "comparison", "grid format"
- When there are many discrete findings that benefit from columnar layout
- When the user wants to scan and compare items quickly
- Good for config files, API endpoints, feature lists

## Schema

```text
## Summary

[1-2 sentence BLUF summary]

| # | Finding | Detail | Source | Status |
|---|---------|--------|--------|--------|
| 1 | [item] | [detail] | [ref] | Found |
| 2 | [item] | [detail] | [ref] | Found |
| 3 | [item] | [detail] | N/A | Not Found |
| 4 | [item] | [detail] | [ref] | Uncertain |

---
Source: [path or URL] | Confidence: [high|medium|low] | [access date]
```

## Example

```text
## Summary

API configuration file defining 4 endpoints with JWT authentication and rate limiting.

| # | Finding | Detail | Source | Status |
|---|---------|--------|--------|--------|
| 1 | Auth method | JWT with 24h expiry | Section 3.2, line 45 | Found |
| 2 | Rate limit | 100 req/min per key | Section 5.1, line 112 | Found |
| 3 | Base URL | https://api.example.com/v2 | Line 3 | Found |
| 4 | WebSocket support | Not mentioned in source | N/A | Not Found |
| 5 | Enterprise limits | "Custom limits" referenced, values unspecified | Section 6.1 | Uncertain |

---
Source: ./config/api.yaml | Confidence: high | Read 2026-02-06
```

## Fidelity Constraints

- Status column MUST use exactly: `Found`, `Not Found`, or `Uncertain`
- Every `Found` row MUST have a Source reference
- `Not Found` rows MUST exist -- cannot omit them from the table
- `Uncertain` rows MUST exist -- cannot omit them from the table
- If no items are Not Found or Uncertain, include one row: "None identified" with appropriate status
- Exact counts in Detail column -- "3 retries" not "several retries"
- Footer MUST include source, confidence, and date

## Metadata

- **Format version**: 1.0
- **Plugin**: summarizer
