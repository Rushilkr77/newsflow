"""
Agent 3: Summarizer
Fetches full article content via the MCP article fetcher, then generates tiered
summaries with a dual-lens structure (technical + product/market).

Model: qwen2.5:7b (via SUMMARIZER_LOCAL_MODEL env var) — better section discipline
and word-count adherence than 3B for the structured P0/P1 prompts.

Summary structure:
  P0 (300-500 words): CONTEXT → WHAT HAPPENED → TECHNICAL ANGLE →
                      PRODUCT/MARKET ANGLE → KEY TAKEAWAY → INTERVIEW EDGE
  P1 (100-200 words): WHAT HAPPENED → TECHNICAL + PRODUCT ANGLE → KEY TAKEAWAY
  P2 (30-50 words):   Single spoken paragraph (snippet only, no scraping)
"""
import os

import structlog

from mcp_servers.article_fetcher_server import fetch_article_content
from models.article import ArticleSummary, CuratedArticle
from models.enums import Priority, Source
from scraper.inc42_scraper import Inc42Scraper
from utils.llm_client import chat

log = structlog.get_logger(__name__)

# Model for summarization (7B for better structured output quality)
_SUMMARIZER_LOCAL_MODEL = os.getenv("SUMMARIZER_LOCAL_MODEL")

# Sources whose articles are typically behind the ET paywall
_ET_SOURCES = frozenset({Source.ETTECH, Source.ET_AI})

_inc42_scraper = Inc42Scraper()


class SummarizerAgent:
    def run(self, curated_articles: list[CuratedArticle]) -> list[ArticleSummary]:
        log.info("summarizer_start", article_count=len(curated_articles))

        self._fetch_full_text(curated_articles)

        summaries = []
        for article in curated_articles:
            try:
                summary = self._summarize(article)
                summaries.append(summary)
            except Exception as e:
                log.error("summary_failed", article_id=article.id, title=article.title, error=str(e))

        log.info("summarizer_complete", summary_count=len(summaries))
        return summaries

    # -------------------------------------------------------------------------
    # Article fetching (via MCP article fetcher)
    # -------------------------------------------------------------------------

    def _fetch_full_text(self, articles: list[CuratedArticle]) -> None:
        """Fetch full article text for P0 and P1 articles in-place."""
        to_fetch = [
            a for a in articles
            if a.priority in (Priority.P0, Priority.P1) and not a.full_text
        ]
        log.info("fetching_articles", count=len(to_fetch))

        for article in to_fetch:
            text = fetch_article_content(str(article.url))
            if text and len(text) >= 200:
                article.full_text = text
                log.debug("article_fetched", article_id=article.id, chars=len(text))
            elif article.source in _ET_SOURCES:
                # ET articles are often paywalled — try Inc42 as a fallback
                inc42_text = _inc42_scraper.search_and_fetch(article.title)
                if inc42_text:
                    article.full_text = inc42_text
                    log.info(
                        "inc42_fallback_used",
                        article_id=article.id,
                        title=article.title[:60],
                        chars=len(inc42_text),
                    )
                else:
                    log.debug("fetch_fallback_to_snippet", article_id=article.id)
            else:
                log.debug("fetch_fallback_to_snippet", article_id=article.id)

    # -------------------------------------------------------------------------
    # Summary generation
    # -------------------------------------------------------------------------

    def _summarize(self, article: CuratedArticle) -> ArticleSummary:
        content = article.full_text or article.snippet

        if article.priority == Priority.P0:
            summary_text = self._summarize_p0(article, content)
        elif article.priority == Priority.P1:
            summary_text = self._summarize_p1(article, content)
        else:
            summary_text = self._summarize_p2(article)

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
Full Text: {content[:4000]}

Write a 300-500 word summary using EXACTLY this structure — no deviations:
1. CONTEXT: What's the landscape/background (1-2 sentences)
2. WHAT HAPPENED: The core announcement or launch (2-3 sentences)
3. TECHNICAL ANGLE: What's technically interesting or novel (1-2 sentences)
4. PRODUCT/MARKET ANGLE: Why this matters for users and the market (2-3 sentences)
5. KEY TAKEAWAY: One sentence the listener should remember
6. INTERVIEW EDGE: One insight showing both technical depth AND product awareness — useful in a Series B+ startup interview

Rules:
- Short sentences. Active voice throughout.
- No jargon without a one-phrase explanation
- Write for ears, not eyes — no bullet points in output
- Stay within 300-500 words strictly"""

        return self._call_llm(prompt)

    def _summarize_p1(self, article: CuratedArticle, content: str) -> str:
        prompt = f"""Article: {article.title}
Source: {article.source.value}
Content: {content[:2000]}

Write a 100-200 word summary using EXACTLY this structure:
1. WHAT HAPPENED (1-2 sentences)
2. TECHNICAL + PRODUCT ANGLE: Both the technical insight and market/product implication (2-3 sentences)
3. KEY TAKEAWAY (1 sentence)

Stay within word count strictly. No bullet points. Short sentences."""

        return self._call_llm(prompt)

    def _summarize_p2(self, article: CuratedArticle) -> str:
        prompt = f"""Article: {article.title}
Snippet: {article.snippet[:500]}

Write a single 30-50 word paragraph covering what happened and why it matters.
One or two short sentences. No headers. Written to be spoken aloud."""

        return self._call_llm(prompt)

    def _call_llm(self, prompt: str) -> str:
        return chat(
            model_hint="claude-haiku-4-5",
            system=(
                "Write podcast-ready summaries for a daily AI/tech news podcast. "
                "The listener is a software engineer building product awareness for AI PM "
                "and developer interviews at Series B+ startups. "
                "Be concise and direct. This will be spoken aloud. Short sentences. Active voice."
            ),
            user=prompt,
            max_tokens=1024,
            local_model_override=_SUMMARIZER_LOCAL_MODEL,
        )

    # -------------------------------------------------------------------------
    # Takeaway and interview edge extraction
    # -------------------------------------------------------------------------

    def _extract_key_takeaways(self, summary_text: str) -> list[str]:
        """Extract KEY TAKEAWAY lines from the structured summary."""
        takeaways = []
        for line in summary_text.splitlines():
            stripped = line.strip()
            if "KEY TAKEAWAY" in stripped.upper():
                parts = stripped.split(":", 1)
                if len(parts) > 1 and parts[1].strip():
                    takeaways.append(parts[1].strip())
                    break
        if not takeaways and summary_text:
            sentences = [s.strip() for s in summary_text.split(".") if s.strip()]
            if sentences:
                takeaways.append(sentences[-1] + ".")
        return takeaways

    def _extract_interview_edges(self, summary_text: str) -> list[str]:
        """Extract INTERVIEW EDGE lines from the structured P0 summary."""
        edges = []
        for line in summary_text.splitlines():
            stripped = line.strip()
            if "INTERVIEW EDGE" in stripped.upper():
                parts = stripped.split(":", 1)
                if len(parts) > 1 and parts[1].strip():
                    edges.append(parts[1].strip())
                    break
        return edges
