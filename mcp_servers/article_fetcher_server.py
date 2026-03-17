"""
MCP Server: Article Content Fetcher

Exposes two MCP tools:
  - fetch_article(url): trafilatura + newspaper3k + rate limiting
  - search_and_fetch(title): Inc42 search fallback for ET paywall bypass

Can be run standalone as an MCP server (e.g. for Claude Desktop integration)
OR imported directly — the core fetch functions are usable from Python without
going through the MCP protocol.

Usage as MCP server:
    python -m mcp_servers.article_fetcher_server

Usage from Python:
    from mcp_servers.article_fetcher_server import fetch_article_content, search_and_fetch_content
    text = fetch_article_content("https://example.com/article")
    text = search_and_fetch_content("OpenAI raises $40B funding round")
"""
import sys
from pathlib import Path

import structlog

# Allow running as top-level module from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.article_scraper import ArticleScraper
from scraper.inc42_scraper import Inc42Scraper

log = structlog.get_logger(__name__)

# Shared scraper instances
_scraper = ArticleScraper()
_inc42 = Inc42Scraper()


def fetch_article_content(url: str) -> str:
    """
    Fetch full article text from a URL.

    Used by both the MCP tool wrapper and the summarizer agent directly.
    Returns clean extracted text, or empty string if the article is unavailable
    (paywall, rate limit, scraping failure).

    Rate limiting is handled internally (1.5s between same-domain requests).
    """
    result = _scraper.scrape(url)
    if result:
        log.debug("article_fetched", url=url, chars=len(result))
        return result
    log.debug("article_fetch_empty", url=url)
    return ""


def search_and_fetch_content(title: str) -> str:
    """
    Search Inc42.com for an article matching *title* and return its full text.

    Used as an ET paywall bypass: ET Tech and ET AI articles link to
    economictimes.indiatimes.com which is paywalled. This searches Inc42
    (India's leading startup news site) for the same story and returns
    the full text from there instead.

    Returns extracted text on success, empty string if not found.
    """
    result = _inc42.search_and_fetch(title)
    if result:
        log.debug("inc42_fetched", title=title[:60], chars=len(result))
        return result
    log.debug("inc42_fetch_empty", title=title[:60])
    return ""


# ---------------------------------------------------------------------------
# MCP server wrapper — only active when `mcp` package is installed
# ---------------------------------------------------------------------------

try:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("newsflow-article-fetcher")

    @mcp.tool()
    def fetch_article(url: str) -> str:
        """
        Fetch the full text content of an article from a URL.

        Returns clean extracted text, or an empty string if the article is
        behind a paywall, rate-limited, or otherwise unavailable.
        Handles trafilatura (primary) and newspaper3k (fallback) automatically.
        Rate limiting: 1.5s between requests to the same domain.
        """
        return fetch_article_content(url)

    @mcp.tool()
    def search_and_fetch(title: str) -> str:
        """
        Search Inc42.com for an article matching the given title and return its full text.

        Use this as a fallback for ET Tech and ET AI articles, which link to
        economictimes.indiatimes.com (paywalled). Inc42 covers the same India tech
        stories without a paywall.

        Returns extracted article text, or an empty string if no matching article is found.
        """
        return search_and_fetch_content(title)

    if __name__ == "__main__":
        mcp.run()

except ImportError:
    # mcp package not installed — MCP server mode unavailable.
    # fetch_article_content() and search_and_fetch_content() still work for direct Python use.
    if __name__ == "__main__":
        print(
            "ERROR: 'mcp' package not installed. "
            "Run: pip install mcp  to enable MCP server mode.\n"
            "The fetch_article_content() and search_and_fetch_content() functions "
            "still work when imported directly."
        )
