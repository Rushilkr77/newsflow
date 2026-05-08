"""
Agent 3: Summarizer
Fetches full article content via the MCP article fetcher, then generates tiered
summaries with structured coverage factors mapped to script-writer needs.

Model: qwen2.5:7b (via SUMMARIZER_LOCAL_MODEL env var) — better section discipline
and word-count adherence than 3B for the structured P0/P1 prompts.

Summary structure:
  P0 (400-500 words): CORE NEWS → SURROUNDING IMPACT → COMPETITOR CONTEXT →
                      LAUNCH RATIONALE → HOW IT WORKS → PM INTERVIEW EDGE
  P1 (150-200 words): CORE NEWS + IMPACT → HOW + WHY → PM EDGE
  P2 (60-80 words):   CORE NEWS → PM EDGE  (enough for a ~30-second mention)
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import structlog

from mcp_servers.article_fetcher_server import fetch_article_content
from models.article import ArticleSummary, CuratedArticle
from models.enums import Priority, Source
from scraper.ddg_scraper import DDGScraper
from scraper.inc42_scraper import Inc42Scraper
from utils.llm_client import chat

log = structlog.get_logger(__name__)

# Model for summarization (7B for better structured output quality)
_SUMMARIZER_LOCAL_MODEL = os.getenv("SUMMARIZER_LOCAL_MODEL")

# OpenRouter model chain for P0/P1 summarization — tried in order, falls back to local on error.
# Override via comma-separated env var, e.g.:
#   OPENROUTER_SUMMARIZER_MODELS=google/gemini-2.0-flash-exp:free,meta-llama/llama-3.3-70b-instruct:free
_OPENROUTER_SUMMARIZER_MODELS: list[str] = [
    m.strip()
    for m in os.getenv(
        "OPENROUTER_SUMMARIZER_MODELS",
        "openai/gpt-oss-120b:free,nousresearch/hermes-3-llama-3.1-405b:free,meta-llama/llama-3.3-70b-instruct:free",
    ).split(",")
    if m.strip()
]

# Sources whose articles are typically behind the ET paywall
_ET_SOURCES = frozenset({Source.ETTECH, Source.ET_AI})

_inc42_scraper = Inc42Scraper()
_ddg_scraper = DDGScraper()


def _url_domain(url: str) -> str | None:
    """Extract domain from URL for DDG skip-domain hint."""
    try:
        return urlparse(url).netloc.lower().removeprefix("www.") or None
    except Exception:
        return None


class SummarizerAgent:
    def run(self, curated_articles: list[CuratedArticle], partial_path: str | None = None) -> list[ArticleSummary]:
        # Load any already-completed summaries from a prior interrupted run
        summaries: list[ArticleSummary] = []
        done_ids: set[str] = set()
        if partial_path and Path(partial_path).exists():
            with open(partial_path) as f:
                summaries = [ArticleSummary.model_validate(s) for s in json.load(f)]
            done_ids = {s.article_id for s in summaries}
            log.info("summarizer_resuming", already_done=len(done_ids))

        remaining = [a for a in curated_articles if a.id not in done_ids]
        log.info("summarizer_start", total=len(curated_articles), remaining=len(remaining))

        self._fetch_full_text(remaining)

        for article in remaining:
            try:
                summary = self._summarize(article)
                summaries.append(summary)
                if partial_path:
                    with open(partial_path, "w") as f:
                        json.dump([s.model_dump(mode="json") for s in summaries], f, default=str)
            except Exception as e:
                log.error("summary_failed", article_id=article.id, title=article.title, error=str(e))

        log.info("summarizer_complete", summary_count=len(summaries))
        return summaries

    # -------------------------------------------------------------------------
    # Article fetching (via MCP article fetcher)
    # -------------------------------------------------------------------------

    def _fetch_full_text(self, articles: list[CuratedArticle]) -> None:
        """Fetch full article text for all articles in-place."""
        to_fetch = [a for a in articles if not a.full_text]
        log.info("fetching_articles", count=len(to_fetch))

        for article in to_fetch:
            url_str = str(article.url)
            skip_domain = _url_domain(url_str)

            text = fetch_article_content(url_str)
            if text and len(text) >= 200:
                article.full_text = text
                log.debug("article_fetched", article_id=article.id, chars=len(text))
                continue

            if article.source in _ET_SOURCES:
                # ET articles are paywalled — search inc42 first (India tech coverage)
                inc42_text = _inc42_scraper.search_and_fetch(article.title)
                if inc42_text:
                    article.full_text = inc42_text
                    log.info(
                        "inc42_fallback_used",
                        article_id=article.id,
                        title=article.title[:60],
                        chars=len(inc42_text),
                    )
                    continue
                # inc42 missed it — fall through to DDG below

            # General DDG fallback for all sources (inc42 miss or non-ET source)
            ddg_text = _ddg_scraper.search_and_fetch(article.title, skip_domain=skip_domain)
            if ddg_text:
                article.full_text = ddg_text
                log.info(
                    "ddg_fallback_used",
                    article_id=article.id,
                    title=article.title[:60],
                    chars=len(ddg_text),
                )
            else:
                log.debug("fetch_fallback_to_snippet", article_id=article.id)

    # -------------------------------------------------------------------------
    # Summary generation
    # -------------------------------------------------------------------------

    def _summarize(self, article: CuratedArticle) -> ArticleSummary:
        content = article.full_text or article.snippet

        if article.priority == Priority.P0:
            summary_text = self._summarize_p0(article, content)
            summary_text = self._validate_p0_summary(article, content, summary_text)
        elif article.priority == Priority.P1:
            summary_text = self._summarize_p1(article, content)
        else:
            summary_text = self._summarize_p2(article, content)

        word_count = len(summary_text.split())
        key_takeaways = self._extract_key_takeaways(summary_text)
        interview_edges = self._extract_interview_edges(summary_text)

        return ArticleSummary(
            article_id=article.id,
            title=article.title,
            source=article.source,
            priority=article.priority,
            category=article.category,
            summary_text=summary_text,
            key_takeaways=key_takeaways,
            discussion_points=interview_edges or article.discussion_hooks,
            word_count=word_count,
        )

    def _summarize_p0(self, article: CuratedArticle, content: str) -> str:
        prompt = f"""Article: {article.title}
