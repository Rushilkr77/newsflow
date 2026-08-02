"""
ScraperAgent: Fetches full article text for a list of articles in-place.

Used in:
  Phase A (GlobalEnrichPipeline): scrape the full deduped pool once globally so
    every per-user Phase B run finds full_text already populated.
  Phase B fallback (SummarizerAgent._fetch_full_text): safety net for articles
    that arrive without full_text (e.g. mid-day user activation, new source
    added after the pool was built).

Accepts either RawArticle (Phase A) or CuratedArticle (Phase B fallback) since
both share the same full_text, url, source, id, title fields.
"""
import requests
import structlog
from urllib.parse import urlparse

from mcp_servers.article_fetcher_server import fetch_article_content
from models.enums import Source
from scraper.ddg_scraper import DDGScraper

log = structlog.get_logger(__name__)

# Sources whose email links hit a paywall — DDG finds the articleshow/ URL directly.
_ET_SOURCES = frozenset({Source.ETTECH, Source.ET_AI})

# ET articleshow URLs are freely scrapeable via trafilatura; scope DDG to this domain.
_ET_SITE_SCOPE = "economictimes.indiatimes.com"

_ddg_scraper = DDGScraper()


def _url_domain(url: str) -> str | None:
    """Extract domain from URL for DDG skip-domain hint."""
    try:
        return urlparse(url).netloc.lower().removeprefix("www.") or None
    except Exception:
        return None


def _resolve_nltrack_url(url: str) -> str:
    """Follow nltrack.indiatimes.com redirect to get the real articleshow URL.

    Returns the resolved URL, or the original URL on any failure.
    nltrack URLs are ET tracking redirects — the final destination is the
    real article. We grab it to bypass the redirect chain that confuses trafilatura.
    """
    parsed = urlparse(url)
    if "nltrack.indiatimes.com" not in parsed.netloc:
        return url
    try:
        resp = requests.head(url, allow_redirects=True, timeout=5)
        resolved = resp.url
        if "articleshow" in resolved or "economictimes.indiatimes.com" in resolved:
            return resolved
    except Exception:
        pass
    return url


class ScraperAgent:
    """
    Fetches full article text for a list of articles (RawArticle or CuratedArticle),
    populating full_text in-place. Articles that already have full_text are skipped.
    """

    def run(self, articles: list) -> None:
        """
        Scrape full text for all articles missing it.
        Modifies articles in-place (sets full_text).
        """
        to_fetch = [a for a in articles if not a.full_text]
        log.info("scraper_start", total=len(articles), to_fetch=len(to_fetch))

        for article in to_fetch:
            url_str = str(article.url)
            is_et = article.source in _ET_SOURCES

            # For ET AI articles: nltrack.indiatimes.com is a tracking redirect.
            # Resolve it first to get the actual articleshow URL for direct scraping.
            if is_et:
                url_str = _resolve_nltrack_url(url_str)

            skip_domain = _url_domain(url_str)

            # Skip direct fetch for ettech placeholder URLs — they are intentionally
            # not real URLs and will always fail. Go straight to DDG.
            is_placeholder = "ettech.placeholder" in url_str
            if not is_placeholder:
                text = fetch_article_content(url_str)
                if text and len(text) >= 200:
                    article.full_text = text
                    log.debug("article_fetched", article_id=article.id, chars=len(text))
                    continue

            # DDG fallback. For ET sources, scope the search to ET's domain and
            # require results to be on-domain or have sufficient title overlap.
            # This prevents bad matches (e.g. Wikipedia "Musical chairs" for "Mphasis").
            if is_et:
                ddg_text = _ddg_scraper.search_and_fetch(
                    article.title,
                    skip_domain=None,
                    site_scope=_ET_SITE_SCOPE,
                )
            else:
                ddg_text = _ddg_scraper.search_and_fetch(
                    article.title,
                    skip_domain=skip_domain,
                )
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

        fetched = sum(1 for a in articles if a.full_text)
        log.info("scraper_complete", total=len(articles), with_full_text=fetched)
