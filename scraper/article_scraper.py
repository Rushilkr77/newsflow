"""
Article scraper — fetches full article text from URLs.

Two-phase architecture (from DESIGN.md §5):
  Phase A (Ingestion): extract {title, snippet, url} from emails
  Phase B (before Summarizer): fetch full article content for P0/P1 only

Primary: trafilatura (fast, handles most sites cleanly)
Fallback: newspaper3k
Rate limiting: 1-2s delay between requests to the same domain.
"""
import time
from collections import defaultdict
from urllib.parse import urlparse

import structlog
import trafilatura
from newspaper import Article as NewspaperArticle

log = structlog.get_logger(__name__)

_DOMAIN_LAST_REQUEST: dict[str, float] = defaultdict(float)
_DOMAIN_DELAY_SEC = 1.5  # delay between requests to the same domain


class ArticleScraper:
    def __init__(self, timeout: int = 10, max_retries: int = 2):
        self.timeout = timeout
        self.max_retries = max_retries

    def scrape(self, url: str) -> str | None:
        """
        Fetch full article text from URL.
        Returns None if both scrapers fail or text is < 200 chars.
        """
        self._rate_limit(url)

        text = self._try_trafilatura(url)
        if text and len(text) > 200:
            log.debug("scraped_trafilatura", url=url, chars=len(text))
            return text

        text = self._try_newspaper(url)
        if text and len(text) > 200:
            log.debug("scraped_newspaper", url=url, chars=len(text))
            return text

        log.debug("scrape_failed", url=url)
        return None

    def _try_trafilatura(self, url: str) -> str | None:
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                return trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                )
        except Exception as e:
            log.debug("trafilatura_error", url=url, error=str(e))
        return None

    def _try_newspaper(self, url: str) -> str | None:
        try:
            article = NewspaperArticle(url, request_timeout=self.timeout)
            article.download()
            article.parse()
            return article.text if article.text else None
        except Exception as e:
            log.debug("newspaper_error", url=url, error=str(e))
        return None

    def _rate_limit(self, url: str) -> None:
        """Enforce per-domain delay to avoid rate limiting."""
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        last = _DOMAIN_LAST_REQUEST[domain]
        elapsed = time.time() - last
        if elapsed < _DOMAIN_DELAY_SEC:
            time.sleep(_DOMAIN_DELAY_SEC - elapsed)
        _DOMAIN_LAST_REQUEST[domain] = time.time()
