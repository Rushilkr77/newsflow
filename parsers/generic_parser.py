"""
Generic fallback parser for newsletters not in the configured sender registry.

Used when a sender email is listed in NEWSLETTER_SENDERS env var but has no
custom parser. Extracts all meaningful <a href> links with surrounding paragraph
text as snippets.

Strategy:
  - Find all <a href> links where link text is > 20 characters
  - Grab the nearest parent <li>, <p>, <td>, or <div> as the snippet context
  - Skip navigation/footer links (unsubscribe, privacy, etc.)
  - Deduplicate by URL
  - Tag articles with Source.CUSTOM and extraction_confidence=0.6

This parser intentionally does no section detection — it just extracts anything
that looks like a readable article link. The curator's LLM classification will
determine priority and relevance.
"""
import uuid
from datetime import datetime

import structlog
from bs4 import BeautifulSoup

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser

log = structlog.get_logger(__name__)

# Link text patterns to skip (navigation, footer, social)
_SKIP_LINK_TEXTS = frozenset({
    "unsubscribe", "privacy", "privacy policy", "manage preferences",
    "manage subscription", "forward", "view online", "view in browser",
    "click here", "read more", "learn more", "see more", "view all",
    "subscribe", "terms", "terms of service", "contact us", "advertise",
    "follow us", "tweet", "facebook", "linkedin", "instagram", "youtube",
    "share", "reply", "support", "help",
})

# Minimum link text length to consider as an article title
_MIN_TITLE_LEN = 20

# Maximum snippet length (characters)
_MAX_SNIPPET_LEN = 500


class GenericParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        soup = BeautifulSoup(email_body, "lxml")
        articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            if not href.startswith("http"):
                continue

            title = link.get_text(strip=True)

            # Filter: too short or navigation-like
            if len(title) < _MIN_TITLE_LEN:
                continue
            if self._is_nav_link(title):
                continue

            url = self._clean_url(href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            snippet = self._extract_snippet(link, title)

            try:
                articles.append(
                    RawArticle(
                        id=str(uuid.uuid4()),
                        title=title,
                        url=url,
                        source=Source.CUSTOM,
                        sender_email=email_metadata.get("sender_email", ""),
                        snippet=snippet,
                        section="main",
                        timestamp=email_metadata.get("timestamp", datetime.utcnow()),
                        newsletter_date=email_metadata.get("newsletter_date", ""),
                        extraction_confidence=0.6,
                    )
                )
            except Exception as e:
                log.debug("generic_parser_skip", title=title, error=str(e))
                continue

        log.info(
            "generic_parser_done",
            sender=email_metadata.get("sender_email", ""),
            article_count=len(articles),
        )
        return articles

    def _is_nav_link(self, text: str) -> bool:
        """Return True if the link text matches a known navigation/footer pattern."""
        lower = text.lower().strip()
        return lower in _SKIP_LINK_TEXTS or any(skip in lower for skip in _SKIP_LINK_TEXTS)

    def _extract_snippet(self, link_tag, title: str) -> str:
        """
        Extract surrounding paragraph text as the snippet.
        Walks up to the nearest meaningful container and grabs its text,
        with the link text removed to avoid duplication.
        """
        parent = link_tag.find_parent(["li", "p", "td", "div"])
        if not parent:
            return title

        full_text = parent.get_text(" ", strip=True)

        # Remove the title from the snippet to avoid duplication
        snippet = full_text.replace(title, "", 1).strip().lstrip("—–-:. ")

        if not snippet:
            snippet = title

        if len(snippet) > _MAX_SNIPPET_LEN:
            snippet = snippet[:_MAX_SNIPPET_LEN].rsplit(" ", 1)[0] + "..."

        return snippet
