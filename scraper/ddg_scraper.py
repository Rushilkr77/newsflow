"""
DuckDuckGo search fallback scraper.

Used when direct URL scraping (trafilatura/newspaper3k) AND inc42 both fail.
Searches DuckDuckGo for the article title, then tries to scrape the top results.

Skips domains that are known paywalls or the same domain as the original failed URL
(no point retrying the same site).
"""
import re
from urllib.parse import urlparse

import structlog
import trafilatura
from ddgs import DDGS
from trafilatura.settings import use_config

log = structlog.get_logger(__name__)

_MIN_CHARS = 500
_TRAFILATURA_CONFIG = use_config()
_TRAFILATURA_CONFIG.set(
    "DEFAULT",
    "USER_AGENTS",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
_MAX_RESULTS = 5          # fetch up to 5 results, try until one scrapes cleanly
_MAX_ATTEMPTS = 3         # try at most 3 URLs

# Minimum Jaccard overlap (significant words) when site_scope results stray off-domain.
_MIN_TITLE_OVERLAP = 0.3

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "it", "its", "as", "by", "be", "this", "that",
    "from", "are", "was", "has", "have", "will", "not", "his", "her",
    "their", "how", "why", "what", "who", "which", "about", "into",
})

# Domains we know are paywalled or unhelpful.
# NOTE: economictimes.indiatimes.com is intentionally excluded — email redirect URLs
# hit a paywall but DDG-found articleshow/ URLs are freely scrapeable.
_SKIP_DOMAINS = frozenset({
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "businessinsider.com",
    "fortune.com",
    "paywall.techcrunch.com",
    "news.google.com",   # aggregator redirect, not scrapeable article content
    "msn.com",          # aggregator, thin content
    "en.wikipedia.org", # encyclopaedia — never a news article
    "tech.co",          # off-topic aggregator for India ET queries
})


def _title_tokens(title: str) -> set[str]:
    """Lowercase word tokens with stopwords removed."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _title_overlap(query: str, result_title: str) -> float:
    """Jaccard similarity between significant words in query and result title."""
    q = _title_tokens(query)
    r = _title_tokens(result_title)
    if not q:
        return 1.0  # can't validate — let it through
    intersection = q & r
    union = q | r
    return len(intersection) / len(union) if union else 0.0


class DDGScraper:
    def search_and_fetch(
        self,
        title: str,
        skip_domain: str | None = None,
        site_scope: str | None = None,
    ) -> str | None:
        """
        Search DuckDuckGo for *title*, scrape the first accessible result.

        Args:
            title: Article title to search for.
            skip_domain: Domain to skip (e.g. the original source that already failed).
            site_scope: When set (e.g. "economictimes.indiatimes.com"), prefix query
                with "site:<scope>" and require results to match that domain OR pass
                title-overlap validation — guards against off-topic DDG matches.

        Returns scraped text on success, None if no accessible result found.
        All exceptions are caught — this method never raises.
        """
        query = f"site:{site_scope} {title}" if site_scope else title
        try:
            results = list(DDGS().text(query, max_results=_MAX_RESULTS))
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

            # When searching with a site scope, validate the result is on-domain OR
            # the result title meaningfully overlaps with the query (catches DDG straying).
            if site_scope:
                scope_domain = site_scope.lower().removeprefix("www.")
                on_domain = domain == scope_domain or domain.endswith("." + scope_domain)
                result_title = result.get("title", "")
                overlap = _title_overlap(title, result_title)
                if not on_domain and overlap < _MIN_TITLE_OVERLAP:
                    log.debug(
                        "ddg_scope_mismatch_rejected",
                        url=url,
                        domain=domain,
                        overlap=round(overlap, 2),
                        title=title[:60],
                    )
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
            downloaded = trafilatura.fetch_url(url, config=_TRAFILATURA_CONFIG)
            if downloaded:
                return trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=False,
                )
        except Exception as e:
            log.debug("ddg_scrape_error", url=url, error=str(e))
        return None
