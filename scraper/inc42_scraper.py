"""
Inc42 fallback scraper for ET article titles.
ET Tech and ET AI articles link to economictimes.indiatimes.com (paywalled).
Strategy: use DuckDuckGo site:inc42.com search to find the article URL, then
fetch with trafilatura. This avoids hitting Inc42's own search endpoint which
blocks automated requests with 403.
"""
import trafilatura
import structlog
from duckduckgo_search import DDGS

log = structlog.get_logger(__name__)

_MIN_ARTICLE_CHARS = 150
_MAX_DDG_RESULTS = 5

# URL path segments that indicate real article pages (not tag/category pages).
# /startups/ covers funding/M&A stories (e.g. inc42.com/startups/news/…).
_VALID_PATH_SEGMENTS = ("/features/", "/news/", "/buzz/", "/startups/")


class Inc42Scraper:
    def search_and_fetch(self, title: str) -> str | None:
        """
        Find an Inc42 article matching *title* via DDG and return its full text.
        Returns scraped text on success, None otherwise. Never raises.
        """
        try:
            article_url = self._find_article_url(title)
            if not article_url:
                log.info("inc42_no_result", title=title[:60])
                return None

            text = self._scrape_url(article_url)
            if text and len(text) > _MIN_ARTICLE_CHARS:
                log.debug(
                    "inc42_fetch",
                    title=title[:60],
                    result_url=article_url,
                    chars=len(text),
                )
                return text

            log.debug("inc42_text_too_short", title=title[:60], result_url=article_url)
            return None

        except Exception as exc:
            log.debug("inc42_error", title=title[:60], error=str(exc))
            return None

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _find_article_url(self, title: str) -> str | None:
        """
        Use DuckDuckGo with site:inc42.com to locate the article.
        Avoids Inc42's search endpoint which returns 403 for automated requests.
        """
        try:
            results = list(DDGS().text(f"site:inc42.com {title}", max_results=_MAX_DDG_RESULTS))
        except Exception as exc:
            log.info("inc42_ddg_error", title=title[:60], error=str(exc))
            return None

        for result in results:
            url = result.get("href") or result.get("url", "")
            if url and self._is_valid_article_url(url):
                return url

        return None

    def _is_valid_article_url(self, href: str) -> bool:
        """Return True if the URL looks like a real Inc42 article."""
        if not href or not href.startswith("http"):
            return False
        if "inc42.com" not in href:
            return False
        return any(segment in href for segment in _VALID_PATH_SEGMENTS)

    def _scrape_url(self, url: str) -> str | None:
        """Fetch and extract article text via trafilatura."""
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            return trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
            )
        return None