Source: {article.source.value}
Full Text: {content[:6000]}

Write a 400-500 word summary using EXACTLY this structure — label each section:
1. CORE NEWS: What exactly happened — one clear sentence.
2. SURROUNDING IMPACT: Who is affected and how does this shift the broader ecosystem? (2-3 sentences)
3. COMPETITOR CONTEXT: How does this change the competitive landscape? Skip this section if not applicable.
4. LAUNCH RATIONALE: Why did they build/launch this now? What problem does it solve? (2-3 sentences)
5. HOW IT WORKS: The interesting technical detail or implementation approach. (2-3 sentences)
6. PM INTERVIEW EDGE: The non-obvious insight for a Series B+ AI PM interview. What would a strong PM candidate say about this? (2-3 sentences)

Rules:
- Short sentences. Active voice throughout.
- No jargon without a one-phrase explanation
- Write for ears, not eyes — no bullet points in output
- Stay within 400-500 words strictly"""

        return self._call_llm(prompt, max_tokens=4096, use_openrouter=True)

    def _summarize_p1(self, article: CuratedArticle, content: str) -> str:
        prompt = f"""Article: {article.title}
Source: {article.source.value}
Content: {content[:2000]}

Write a 150-200 word summary using EXACTLY this structure — label each section:
1. CORE NEWS + IMPACT: What happened and who it affects. (2-3 sentences)
2. HOW + WHY: Technical approach and launch rationale combined. (2-3 sentences)
3. PM EDGE: One non-obvious insight for an AI PM interview. (1-2 sentences)

Stay within word count strictly. No bullet points. Short sentences."""

        return self._call_llm(prompt, max_tokens=1536, use_openrouter=True)

    def _summarize_p2(self, article: CuratedArticle, content: str) -> str:
        prompt = f"""Article: {article.title}
Snippet: {content[:500]}

Write a 60-80 word summary using EXACTLY this structure — label each section:
1. CORE NEWS: What happened — one clear sentence.
2. PM EDGE: One non-obvious insight for an AI PM interview. (1-2 sentences)

