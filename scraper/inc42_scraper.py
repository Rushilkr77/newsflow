"""
India tech fallback scraper for paywalled ET articles.
Uses DuckDuckGo site: search to find the article on a given India news site,
then fetches the content via trafilatura.

Default site is inc42.com. Pass a different site + valid_path_segments to
reuse for YourStory, Entrackr, etc.
"""
import trafilatura
import structlog
from duckduckgo_search import DDGS

log = structlog.get_logger(__name__)

_MIN_ARTICLE_CHARS = 150
_MAX_DDG_RESULTS = 5

# Default valid path segments for inc42.com.
# /startups/ covers funding/M&A stories (e.g. inc42.com/startups/news/…).
_INC42_PATHS = ("/features/", "/news/", "/buzz/", "/startups/")


class Inc42Scraper:
    """Search a given India tech site via DDG and scrape the result.

    Default args target inc42.com. Pass site + valid_path_segments to reuse
    for YourStory, Entrackr, or any India news site.
    """

    def __init__(
        self,
        site: str = "inc42.com",
        valid_path_segments: tuple[str, ...] = _INC42_PATHS,
    ):
        self._site = site
        self._valid_paths = valid_path_segments

    def search_and_fetch(self, title: str) -> str | None:
        """
        Find an article matching *title* on self._site via DDG and return full text.
        Returns scraped text on success, None otherwise. Never raises.
        """
        try:
            article_url = self._find_article_url(title)
            if not article_url:
                log.info("india_scraper_no_result", site=self._site, title=title[:60])
                return None

            text = self._scrape_url(article_url)
            if text and len(text) > _MIN_ARTICLE_CHARS:
                log.debug(
                    "india_scraper_fetch",
                    site=self._site,
                    title=title[:60],
                    result_url=article_url,
                    chars=len(text),
                )
                return text

            log.debug("india_scraper_text_too_short", site=self._site, title=title[:60])
            return None

        except Exception as exc:
            log.debug("india_scraper_error", site=self._site, title=title[:60], error=str(exc))
            return None

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _find_article_url(self, title: str) -> str | None:
        """Use DDG site: search to find the article URL.
        Avoids the site's own search endpoint (often 403 for automated requests)."""
        try:
            results = list(DDGS().text(f"site:{self._site} {title}", max_results=_MAX_DDG_RESULTS))
        except Exception as exc:
            log.info("india_scraper_ddg_error", site=self._site, title=title[:60], error=str(exc))
            return None

        for result in results:
            url = result.get("href") or result.get("url", "")
            if url and self._is_valid_article_url(url):
                return url

        return None

    def _is_valid_article_url(self, href: str) -> bool:
        """Return True if the URL looks like a real article on self._site."""
        if not href or not href.startswith("http"):
            return False
        if self._site not in href:
            return False
        if not self._valid_paths:
            from urllib.parse import urlparse
            return len(urlparse(href).path.strip("/")) > 5
        return any(seg in href for seg in self._valid_paths)

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
