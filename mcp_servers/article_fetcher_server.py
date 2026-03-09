"""
MCP Server: Article Content Fetcher

Exposes article fetching as an MCP tool (fetch_article).
Can be run standalone as an MCP server (e.g. for Claude Desktop integration)
OR imported directly — the core fetch function is usable from Python without
going through the MCP protocol.

Phase 1: fetch_article(url) — trafilatura + newspaper3k + rate limiting
Phase 2 (future): search_and_fetch(query, preferred_sites) — for ET paywall bypass via Inc42/Google

Usage as MCP server:
    python -m mcp_servers.article_fetcher_server

Usage from Python:
    from mcp_servers.article_fetcher_server import fetch_article_content
    text = fetch_article_content("https://example.com/article")
"""
import sys
from pathlib import Path

import structlog

# Allow running as top-level module from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.article_scraper import ArticleScraper

log = structlog.get_logger(__name__)

# Shared scraper instance — handles trafilatura + newspaper3k + rate limiting
_scraper = ArticleScraper()


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

    if __name__ == "__main__":
        mcp.run()

except ImportError:
    # mcp package not installed — MCP server mode unavailable.
    # fetch_article_content() still works for direct Python use.
    if __name__ == "__main__":
        print(
            "ERROR: 'mcp' package not installed. "
            "Run: pip install mcp  to enable MCP server mode.\n"
            "The fetch_article_content() function still works when imported directly."
        )