No bullet points. Short sentences. Written to be spoken aloud."""

        return self._call_llm(prompt, max_tokens=768)

    def _validate_p0_summary(
        self, article: CuratedArticle, content: str, summary_text: str
    ) -> str:
        """Validate P0 summary quality; retries once via OpenRouter if below threshold. Retry result is accepted unconditionally."""
        word_count = len(summary_text.split())
        headers = sum(
            1
            for marker in [
                "CORE NEWS",
                "SURROUNDING IMPACT",
                "COMPETITOR CONTEXT",
                "LAUNCH RATIONALE",
                "HOW IT WORKS",
                "PM INTERVIEW EDGE",
            ]
            if marker in summary_text.upper()
        )
        if word_count >= 300 and headers >= 4:
            return summary_text  # passes

        log.info(
            "p0_summary_retry",
            title=article.title[:60],
            word_count=word_count,
            headers=headers,
        )
        retry_prompt = f"""Your previous summary was too short ({word_count} words, target: 400-500) and only had {headers}/6 required sections.

Article: {article.title}
Full Text: {content[:6000]}

You MUST write a 400-500 word summary with ALL SIX sections labeled exactly:
1. CORE NEWS  2. SURROUNDING IMPACT  3. COMPETITOR CONTEXT
4. LAUNCH RATIONALE  5. HOW IT WORKS  6. PM INTERVIEW EDGE

If COMPETITOR CONTEXT doesn't apply, write "Not directly applicable" and move on.
Each section needs 2-3 sentences. Stay within 400-500 words total."""

        return self._call_llm(retry_prompt, max_tokens=4096, use_openrouter=True)

    def _call_llm(
        self, prompt: str, max_tokens: int = 1024, use_openrouter: bool = False
    ) -> str:
        return chat(
            model_hint="claude-haiku-4-5",
            system=(
                "Write podcast-ready summaries for a daily AI/tech news podcast. "
                "The listener is a software engineer building product awareness for AI PM "
                "and developer interviews at Series B+ startups. "
                "Be concise and direct. This will be spoken aloud. Short sentences. Active voice."
            ),
            user=prompt,
            max_tokens=max_tokens,
            local_model_override=_SUMMARIZER_LOCAL_MODEL,
            openrouter_models=_OPENROUTER_SUMMARIZER_MODELS if use_openrouter else None,
        )

    # -------------------------------------------------------------------------
    # Takeaway and interview edge extraction
    # -------------------------------------------------------------------------

    def _extract_key_takeaways(self, summary_text: str) -> list[str]:
        """Extract 3 takeaways from the structured summary headers.

        Pulls the first sentence after CORE NEWS, SURROUNDING IMPACT, and
        PM INTERVIEW EDGE (or PM EDGE for P1/P2). Falls back to first 3
        sentences of the text if headers are absent.
        """
        _TARGET_HEADERS = ("CORE NEWS", "SURROUNDING IMPACT", "PM INTERVIEW EDGE", "PM EDGE")
        takeaways: list[str] = []
        lines = summary_text.splitlines()
        for i, line in enumerate(lines):
            upper = line.strip().upper()
            for header in _TARGET_HEADERS:
                if header in upper:
                    # Content may be on the same line after ":" or on the next line
                    parts = line.strip().split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        first_sentence = parts[1].strip().split(".")[0] + "."
                        takeaways.append(first_sentence)
                    elif i + 1 < len(lines) and lines[i + 1].strip():
                        first_sentence = lines[i + 1].strip().split(".")[0] + "."
                        takeaways.append(first_sentence)
                    break
            if len(takeaways) == 3:
                break

        # Fallback: first 3 sentences of plain text
        if not takeaways:
            sentences = [s.strip() for s in summary_text.replace("\n", " ").split(".") if s.strip()]
            takeaways = [s + "." for s in sentences[:3]]

        return takeaways[:3]

    def _extract_interview_edges(self, summary_text: str) -> list[str]:
        """Extract PM INTERVIEW EDGE or PM EDGE lines from the structured summary."""
        edges = []
        for line in summary_text.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if "PM INTERVIEW EDGE" in upper or "PM EDGE" in upper:
                parts = stripped.split(":", 1)
                if len(parts) > 1 and parts[1].strip():
                    edges.append(parts[1].strip())
                    break
        return edges
