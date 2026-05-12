"""
Inc42 fallback scraper for ET article titles.
ET Tech and ET AI articles link to economictimes.indiatimes.com (paywalled).
Strategy: search Inc42.com for the article title, scrape the top matching result.
"""
import urllib.parse

import requests
import structlog
import trafilatura

log = structlog.get_logger(__name__)

_SEARCH_URL = "https://inc42.com/?s={query}"
_REQUEST_TIMEOUT = 8  # seconds — increased from 5 (Inc42 search can be slow)
_MIN_ARTICLE_CHARS = 150

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# URL path segments that indicate real article pages (not tag/category pages).
# /startups/ added: Inc42 uses it for funding/M&A stories (e.g. inc42.com/startups/news/…).
_VALID_PATH_SEGMENTS = ("/features/", "/news/", "/buzz/", "/startups/")


class Inc42Scraper:
    def search_and_fetch(self, title: str) -> str | None:
        """
        Search Inc42 for an article matching *title* and return its full text.

        Returns scraped text (len > _MIN_ARTICLE_CHARS) on success, None otherwise.
        All exceptions are caught — this method never raises.
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
        Fetch the Inc42 search results page and return the first suitable URL.

        Looks for <article> tags or <h2> elements that contain an <a href>.
        Accepts only paths that contain /features/, /news/, or /buzz/.
        """
        search_url = _SEARCH_URL.format(query=urllib.parse.quote(title))
        response = requests.get(search_url, timeout=_REQUEST_TIMEOUT, headers=_HEADERS)
        response.raise_for_status()

        # Lazy import to avoid hard dependency at module load time in tests
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.text, "lxml")

        # Strategy 1: <article> tags (standard HTML5 search result cards)
        for article_tag in soup.find_all("article"):
            link = article_tag.find("a", href=True)
            if link:
                href = link["href"]
                if self._is_valid_article_url(href):
                    return href

        # Strategy 2: <h2> elements containing an <a href> (common in WordPress themes)
        for h2 in soup.find_all("h2"):
            link = h2.find("a", href=True)
            if link:
                href = link["href"]
                if self._is_valid_article_url(href):
                    return href

        # Strategy 3: any <a href> on the page matching a valid Inc42 article URL.
        # Catches layout changes where results aren't wrapped in <article>/<h2>.
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if self._is_valid_article_url(href):
                return href

        return None

    def _is_valid_article_url(self, href: str) -> bool:
        """Return True if the URL path looks like a real Inc42 article."""
        if not href or not href.startswith("http"):
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
