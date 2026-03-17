# NewsFlow AI — Implementation Design Spec

> This document contains everything needed to build NewsFlow AI.
> Each section maps to a component in the codebase. Build in phase order.

---

## Table of Contents

1. [Newsletter Source Registry](#1-newsletter-source-registry)
2. [Data Models (Pydantic)](#2-data-models)
3. [Config Files](#3-config-files)
4. [Parsers — Email HTML Extraction](#4-parsers)
5. [Article Scraper — Full Content Fetch](#5-article-scraper)
6. [Agent 1: Ingestion](#6-agent-1-ingestion)
7. [Agent 2: Curator](#7-agent-2-curator)
8. [Agent 3: Summarizer](#8-agent-3-summarizer)
9. [Agent 4: Script Writer](#9-agent-4-script-writer)
10. [Agent 5: Audio Producer](#10-agent-5-audio-producer)
11. [Pipeline Orchestrator](#11-pipeline-orchestrator)
12. [Delivery](#12-delivery)
13. [Phase Implementation Plan](#13-phase-implementation-plan)
14. [Evaluation & Monitoring](#14-evaluation--monitoring)

---

## Model Strategy

### Local Ollama (primary — free, GTX 1650 Ti 4GB VRAM)

| Agent | Model | VRAM | Reason |
|-------|-------|------|--------|
| Curator (classification) | `qwen2.5:3b` | ~1.9 GB | Best 3B for structured JSON output; classification is rule-following, 7B adds no quality |
| Summarizer (all tiers) | `qwen2.5:7b` | ~4.7 GB* | Extra params pay off for word-count discipline and dual-lens depth in P0 summaries |
| Script Writer | `llama3.2:3b` | ~2.0 GB | Meta's English-optimized training produces noticeably more natural podcast narrative than qwen at any size |

*qwen2.5:7b overflows 4GB VRAM → CPU offloading (~8 tok/sec). Acceptable since the pipeline runs in the morning with no time constraint.

**Estimated daily cost: $0.00** (local inference only)

**Per-agent model override**: Each agent reads its model from env (`CURATOR_LOCAL_MODEL`, `SUMMARIZER_LOCAL_MODEL`, `SCRIPT_LOCAL_MODEL`) and passes it as `local_model_override` to `chat()`. Global `LOCAL_LLM_MODEL` is the fallback default.

To pull models (if not already downloaded):
```bash
ollama pull qwen2.5:3b
ollama pull llama3.2:3b
# qwen2.5:7b — already installed
```

### Anthropic API (fallback — set USE_LOCAL_LLM=false in .env)

| Agent | Model | Reason |
|-------|-------|--------|
| Curator | Claude Haiku 4.5 | Structured JSON, cheap |
| Summarizer | Claude Haiku 4.5 | Structured prompts compensate for smaller model |
| Script Writer | Claude Sonnet 4.5 | Voice consistency, SSML, narrative flow |

**Estimated daily API cost: ~$0.17/day (~$5/month)**

---

## 1. Newsletter Source Registry

These are **verified sender addresses** extracted from the user's Gmail inbox (rushilmisc77@gmail.com) on Feb 20, 2026.

### Active Sources

| ID | Newsletter | Sender Email | Display Name | Frequency | Priority | MIME Type |
|----|-----------|-------------|-------------|-----------|----------|-----------|
| `tldr_ai` | TLDR AI | `dan@tldrnewsletter.com` | TLDR AI | Daily ~2:30 PM UTC | P0 | multipart/alternative |
| `tldr_tech` | TLDR Tech | `dan@tldrnewsletter.com` | TLDR | Daily ~12:00 PM UTC | P1 | multipart/alternative |
| `tldr_dev` | TLDR Dev | `dan@tldrnewsletter.com` | TLDR Dev | Daily ~12:15 PM UTC | P2 | multipart/alternative |
| `techcrunch` | TechCrunch Daily | `newsletters@techcrunch.com` | TechCrunch Daily News | 2x/day (11 AM + 6 PM EST) | P0 | multipart/alternative |
| `harper_carroll` | Harper Carroll AI | `hai@harpercarrollai.com` | Harper Carroll AI | Weekly (Wed/Thu) | P0 | multipart/alternative → **use text/plain part** |
| `ettech` | ETtech Top 5 | `newsletter@ettech.com` | ETtech Top 5 | Daily ~8:30 PM IST | P1 | multipart/mixed |
| `et_ai` | ET AI | `newsletter@economictimesnews.com` | ET AI | Daily ~7:45 AM IST | P1 | multipart/mixed |

### Excluded Sources (same senders, different variants)

| Sender | Variant | Detection | Action |
|--------|---------|-----------|--------|
| `dan@tldrnewsletter.com` | TLDR Crypto | Body contains `"TLDR CRYPTO"` | **SKIP** |
| `dan@tldrnewsletter.com` | TLDR Fintech | Body contains `"TLDR FINTECH"` | **SKIP** |
| `newsletter@economictimesnews.com` | ET general/promos | Display name is `"The Economic Times"` (not `"ET AI"`) | **SKIP** |

### Variant Detection Rules

**TLDR family** (all from `dan@tldrnewsletter.com`):
```python
import re

TLDR_VARIANT_PATTERN = re.compile(r'TLDR\s+(AI|DEV|CRYPTO|FINTECH)?\s*\d{4}-\d{2}-\d{2}')

# Use From display name — simpler and more reliable than body regex
# Confirmed from real email: "TLDR AI <dan@tldrnewsletter.com>"

def detect_tldr_variant(from_display_name: str) -> str | None:
    name = from_display_name.upper()
    if "TLDR AI" in name:        return "tldr_ai"
    if "TLDR DEV" in name:       return "tldr_dev"
    if "TLDR CRYPTO" in name:    return None   # skip
    if "TLDR FINTECH" in name:   return None   # skip
    if "TLDR FOUNDERS" in name:  return None   # skip
    if "TLDR" in name:           return "tldr_tech"  # plain "TLDR" = Tech edition
    return None

ALLOWED_TLDR_VARIANTS = {"tldr_ai", "tldr_tech", "tldr_dev"}
```

**ET family** (all from `newsletter@economictimesnews.com`):
```python
def detect_et_variant(from_display_name: str, subject: str) -> str | None:
    if "ET AI" in from_display_name or subject.startswith("ET AI:"):
        return "et_ai"
    return None
```

**Harper Carroll promo filter**:
```python
def is_harper_carroll_news(subject: str) -> bool:
    news_keywords = ["what's new in ai", "this week's ai news", "ai news"]
    return any(kw in subject.lower() for kw in news_keywords)
```

---

## 2. Data Models

### `models/enums.py`

```python
from enum import Enum

class Source(str, Enum):
    TLDR_AI = "tldr_ai"
    TLDR_TECH = "tldr_tech"
    TLDR_DEV = "tldr_dev"
    TECHCRUNCH = "techcrunch"
    HARPER_CARROLL = "harper_carroll"
    ETTECH = "ettech"
    ET_AI = "et_ai"

class Priority(str, Enum):
    P0 = "P0"  # Must include — deep dive
    P1 = "P1"  # High priority — standard coverage
    P2 = "P2"  # If space — quick hit
    P3 = "P3"  # Skip

class Category(str, Enum):
    AI_MODELS = "ai_models"
    AI_PRODUCTS = "ai_products"
    FUNDING_MA = "funding_ma"
    INDUSTRY_POLICY = "industry_policy"
    INDIA_TECH = "india_tech"
    PRODUCT_STRATEGY = "product_strategy"
    ENGINEERING = "engineering"
    QUICK_HITS = "quick_hits"
```

### `models/article.py`

```python
from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime
from typing import Optional
from .enums import Source, Priority, Category

class RawArticle(BaseModel):
    id: str = Field(description="UUID")
    title: str
    url: HttpUrl
    source: Source
    sender_email: str
    snippet: str = Field(description="Article summary from newsletter email")
    full_text: Optional[str] = Field(None, description="Full article if scraped")
    section: Optional[str] = Field(None, description="Section within newsletter, e.g. 'Headlines'")
    tags: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(description="Email send time")
    newsletter_date: str = Field(description="e.g. '2026-02-19'")
    read_more_url: Optional[HttpUrl] = Field(None, description="Actual article URL if different from url")
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

class CuratedArticle(BaseModel):
    id: str
    title: str
    url: HttpUrl
    source: Source = Field(description="Best source if merged from multiple")
    all_sources: list[Source] = Field(description="All sources that covered this story")
    priority: Priority
    relevance_score: float = Field(ge=0.0, le=100.0)
    category: Category
    dedup_group_id: Optional[str] = Field(None, description="Groups merged duplicates")
    estimated_podcast_duration_sec: int
    snippet: str
    full_text: Optional[str] = None
    discussion_hooks: list[str] = Field(default_factory=list, description="Interview-ready insights")

class ArticleSummary(BaseModel):
    article_id: str
    title: str
    source: Source
    priority: Priority
    category: Category
    summary_text: str
    key_takeaways: list[str]
    discussion_points: list[str] = Field(description="For PM interview prep")
    related_article_ids: list[str] = Field(default_factory=list)
    word_count: int
```

### `models/podcast.py`

```python
from pydantic import BaseModel, Field
from typing import Optional

class Segment(BaseModel):
    id: str
    title: str
    segment_type: str = Field(description="cold_open | intro | ai_updates | funding | india_tech | product_strategy | quick_hits | closing")
    content_ssml: str = Field(description="SSML-annotated script text")
    content_plain: str = Field(description="Plain text (for TTS that don't support SSML)")
    duration_estimate_sec: int
    source_article_ids: list[str] = Field(default_factory=list)

class PodcastScript(BaseModel):
    episode_number: int
    date: str
    total_estimated_duration_min: int
    segments: list[Segment]
    top_takeaways: list[str] = Field(description="3 discussion-ready points for closing")

class Episode(BaseModel):
    episode_number: int
    date: str
    duration_sec: int
    file_path: str
    file_size_bytes: int
    article_count: int
    sources_used: list[str]
```

---

## 3. Config Files

### `config/senders.yaml`

```yaml
senders:
  - id: tldr_ai
    sender_email: dan@tldrnewsletter.com
    variant_detection: body_contains
    variant_pattern: "TLDR AI"
    priority_default: P0
    parser: tldr

  - id: tldr_tech
    sender_email: dan@tldrnewsletter.com
    variant_detection: body_contains
    variant_pattern: "TLDR \\d{4}"
    variant_exclude: ["TLDR AI", "TLDR DEV", "TLDR CRYPTO", "TLDR FINTECH"]
    priority_default: P1
    parser: tldr

  - id: tldr_dev
    sender_email: dan@tldrnewsletter.com
    variant_detection: body_contains
    variant_pattern: "TLDR DEV"
    priority_default: P2
    parser: tldr

  - id: techcrunch
    sender_email: newsletters@techcrunch.com
    variant_detection: none
    priority_default: P0
    parser: techcrunch

  - id: harper_carroll
    sender_email: hai@harpercarrollai.com
    variant_detection: subject_filter
    subject_keywords: ["what's new in ai", "this week's ai news", "ai news"]
    priority_default: P0
    parser: harper_carroll

  - id: ettech
    sender_email: newsletter@ettech.com
    variant_detection: none
    priority_default: P1
    parser: ettech

  - id: et_ai
    sender_email: newsletter@economictimesnews.com
    variant_detection: from_display_name
    display_name_match: "ET AI"
    subject_prefix: "ET AI:"
    priority_default: P1
    parser: et_ai

excluded_variants:
  - sender: dan@tldrnewsletter.com
    patterns: ["TLDR CRYPTO", "TLDR FINTECH", "TLDR FOUNDERS"]
  - sender: newsletter@economictimesnews.com
    exclude_display_names: ["The Economic Times"]
```

### `config/preferences.yaml`

```yaml
user_profile:
  role: "Software Developer transitioning to AI Product Manager"
  interests:
    - AI model releases and capabilities
    - AI product launches and strategy
    - Funding and M&A in AI space
    - Product management frameworks and case studies
    - India AI ecosystem and startups
    - SaaS disruption by AI
    - Developer tools with product implications

priority_rules:
  P0_must_include:
    - "Major AI model releases (GPT, Claude, Gemini, Llama, open source)"
    - "AI product launches from major companies"
    - "Funding rounds > $50M in AI"
    - "AI regulation and policy changes"
    - "Product teardowns and PM case studies"
    - "India AI ecosystem developments (summit, startups, policy)"

  P1_high:
    - "AI startup launches and pivots"
    - "Developer tools with product implications"
    - "Industry trend analysis pieces"
    - "Notable acquisitions in tech"
    - "India tech/IT industry shifts (IT stock impact, outsourcing changes)"
    - "SaaS disruption stories"

  P2_if_space:
    - "Smaller funding ($10-50M)"
    - "Engineering deep dives (interesting but niche)"
    - "Cloud/infra news"
    - "Open-source milestones"

  P3_skip:
    - "Pure code tutorials with no strategic angle"
    - "Crypto/Web3 (unless AI intersection)"
    - "Consumer hardware (unless AI-powered)"
    - "Generic career advice"
    - "Sponsor/ad content within newsletters"

dedup:
  url_match: true
  title_similarity_threshold: 0.85
  content_similarity_threshold: 0.90
  source_priority_order:
    - harper_carroll
    - et_ai
    - ettech
    - techcrunch
    - tldr_ai
    - tldr_tech
    - tldr_dev

time_budget:
  target_duration_min: 90
  p0_deep_dive:
    duration_min_per_article: 5-7
    max_articles: 6
    total_max_min: 35
  p1_standard:
    duration_min_per_article: 2-3
    max_articles: 12
    total_max_min: 30
  p2_quick_hit:
    duration_sec_per_article: 30-60
    max_articles: 15
    total_max_min: 12
  overhead:
    intro_min: 2
    transitions_min: 5
    closing_min: 5
```

### `config/tts_config.yaml`

```yaml
primary:
  provider: chatterbox
  model: ResembleAI/Chatterbox
  params:
    cfgw: 0.5
    exaggeration: 0.4
    temperature: 0.7
    max_chars_per_call: 300
  voice_reference: null

fallback:
  provider: elevenlabs
  model: eleven_turbo_v2_5
  voice_id: "josh"
  params:
    stability: 0.5
    similarity_boost: 0.75
    max_chars_per_call: 5000

output:
  format: mp3
  bitrate: 128k
  sample_rate: 44100
  silence_between_segments_ms: 1500
  silence_between_articles_ms: 800
  normalize_loudness: true
  target_lufs: -16
```

---

## 4. Parsers

All parsers inherit from `BaseParser` and return `list[RawArticle]`.

### `parsers/base_parser.py`

```python
from abc import ABC, abstractmethod
from models.article import RawArticle

class BaseParser(ABC):
    @abstractmethod
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        pass

    def _clean_url(self, url: str) -> str:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        clean_params = {k: v for k, v in params.items() if not k.startswith('utm_')}
        clean_query = urlencode(clean_params, doseq=True)
        return urlunparse(parsed._replace(query=clean_query))
```

### Parser: TLDR (`parsers/tldr_parser.py`)

**Confirmed email structure** (verified from real Gmail fetch, Mar 6 2026):

The Gmail MCP returns the `text/plain` part of the `multipart/alternative` email.
The plain text part is well-structured and is the correct part to parse —
not the HTML part. BeautifulSoup is NOT needed for TLDR.

**Article pattern:**
```
ARTICLE TITLE (X MINUTE READ) [N]

Summary paragraph in 1-4 sentences.

NEXT ARTICLE TITLE (X MINUTE READ) [N]

Next summary...
```

**Section headers (emoji-prefixed, all caps):**
- `🚀 HEADLINES & LAUNCHES`
- `🧠 DEEP DIVES & ANALYSIS`
- `🧑‍💻 ENGINEERING & RESEARCH`
- `🎁 MISCELLANEOUS`
- `⚡ QUICK LINKS`

**Links block at bottom of email:**
```
[1] https://tldr.tech/ai?utm_source=tldrai
[5] https://links.tldrnewsletter.com/Ioj8ZH   ← redirect URL, follow it
[6] https://the-decoder.com/chatgpt-users...   ← direct URL
```

**Key implementation notes:**
- Parse link number from article title: `re.search(r'\[(\d+)\]', title_line)`
- Build a `links_map: dict[int, str]` from the bottom links block first, then resolve
- Some links go via `links.tldrnewsletter.com` redirects — scraper follows these automatically
- Skip sponsors: title line contains `(SPONSOR)`
- Stop parsing articles at: `"Love TLDR?"` line
- QUICK LINKS section articles have no summary paragraph — just title + link number
- Strip `utm_source=tldrai` params via `_clean_url()` in BaseParser
...
```

**Sections observed**: `HEADLINES & LAUNCHES`, `DEEP DIVES & ANALYSIS`, `ENGINEERING & RESEARCH`, `MISCELLANEOUS`, `QUICK LINKS`

**Links**: Appear at bottom as `[1] https://...`, `[2] https://...` etc.

**Key implementation notes**:
- Articles follow pattern: `TITLE (X MINUTE READ) [number]` followed by summary paragraph
- The link number maps to the URL in the links section at the bottom
- Sponsor blocks contain `(SPONSOR)` in the title — **always skip these**
- "Love TLDR?" section marks end of articles
- Quick Links section has articles but shorter summaries

### Parser: TechCrunch (`parsers/techcrunch_parser.py`)

**Observed structure**:
```
TechCrunch Top 3

Article Title : One sentence summary. Read More

Morning Must-Reads (or "Afternoon Must-Reads")

Article Title : One sentence summary. Read More
...

Last but Not Least
Article Title : Summary. Read More
```

**Key implementation notes**:
- "Top 3" section has the highest-priority stories
- "Must-Reads" is the main content section
- "Last but Not Least" is usually 1 article, lower priority
- Sponsor blocks say "A message from [sponsor]" — **skip these**
- URLs are embedded in "Read More" links
- Morning and afternoon editions have identical structure

### Parser: Harper Carroll (`parsers/harper_carroll_parser.py`)

**MIME type**: `text/plain` — same as TLDR. Use the plain text part, not HTML.

**Verified email structure** (from real emails, Feb 26 and Mar 4 2026):

```
*****************
What's New in AI?
*****************

-----------
Top Stories
-----------

1. Article Title (
https://822c1333.click.kit-mail3.com/.../aHR0cHM6Ly93d3cu...
) — One to two sentence description.

2. Article Title (https://tracking.url) — Description inline.

--------------------
Major Model Releases
--------------------

Title (
https://tracking.url
) — Description.

-----------------
AI Agents & Tools       ← section names vary week to week
-----------------

------------------
Business & Funding
------------------

-------------------------------
What Happened with the Pentagon   ← editorial deep-dive sections
-------------------------------

Multi-paragraph analysis with inline links...

Have a great week! If you find this useful...   ← STOP here
```

**Key structural facts**:
1. **Top Stories are numbered** (`1.`, `2.`, ...); all other sections are unnumbered
2. **URLs are Kit tracking redirects** — real URL is base64-encoded at the end of the path:
   ```python
   b64 = tracking_url.rstrip('/').split('/')[-1]
   real_url = base64.b64decode(b64 + '==').decode('utf-8')
   ```
3. **Section names vary week to week** — parse all dash-bordered headers dynamically; do not hardcode section names
4. **"What Happened with X" sections** are Harper Carroll's own editorial deep-dives — high podcast value; extract any inline links found within them
5. **Stop marker**: `"Have a great week!"` — stop parsing at this line
6. **Subject filter**: subjects contain `"this week"` or `"what's new in ai"` (already configured in senders.yaml)

**Implementation notes**:
- Section header = line of `---` + section name + line of `---` (three consecutive lines)
- Article entry: `Title (URL_or_newline) — description` — URL may span multiple lines within parens
- `extraction_confidence = 0.85` (structured plain text)
- WEEKLY — articles may be 2–7 days old; dedup against daily sources handles freshness

### Parser: ETtech (`parsers/ettech_parser.py`)

**Observed structure**:
```
Daily Top 5
A closer look at today's biggest tech and startup stories...

[Story 1 headline + teaser paragraph + Read More link]
...
```

**Key implementation notes**:
- Exactly 5 stories per edition
- MIME type is `multipart/mixed`
- India-focused: Indian startups, IT industry, India government policy
- Full article behind paywall — use snippet + title if scrape fails

### Parser: ET AI (`parsers/et_ai_parser.py`)

**Observed structure**:
```
Good morning Reader,
In today's newsletter:
[Headline 1..N]

[Story 1: Headline + teaser + Read More]
...
```

**Key implementation notes**:
- **Must filter by**: From display name = `"ET AI"` OR subject starts with `"ET AI:"`
- MIME type is `multipart/mixed`
- Has a "table of contents" at top listing headlines, then full teasers below
- Subject line format: `"ET AI: [main headline]"`
- Also behind ET paywall — similar scraping constraints as ETtech

---

## 5. Article Scraper

### The Problem

Every newsletter is "teaser + Read More link" format. Without scraping, the Summarizer summarizes already-summarized content — resulting in shallow podcast segments.

### Two-Phase Architecture

```
Phase A (in Ingestion Agent):
  Email HTML → Parse → Extract {title, snippet, url} per article

Phase B (after Curator, before Summarizer):
  For P0 and P1 articles only → Fetch full article from URL → Clean text → Attach to CuratedArticle.full_text
```

Why scrape after curation: ingestion yields ~60-80 articles, curation filters to ~25-35. Only scrape what you'll use.

### `scraper/article_scraper.py`

```python
import trafilatura
import requests
from newspaper import Article as NewspaperArticle

class ArticleScraper:
    def __init__(self, timeout: int = 10, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; NewsFlowAI/1.0)'
        })

    def scrape(self, url: str) -> str | None:
        text = self._try_trafilatura(url)
        if text and len(text) > 200:
            return text
        text = self._try_newspaper(url)
        if text and len(text) > 200:
            return text
        return None

    def _try_trafilatura(self, url: str) -> str | None:
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                return trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        except Exception:
            return None

    def _try_newspaper(self, url: str) -> str | None:
        try:
            article = NewspaperArticle(url)
            article.download()
            article.parse()
            return article.text if article.text else None
        except Exception:
            return None
```

### Known Scraping Challenges

| Source | Challenge | Mitigation |
|--------|-----------|------------|
| economictimes.com | Soft paywall | Use snippet if scrape fails |
| techcrunch.com | Generally scrapable | trafilatura works well |
| TLDR link redirects | `links.tldrnewsletter.com/xxxx` redirects | Follow redirects (requests does by default) |
| Rate limiting | Too many requests to same domain | 1-2 sec delay between same-domain requests |
| arxiv.org papers | PDF-heavy | Use TLDR/Harper Carroll description instead |

---

## 6. Agent 1: Ingestion

### Responsibility
Connect to Gmail, fetch newsletters from the 4 sender addresses, detect variants, parse HTML into RawArticle objects.

### Gmail API Query

```python
GMAIL_QUERY = (
    "from:(dan@tldrnewsletter.com OR newsletters@techcrunch.com "
    "OR hai@harpercarrollai.com OR newsletter@ettech.com "
    "OR newsletter@economictimesnews.com) "
    "newer_than:1d"
)
```

### Process Flow

```
1. Authenticate Gmail API (OAuth 2.0, auto-refresh tokens)
2. Query inbox with GMAIL_QUERY
3. For each email:
   a. Extract sender_email, from_display_name, subject, date, body
   b. Route to variant detector
   c. If variant is excluded → skip
   d. Route to appropriate parser based on source ID
   e. Parser returns list[RawArticle]
4. Flatten all articles into single list
5. Deduplicate by exact URL
6. Save to workspace/{date}/raw_articles.json
7. Apply Gmail label "NewsFlow/Processed" to processed emails
8. Save checkpoint: last processed email ID per sender
```

### Error Handling

- Gmail API 429: exponential backoff, max 3 retries
- OAuth token expired: auto-refresh; if refresh fails → Telegram alert
- HTML parse failure: log error, skip article, continue
- Empty email body: skip

---

## 7. Agent 2: Curator

### Responsibility
Deduplicate articles across all 7 sources. Classify priority and category. Rank by relevance. Enforce time budget.

### Dedup Pipeline

```
Step 1: URL Dedup (fast, catches ~60%)
  - Normalize URLs: strip utm params, trailing slashes, www prefix
  - Group identical normalized URLs
  - Keep the version from the highest-priority source

Step 2: Title Similarity (catches ~25% more)
  - Embed all titles using all-MiniLM-L6-v2
  - Compute pairwise cosine similarity
  - Merge if similarity > 0.85

Step 3: Content Similarity (catches remaining ~15%)
  - Embed snippets using all-MiniLM-L6-v2
  - Merge if similarity > 0.90
```

### LLM Classification (Claude Haiku 4.5)

```
System: You are a content classifier for an AI-focused news podcast.
The listener is a software developer transitioning to AI Product Manager.

Classify this article:
Title: {title}
Source: {source}
Snippet: {snippet}

Return JSON:
{
  "priority": "P0" | "P1" | "P2" | "P3",
  "category": "ai_models" | "ai_products" | "funding_ma" | "industry_policy" | "india_tech" | "product_strategy" | "engineering" | "quick_hits",
  "relevance_score": 0-100,
  "discussion_hooks": ["1-2 sentence insight for PM interviews"],
  "estimated_podcast_seconds": 30-420
}
```

**Batch classification**: Send 5-10 articles per Haiku call to reduce API overhead.

### Time Budget Enforcement

1. Sort P0 by relevance_score desc → take top 6
2. Sort P1 by relevance_score desc → fill remaining time up to 30 min
3. Sort P2 by relevance_score desc → fill remaining time up to 12 min
4. Discard anything that doesn't fit

### Output

Save `workspace/{date}/curated_articles.json`

---

## 8. Agent 3: Summarizer

### Model
**Claude Haiku 4.5** — switched from Sonnet 4.5 to reduce cost (~8x cheaper).
Haiku handles structured, tiered summaries well when prompts enforce explicit output format and word count.
Quality difference vs Sonnet is minimal for P1/P2. For P0, the structured prompt scaffolding compensates effectively.

### Scrape Full Articles First

```python
for article in curated_articles:
    if article.priority in (Priority.P0, Priority.P1) and not article.full_text:
        article.full_text = scraper.scrape(str(article.url))
```

### Summary Generation (Claude Haiku 4.5)

**P0 Deep Dive** (300-500 words):
```
System: Write a podcast-ready summary for an AI tech podcast.
The listener is an SDE transitioning to AI PM.
Be concise and direct. This will be spoken aloud. Short sentences. Active voice.

Article: {title}
Source: {source}
Full Text: {full_text or snippet}

Write a 300-500 word summary using EXACTLY this structure — no deviations:
1. CONTEXT: What's the landscape/background (1-2 sentences)
2. WHAT HAPPENED: The core news (2-3 sentences)
3. WHY IT MATTERS: Impact and implications (2-3 sentences)
4. KEY TAKEAWAY: One sentence the listener should remember
5. DISCUSSION POINT: One insight they could bring up in a PM interview

Rules:
- Use short sentences and active voice throughout
- No jargon without explanation
- Write for ears, not eyes — no bullet points in output
- Stay within 300-500 words strictly
```

**P1 Standard** (100-200 words):
```
System: Write a podcast-ready summary. Short sentences. Active voice. Spoken aloud.

Article: {title}
Source: {source}
Content: {full_text or snippet}

Write a 100-200 word summary using EXACTLY this structure:
1. WHAT HAPPENED (1-2 sentences)
2. WHY IT MATTERS (1-2 sentences)
3. KEY TAKEAWAY (1 sentence)

Stay within word count strictly. No bullet points.
```

**P2 Quick Hit** (30-50 words):
```
Write a single 30-50 word paragraph covering what happened and why it matters.
One flowing sentence or two short ones. No headers. Spoken aloud.

Article: {title}
Snippet: {snippet}
```

> **Haiku prompting tip**: Unlike Sonnet, Haiku benefits from more explicit constraints in the prompt (word counts, structure labels, "no deviations"). The structured format above was designed to get reliable output from Haiku without quality drop.

### Topic Clustering

Group summaries by `Category` enum. Podcast segment order:
1. `ai_models` + `ai_products` → "AI Updates"
2. `funding_ma` → "Funding & Business"
3. `india_tech` → "India Tech"
4. `product_strategy` + `industry_policy` → "Product & Strategy"
5. `engineering` + `quick_hits` → "Quick Hits"

### Output

Save `workspace/{date}/summaries.json`

---

## 9. Agent 4: Script Writer

### Model
**Claude Sonnet 4.5** — retained. Voice consistency, natural transitions, SSML generation, and 90-minute narrative flow require Sonnet's capability. This is the one step where quality directly impacts listenability.

### Script Structure

| Segment | Duration | Content |
|---------|----------|---------|
| Cold Open | 30 sec | Hook with the single most interesting story |
| Intro | 2 min | "Good morning! It's [date]. Here's what you need to know..." + preview top 3 |
| AI Updates | 15-25 min | P0 and P1 AI model/product stories |
| Funding & Business | 10-15 min | Investment, M&A, startup news |
| India Tech | 5-10 min | ETtech and ET AI stories |
| Product & Strategy | 10-15 min | PM insights, case studies, SaaS disruption |
| Quick Hits | 5-10 min | P2 rapid-fire roundup |
| Closing | 3-5 min | "3 things to remember" + sign-off |

### LLM Prompt (Claude Sonnet 4.5)

```
System: You are the script writer for "NewsFlow" — a daily AI tech podcast.
Write for a single host narrating to a listener who's at the gym.

Voice guidelines:
- Conversational, like a smart colleague briefing you over coffee
- Use verbal signposts: "First up...", "Now here's where it gets interesting...", "Moving on to funding..."
- Short sentences. Active voice. No jargon without explanation.
- Include natural pauses (mark with <break time="500ms"/> for segment transitions)
- End each P0 story with: "If someone asks you about this, here's the key point: [insight]"
- Quick hits should be rapid-fire: "In quick hits today: [story], [story], and [story]."

Input summaries: {summaries_json}

Write the complete script following this segment order:
1. Cold Open (hook the listener)
2. Intro (date, overview)
3. AI Updates segment
4. Funding & Business segment
5. India Tech segment
6. Product & Strategy segment
7. Quick Hits segment
8. Closing (3 takeaways + sign-off)

Output as JSON matching the PodcastScript model.
Include both content_ssml (with SSML markers) and content_plain (without).
```

---

## 10. Agent 5: Audio Producer

### Responsibility
Convert podcast script to MP3 audio file.

### TTS Strategy

**Primary: Chatterbox TTS** (free, via HuggingFace)
- Max 300 chars per call → aggressive chunking required
- Split by sentence boundaries
- Returns wav numpy array → convert to MP3 with pydub

**Fallback: ElevenLabs** (paid, higher quality)
- Max 5000 chars per call
- Use if Chatterbox quality is insufficient or HF Space is down

### Process Flow

```
1. Load podcast_script.json
2. For each segment:
   a. Split content_plain into chunks (≤300 chars for Chatterbox)
   b. Chunk at sentence boundaries ('. ', '! ', '? ')
   c. Send each chunk to TTS
   d. Collect audio segments
3. Concatenate all audio:
   a. 1500ms silence between segments
   b. 800ms silence between articles within a segment
4. Post-process:
   a. Normalize loudness to -16 LUFS
   b. Export as MP3 128kbps 44.1kHz
5. Add ID3 tags: Title, Episode number, Duration
6. Save to workspace/{date}/episode_{number}.mp3
```

### Audio Quality Checks

- Duration within 60-90 min range (alert if outside)
- No silence gaps > 3 seconds (indicates TTS failure)
- File size reasonable (~60-100 MB for 90 min at 128kbps)

---

## 11. Pipeline Orchestrator

### `orchestrator/pipeline.py`

```python
class NewsFlowPipeline:
    def run(self, date: str = None):
        date = date or datetime.now().strftime("%Y-%m-%d")
        workspace = f"workspace/{date}"
        os.makedirs(workspace, exist_ok=True)

        raw_articles = IngestionAgent().run()
        save_json(raw_articles, f"{workspace}/raw_articles.json")
        log.info("ingestion_complete", count=len(raw_articles))

        curated = CuratorAgent().run(raw_articles)
        save_json(curated, f"{workspace}/curated_articles.json")
        log.info("curation_complete", count=len(curated))

        scraper = ArticleScraper()
        for article in curated:
            if article.priority in ("P0", "P1"):
                article.full_text = scraper.scrape(str(article.url))
        save_json(curated, f"{workspace}/curated_articles_enriched.json")

        summaries = SummarizerAgent().run(curated)
        save_json(summaries, f"{workspace}/summaries.json")
        log.info("summarization_complete", count=len(summaries))

        script = ScriptWriterAgent().run(summaries, date)
        save_json(script, f"{workspace}/podcast_script.json")
        log.info("script_complete", duration_min=script.total_estimated_duration_min)

        episode = AudioProducerAgent().run(script, workspace)
        save_json(episode, f"{workspace}/episode_metadata.json")
        log.info("episode_complete", duration_sec=episode.duration_sec, path=episode.file_path)

        return episode
```

### Checkpoint & Recovery

Each stage saves output to workspace. Re-run checks for existing checkpoint files, skips completed stages, resumes from last incomplete stage.

---

## 12. Delivery

### Telegram Bot
- Send MP3 file link + episode summary when pipeline completes
- Accept feedback: 👍/👎 reaction on each episode
- Alert if pipeline fails or is late (deadline: 6:00 AM IST)

### Podcast RSS Feed
- Generate RSS XML with enclosure pointing to MP3 file
- Host on S3 or local server
- Subscribe in any podcast app (Apple Podcasts, Spotify, etc.)

---

## 13. Phase Implementation Plan

### Phase 1: MVP — Gmail to Summary (Week 1-2)

Active sources: **TLDR AI, TLDR Tech, TLDR Dev, TechCrunch, Harper Carroll**

```
Build order:
1.  models/enums.py + models/article.py + models/podcast.py
2.  config/senders.yaml (enabled flags: harper_carroll=true, ettech/et_ai=false)
3.  config/preferences.yaml (new priority rules + user profile)
4.  parsers/base_parser.py
5.  parsers/tldr_parser.py
6.  parsers/techcrunch_parser.py
7.  parsers/harper_carroll_parser.py  ← plain text, dash-bordered sections
8.  parsers/generic_parser.py         ← BS4 fallback for NEWSLETTER_SENDERS env
9.  agents/ingestion.py               ← config-driven GMAIL_QUERY + parser registry
10. mcp_servers/article_fetcher_server.py  ← FastMCP fetch_article
11. utils/llm_client.py               ← local_model_override param
12. agents/curator.py                 ← new categories + CURATOR_LOCAL_MODEL
13. agents/summarizer.py              ← dual-lens prompts + MCP fetch + SUMMARIZER_LOCAL_MODEL
14. agents/script_writer.py           ← SCRIPT_LOCAL_MODEL
15. Basic TTS test with gTTS (validates flow only)
16. orchestrator/pipeline.py

Test with: Save real emails as plain text fixtures in tests/fixtures/
```

**Deliverable**: Working pipeline producing a rough MP3 from TLDR + TechCrunch + Harper Carroll.

### Phase 2: ET Sources + Quality Upgrade (Week 3-4)

Active sources added: **ET Tech, ET AI** (via Inc42 fallback strategy)

```
Build order:
1. parsers/ettech_parser.py + parsers/et_ai_parser.py
2. ET paywall strategy: extract title from email → query Inc42.com directly
   (do NOT follow ET links — paywall); MCP search_and_fetch for fallback
3. mcp_servers/article_fetcher_server.py: add search_and_fetch tool
4. agents/curator.py upgrade: semantic dedup with all-MiniLM-L6-v2
5. agents/script_writer.py (full SSML + segment transitions)
6. agents/audio_producer.py (Chatterbox TTS via HuggingFace)
7. Audio post-processing (pydub + ffmpeg normalization)
8. config/tts_config.yaml + ElevenLabs fallback
9. Enable ettech + et_ai in senders.yaml
```

**Deliverable**: Full 7-source pipeline with polished, gym-ready podcast.

### Phase 3: Automation & Delivery (Week 5-6)

```
Build order:
1. orchestrator/scheduler.py (cron 5:00 AM IST)
2. Checkpoint/recovery logic
3. delivery/telegram_bot.py
4. delivery/rss_feed.py
5. Monitoring: cost tracking, article counts, duration checks
6. Error alerting via Telegram
```

**Deliverable**: Wake up, open podcast app, listen. Zero manual steps.

### Phase 4: Intelligence (Week 7+)

```
- Feedback loop: thumbs up/down adjusts relevance scoring weights
- Trend detection: "this is the 3rd day we're covering OpenAI funding..."
- Weekend digest mode: longer, more analytical, covers the full week
- Web scraping improvements: handle paywalls, caching, rate limiting
- A/B test script styles and segment ordering
```

---

## 14. Evaluation & Monitoring

### Agent-Level Metrics

| Agent | Metric | Target | How to Test |
|-------|--------|--------|-------------|
| Ingestion | Extraction accuracy | >95% articles found | Weekly audit vs manually reading 10 emails |
| Ingestion | Variant detection | >99% correct | Check TLDR classification on 20 emails |
| Ingestion | Parse success rate | >98% valid JSON | Pydantic validation on output |
| Curator | Dedup precision | >90% correct merges | Manual review of 10 merge decisions/week |
| Curator | Relevance accuracy | >85% agree with human | Rate 20 articles/week, compare P0/P1/P2 |
| Summarizer | Factual accuracy | Zero hallucinations | Spot-check 5 summaries/day vs source |
| Summarizer | Completeness | Key facts preserved | Checklist: what/why/impact captured? |
| Summarizer | Haiku quality | >3.5/5 avg rating | Weekly self-rating on summary usefulness |
| Script Writer | Listenability | >4/5 rating | Weekly self-rating on naturalness |
| Script Writer | Discussion hooks | >3 per episode | Count actionable PM interview insights |
| Audio | Quality | No artifacts | Listen for glitches, unnatural pauses |
| Audio | Duration | 60-90 min | Automated MP3 duration check |

> **Haiku quality monitoring note**: Add a weekly review step where you compare 3-5 Haiku-generated P0 summaries against what Sonnet would produce. If quality gap becomes noticeable over time, P0 summaries can be selectively upgraded back to Sonnet (~$0.10/day incremental cost).

### Automated Alerts (via Telegram)

- Pipeline not complete by 6:00 AM IST
- Daily cost exceeds $1 (up from $5 — tighter budget now)
- Article count drops below 20
- TTS produces audio shorter than 30 minutes
- Any agent throws unhandled exception

### Cost Tracking

| Component | Expected Daily Cost |
|-----------|-------------------|
| Claude Haiku 4.5 (classification + all summaries) | ~$0.09 |
| Claude Sonnet 4.5 (script writing only) | ~$0.08 |
| Chatterbox TTS (HuggingFace) | $0.00 (free) |
| Embeddings (local MiniLM) | $0.00 (free) |
| Article scraping | $0.00 (free) |
| Gmail API | $0.00 (free) |
| **Total** | **~$0.17/day (~$5/month)** |

**vs original design**: ~$0.65/day → **74% cost reduction**

If using ElevenLabs fallback instead of Chatterbox: add ~$1.50/day.

> **Escape hatch**: If Haiku summary quality proves insufficient for P0 deep dives after a week of real use, upgrade P0 summaries only back to Sonnet. Cost impact: +~$0.08/day → ~$0.25/day total. Still 60% cheaper than the original design.