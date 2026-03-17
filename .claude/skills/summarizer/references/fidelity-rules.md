# Fidelity Rules for Summarization

These rules govern ALL summarization operations in this plugin. They exist to prevent the three failure modes observed in AI summarization:

1. **Hallucinated content** - guessing file contents from filenames instead of reading them
2. **Lossy summary chains** - summarizing summaries, losing nuance at each step
3. **Speculation as observation** - upgrading "not found" to "doesn't exist"

## Rule 1: Read Before Summarizing

The model MUST read the actual content of any source before producing a summary.

**Prohibited behaviors**:

- Guessing file contents from the filename or path
- Describing a file based on its position in a directory listing
- Summarizing a URL from its domain or path segments
- Inferring image content from the filename

**Required behavior**:

- Use the Read tool to read files
- Use WebFetch or mcp__Ref__ref_read_url to read URLs
- Use the Read tool to view images (Claude Code is multimodal)
- If a source cannot be read, state: "Unable to read [source]: [reason]"

## Rule 2: Extract Before Abstracting

When summarizing text content, the model MUST first extract relevant quotes or passages, then summarize from those extracts.

**Process**:

1. Read full source
2. Identify and extract key passages (the "extractive" step)
3. Organize extracts by theme or importance
4. Write summary grounded in the extracts (the "abstractive" step)
5. Verify every claim in the summary traces back to an extract

**Why**: Extraction creates an audit trail. If a summary claim cannot be traced to an extracted passage, it may be hallucinated.

SOURCE: "Ground responses in quotes" technique from Anthropic prompt engineering documentation (<https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips>, accessed 2026-02-06).

## Rule 3: Preserve Counts and Specifics

When relaying quantitative information, the model MUST preserve exact numbers, counts, and specifics.

**Prohibited transformations**:

| Source Says | Model Writes | Problem |
|-------------|-------------|---------|
| "7 items found, 3 not accessible" | "Most items found" | Lost counts |
| "Error on lines 45, 89, 203" | "Several errors found" | Lost specifics |
| "3 of 10 tests failed" | "Some tests failed" | Lost ratio |
| "Response time: 245ms" | "Fast response time" | Lost measurement |

**Required behavior**: Preserve the original numbers. If compression is needed, state the numbers then add interpretation:

```text
7 of 10 items found (3 sources were inaccessible). The accessible sources cover the core API documentation.
```

## Rule 4: Distinguish Absence from Nonexistence

The model MUST use precise language when information is not found.

**The spectrum of "not found"**:

| Situation | Correct Language | Incorrect Language |
|-----------|-----------------|-------------------|
| Searched but not in source | "Not mentioned in this document" | "Doesn't exist" |
| Source inaccessible | "Unable to access [source]" | "Not available" |
| Source doesn't cover topic | "Outside the scope of this source" | "Not supported" |
| Ambiguous/unclear | "The source is unclear about X" | "X works differently" |
| Contradictory sources | "Source A says X, Source B says Y" | "The answer is X" |

**The principle**: Reporting what you searched and what you found (or didn't find) is an observation. Concluding that something doesn't exist is a claim that requires evidence beyond "I didn't find it."

## Rule 5: No Lossy Re-Summarization

When an orchestrator receives a summary from a sub-agent, it MUST NOT re-summarize that summary.

**Prohibited pattern** (the lossy chain):

```text
Agent researches 10 items → finds 7, can't access 3
Agent reports: "7 items found with details, 3 items inaccessible"
Orchestrator tells user: "Research complete, 7 items found, the rest don't exist"
                                                              ^^^ INFORMATION CORRUPTED
```

**Required pattern** (the relay):

```text
Agent researches 10 items → finds 7, can't access 3
Agent reports: "7 items found with details, 3 items inaccessible"
Agent writes results to file: ./research-results.md
Orchestrator tells user: "Research complete. 7 items found, 3 sources were inaccessible.
                          Full results: ./research-results.md"
```

**Rules for orchestrators**:

1. If the agent wrote a file, reference the file path
2. If the agent returned counts, preserve exact counts
3. If the agent reported failures, preserve failure reasons
4. Do NOT interpret agent results - relay them
5. Do NOT upgrade "inaccessible" to "nonexistent"
6. Do NOT upgrade "not found" to "doesn't exist"

## Rule 6: State Confidence Explicitly

Every summary MUST include a confidence assessment in the YAML frontmatter.

**Factors that reduce confidence**:

- Source was partially read (truncated, paginated, rate-limited)
- Source is dated (information may have changed)
- Source is informal (chat message vs official documentation)
- Source is ambiguous (multiple interpretations possible)
- Source conflicts with other sources
- Summarizer had to interpret (not just extract)

**Factors that increase confidence**:

- Full source was read completely
- Source is authoritative (official documentation, primary source)
- Source is recent and dated
- Content is factual/structured (API spec, config file) vs. opinion/narrative
- Multiple sources agree

SOURCE: Confidence scoring methodology adapted from Anthropic knowledge-synthesis skill (knowledge-work-plugins repository, accessed 2026-02-06). Freshness and authority weighting from the same source.

## Rule 7: Structured Output Always

Every summary MUST use the structured output format defined in [Structured Summary](../templates/structured.md).

The structured sections (Summary, What Was Found, What Was NOT Found, Uncertain, Sources) exist to force explicit categorization. Omitting any section is prohibited - if nothing belongs in a section, write "None" or "N/A."

This prevents the common failure mode where uncertain information gets silently mixed into the summary as if it were definitive.
