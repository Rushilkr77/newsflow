"""
Parser: Harper Carroll AI weekly digest.

Email structure (HTML):
  - Sections: "Top Stories", "Major Model Releases", "Business & Strategy",
    "Safety & Security", "Product & Developer Tools", "Health & Science"
  - Each section contains numbered items: <li> or <p> with an <a> link + description
  - Skip "Social Updates" section entirely
  - Stop at "Live Course", "Enroll", or "Sponsor" sections

MIME type: multipart/alternative — use text/html part.
Frequency: Weekly (Wednesday or Thursday).
"""
import re
import uuid
from datetime import datetime

import structlog
from bs4 import BeautifulSoup, Tag

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser

log = structlog.get_logger(__name__)

# Sections to skip entirely
_SKIP_SECTIONS = {"social updates", "social", "sponsor", "sponsors", "live course"}

# Stop parsing when these appear in a section heading
_STOP_SECTIONS = {"live course", "enroll", "sponsor"}

# Sections that map to subsections worth parsing
_SECTION_PRIORITY = {
    "top stories": "top_stories",
    "major model releases": "model_releases",
    "business & strategy": "business_strategy",
    "business and strategy": "business_strategy",
    "product & developer tools": "product_tools",
    "product and developer tools": "product_tools",
    "safety & security": "safety_security",
    "safety and security": "safety_security",
    "health & science": "health_science",
    "health and science": "health_science",
}


class HarperCarrollParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        soup = BeautifulSoup(email_body, "lxml")
        articles: list[RawArticle] = []

        # Try structured section parsing first
        articles = self._parse_sections(soup, email_metadata)

        if not articles:
            # Fallback: extract any link with enough surrounding text
            articles = self._parse_fallback(soup, email_metadata)

        log.info("harper_carroll_parsed", article_count=len(articles))
        return articles

    # -------------------------------------------------------------------------
    # Structured section parsing
    # -------------------------------------------------------------------------

    def _parse_sections(self, soup: BeautifulSoup, meta: dict) -> list[RawArticle]:
        """Walk section headers and extract numbered article items within each."""
        articles: list[RawArticle] = []
        current_section = "top_stories"
        stop = False

        # Find all headings (h1–h4) and treat them as section markers
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td"]):
            if stop:
                break

            text = tag.get_text(strip=True)
            lower = text.lower()

            # Check if this tag is a section header
            matched_section = self._match_section(lower)
            if matched_section is not None:
                if matched_section == "__stop__":
                    stop = True
                    break
                if matched_section == "__skip__":
                    current_section = "__skip__"
                    continue
                current_section = matched_section
                continue

            # Skip content within skipped sections
            if current_section == "__skip__":
                continue

            # Try to extract an article from this tag if it has a link
            if tag.name in ("li", "p", "td"):
                article = self._extract_article_from_tag(tag, current_section, meta)
                if article:
                    articles.append(article)

        return articles

    def _match_section(self, text: str) -> str | None:
        """Return section key, '__stop__', '__skip__', or None (not a section header)."""
        # Must be short enough to be a heading (not a paragraph)
        if len(text) > 80:
            return None

        for stop_kw in _STOP_SECTIONS:
            if stop_kw in text:
                return "__stop__"

        for skip_kw in _SKIP_SECTIONS:
            if skip_kw in text:
                return "__skip__"

        for kw, section_id in _SECTION_PRIORITY.items():
            if kw in text:
                return section_id

        return None

    def _extract_article_from_tag(
        self, tag: Tag, section: str, meta: dict
    ) -> RawArticle | None:
        """Extract a RawArticle from a <li> or <p> that contains an <a href> link."""
        link = tag.find("a", href=True)
        if not link:
            return None

        href = link.get("href", "").strip()
        if not href or not href.startswith("http"):
            return None

        # Title: link text, falling back to surrounding text before em-dash
        title = link.get_text(strip=True)
        if not title or len(title) < 10:
            return None

        # Snippet: full tag text minus the link text, or the text after "—"
        full_text = tag.get_text(" ", strip=True)
        snippet = self._extract_snippet(full_text, title)
        if not snippet:
            snippet = title  # Minimum: use title as snippet

        url = self._clean_url(href)

        try:
            return RawArticle(
                id=str(uuid.uuid4()),
                title=title,
                url=url,
                source=Source.HARPER_CARROLL,
                sender_email=meta.get("sender_email", "hai@harpercarrollai.com"),
                snippet=snippet,
                section=section,
                timestamp=meta.get("timestamp", datetime.utcnow()),
                newsletter_date=meta.get("newsletter_date", ""),
                extraction_confidence=0.85,
            )
        except Exception as e:
            log.debug("harper_carroll_article_skip", title=title, error=str(e))
            return None

    def _extract_snippet(self, full_text: str, title: str) -> str:
        """Extract description after the title, removing the title prefix."""
        # Remove the title from the full text to get the description
        text = full_text.replace(title, "", 1).strip()

        # Strip leading separators: "—", "-", "–", ":", "."
        text = re.sub(r"^[\—\-–:\.\s]+", "", text).strip()

        # Cap length
        if len(text) > 600:
            text = text[:600].rsplit(" ", 1)[0] + "..."

        return text

    # -------------------------------------------------------------------------
    # Fallback: generic link extraction
    # -------------------------------------------------------------------------

    def _parse_fallback(self, soup: BeautifulSoup, meta: dict) -> list[RawArticle]:
        """Extract any <a href> with text > 20 chars and surrounding paragraph."""
        articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        _SKIP_TEXTS = {"unsubscribe", "privacy", "manage", "forward", "view online", "click here"}

        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            if not href.startswith("http"):
                continue

            title = link.get_text(strip=True)
            if len(title) < 20:
                continue
            if any(skip in title.lower() for skip in _SKIP_TEXTS):
                continue

            url = self._clean_url(href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Snippet: text of the parent container
            parent = link.find_parent(["li", "p", "td", "div"])
            snippet = parent.get_text(" ", strip=True) if parent else title
            if len(snippet) > 600:
                snippet = snippet[:600].rsplit(" ", 1)[0] + "..."

            try:
                articles.append(
                    RawArticle(
                        id=str(uuid.uuid4()),
                        title=title,
                        url=url,
                        source=Source.HARPER_CARROLL,
                        sender_email=meta.get("sender_email", "hai@harpercarrollai.com"),
                        snippet=snippet,
                        section="main",
                        timestamp=meta.get("timestamp", datetime.utcnow()),
                        newsletter_date=meta.get("newsletter_date", ""),
                        extraction_confidence=0.6,
                    )
                )
            except Exception:
                continue

        return articles
