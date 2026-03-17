---
format_id: outline
format_name: Outline
description: Hierarchical indented outline mirroring the source document structure. Preserves the source's own organization with nested headings and sub-items. Good for documentation and long-form content.
fidelity_sections_required:
- Outline body
- Not Found
- Uncertain
metadata_preserved:
- source_path
- confidence
---

# Outline Format

Hierarchical outline that mirrors the source document's structure. Preserves the original organization while condensing content at each level.

## When to Use

- User asks for "outline", "table of contents", "hierarchical", "structure"
- When the source has a clear heading/section structure worth preserving
- When the user wants to understand document organization
- Good for documentation files, long articles, codebases with module structure

## Schema

```text
## Outline

- **[Top-level heading or component]**
  - [Key point] (source: [ref])
  - [Key point] (source: [ref])
  - **[Sub-heading or sub-component]**
    - [Key point] (source: [ref])

## Not Found

- [Expected item not present in source]

## Uncertain

- [Ambiguous item] (source: [ref])

---
Source: [path or URL] | Confidence: [high|medium|low] | [access date]
```

## Example

```text
## Outline

- **1. Getting Started** (lines 10-45)
  - Docker installation on Linux and macOS
  - Prerequisites: Docker Engine 24+, 4GB RAM minimum
- **2. Building Images** (lines 47-89)
  - Dockerfile syntax overview (source: lines 48-60)
  - **2.1 Multi-stage Builds** (lines 61-89)
    - Builder pattern for reducing image size
    - Example: Go application from 1.2GB to 45MB (source: line 78)
- **3. Registry Configuration** (lines 90-130)
  - Docker Hub setup (source: lines 91-100)
  - Private registry authentication (source: lines 101-130)
- **4. Troubleshooting** (lines 200-245)
  - 5 common errors with solutions documented

## Not Found

- No Windows deployment instructions
- Security best practices section not present
- Performance tuning mentioned at line 15 ("TODO") but not written

## Uncertain

- Section 3 references "advanced registry options" but no link or content found

---
Source: ./docs/deployment-guide.md | Confidence: high | Read 2026-02-06
```

## Fidelity Constraints

- Outline hierarchy MUST reflect the source document's actual structure
- Do NOT impose an artificial organization -- mirror the source
- Each leaf item SHOULD include a source reference
- "Not Found" section is mandatory even if empty ("None")
- "Uncertain" section is mandatory even if empty ("None")
- Indentation level indicates nesting depth -- use consistent 2-space indent for each level
- Footer MUST include source, confidence, and date

## Metadata

- **Format version**: 1.0
- **Plugin**: summarizer
