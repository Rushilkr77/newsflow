"""
DuckDuckGo search fallback scraper.

Used when direct URL scraping (trafilatura/newspaper3k) AND inc42 both fail.
Searches DuckDuckGo for the article title, then tries to scrape the top results.

Skips domains that are known paywalls or the same domain as the original failed URL
(no point retrying the same site).
"""
from urllib.parse import urlparse

import structlog
import trafilatura
from duckduckgo_search import DDGS

log = structlog.get_logger(__name__)

_MIN_CHARS = 200
_MAX_RESULTS = 5          # fetch up to 5 results, try until one scrapes cleanly
_MAX_ATTEMPTS = 3         # try at most 3 URLs

# Domains we know are paywalled or unhelpful
_SKIP_DOMAINS = frozenset({
    "economictimes.indiatimes.com",
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "businessinsider.com",
    "fortune.com",
    "paywall.techcrunch.com",
})


class DDGScraper:
    def search_and_fetch(self, title: str, skip_domain: str | None = None) -> str | None:
        """
        Search DuckDuckGo for *title*, scrape the first accessible result.

        Args:
            title: Article title to search for.
            skip_domain: Domain to skip (e.g. the original source that already failed).

        Returns scraped text on success, None if no accessible result found.
        All exceptions are caught — this method never raises.
        """
        try:
            results = list(DDGS().text(title, max_results=_MAX_RESULTS))
        except Exception as e:
            log.debug("ddg_search_error", title=title[:60], error=str(e))
            return None

        attempts = 0
        for result in results:
            if attempts >= _MAX_ATTEMPTS:
                break
            url = result.get("href") or result.get("url", "")
            if not url:
                continue

            domain = urlparse(url).netloc.lower().removeprefix("www.")
            if domain in _SKIP_DOMAINS:
                continue
            if skip_domain and domain == skip_domain.lower().removeprefix("www."):
                continue

            attempts += 1
            text = self._scrape(url)
            if text and len(text) >= _MIN_CHARS:
                log.debug("ddg_scrape_success", title=title[:60], url=url, chars=len(text))
                return text
            log.debug("ddg_scrape_miss", title=title[:60], url=url)

        log.debug("ddg_no_result", title=title[:60])
        return None

    def _scrape(self, url: str) -> str | None:
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                return trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                )
        except Exception as e:
            log.debug("ddg_scrape_error", url=url, error=str(e))
        return None
