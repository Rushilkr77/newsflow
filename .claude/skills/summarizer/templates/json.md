---
format_id: json
format_name: JSON
description: Machine-readable JSON output with all metadata and findings as structured fields. Parseable by downstream tools. Fidelity enforced through required keys.
fidelity_sections_required:
- summary
- findings
- not_found
- uncertain
- sources
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

# JSON Format

Machine-readable JSON output containing all metadata and findings as structured fields. Designed for programmatic consumption and downstream tool integration.

## When to Use

- User asks for "json", "machine-readable", "structured data", "parseable output"
- When output will be consumed by scripts, pipelines, or other tools
- When metadata needs to be programmatically accessible
- When the user says "give me the data" or "I need this in json"

## Schema

```json
{
  "metadata": {
    "source_type": "file | url | image | multi-source",
    "source_path": "<string or array>",
    "summarized_at": "<ISO 8601>",
    "method": "extractive | abstractive | hybrid",
    "word_count_source": "<integer or null>",
    "word_count_summary": "<integer>",
    "compression_ratio": "<float or null>",
    "confidence": "high | medium | low",
    "confidence_notes": "<string>"
  },
  "summary": "<string>",
  "findings": [
    {
      "item": "<string>",
      "source_ref": "<string>"
    }
  ],
  "not_found": ["<string>"],
  "uncertain": ["<string>"],
  "sources": [
    {
      "path": "<string>",
      "accessed": "<ISO 8601 date>"
    }
  ]
}
```

## Example

```json
{
  "metadata": {
    "source_type": "file",
    "source_path": "./src/auth.py",
    "summarized_at": "2026-02-06T14:30:00Z",
    "method": "hybrid",
    "word_count_source": 1250,
    "word_count_summary": 95,
    "compression_ratio": 0.076,
    "confidence": "high",
    "confidence_notes": "Full file read, structured code with clear documentation"
  },
  "summary": "Python module implementing JWT authentication with automatic token refresh. Exports AuthClient class and refresh_token() function.",
  "findings": [
    {
      "item": "Class AuthClient (lines 15-87): JWT-based HTTP client with token refresh",
      "source_ref": "lines 15-87"
    },
    {
      "item": "Function refresh_token() retries up to 3 times on 401 errors",
      "source_ref": "lines 92-105"
    },
    {
      "item": "Dependencies: httpx, jwt, tenacity",
      "source_ref": "lines 1-3"
    }
  ],
  "not_found": [
    "No test coverage information in this file",
    "No error handling for network failures"
  ],
  "uncertain": [],
  "sources": [
    {
      "path": "./src/auth.py",
      "accessed": "2026-02-06"
    }
  ]
}
```

## Fidelity Constraints

- Output MUST be valid JSON (parseable by `json.loads()`)
- All 5 content keys (`summary`, `findings`, `not_found`, `uncertain`, `sources`) are required
- `not_found` array MUST exist even if empty (`[]`)
- `uncertain` array MUST exist even if empty (`[]`)
- Each finding MUST include `source_ref` for traceability
- Exact counts preserved in string values -- "7 of 10" not "most"
- `metadata` object MUST include `confidence` and `confidence_notes`

## Metadata

- **Format version**: 1.0
- **Plugin**: summarizer
