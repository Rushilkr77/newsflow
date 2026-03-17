"""
Parser: Harper Carroll AI weekly digest.

Email format: HTML primary (text/plain fallback).

HTML structure (verified from real emails, Feb 26 and Mar 4 2026):

  Section headers: <h1>–<h4> elements or bold blocks between article groups.
    e.g. <h2>Top Stories</h2>

  Article entries: <a href="kit-tracking-url">Title of Article</a>
    followed by a short description in the same or sibling element.

  Kit tracking URLs are decoded exactly as in the plain-text version:
    https://822c1333.click.kit-mail3.com/.../aHR0cHM6Ly93d3cu...
    Decode: base64.b64decode(last_segment + padding).decode('utf-8')

  Sections vary week to week — parsed dynamically from heading text.

  Stop parsing at: "Have a great week!"

Plain-text fallback (used when HTML body is unavailable):

  Section headers are dash-bordered:
    -----------
    Top Stories
    -----------

  Article entries:
    Title (https://tracking.url) — Description

Frequency: Weekly (Thursday).
"""
import base64
import re
import uuid
from datetime import datetime

import structlog
from bs4 import BeautifulSoup

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser

log = structlog.get_logger(__name__)

_STOP_MARKER = "Have a great week!"

# Line consisting entirely of dashes (3 or more) — plain-text parser
_DASH_LINE = re.compile(r"^-{3,}\s*$")

# Numbered article prefix: "1. " or "12. " — plain-text parser
_NUMBERED_PREFIX = re.compile(r"^(\d+)\.\s+(.+)$")

# Kit tracking redirect URL pattern
_KIT_DOMAIN = "click.kit-mail"

# HTML heading tag names
_HEADING_TAGS = {"h1", "h2", "h3", "h4"}

# Nav / UI links to skip in the HTML parser
_NAV_SIGNALS = {
    "unsubscribe", "view in browser", "view online", "manage preferences",
    "manage subscription", "twitter", "linkedin", "instagram", "facebook",
    "youtube", "privacy policy", "terms of service", "forward this",
    "powered by", "kit", "convertkit",
}


def _decode_kit_url(tracking_url: str) -> str:
    """
    Decode real URL from Harper Carroll Kit tracking redirect.
    The last path segment is the real URL base64-encoded.
    Falls back to the tracking URL if decoding fails.
    """
    try:
        b64 = tracking_url.rstrip("/").split("/")[-1]
        b64 += "=" * (4 - len(b64) % 4)
        decoded = base64.b64decode(b64).decode("utf-8")
        if decoded.startswith("http"):
            return decoded
    except Exception:
        pass
    return tracking_url


def _is_nav_link(title: str) -> bool:
    """Return True for unsubscribe / footer / social links that aren't articles."""
    t = title.lower().strip()
    return any(signal in t for signal in _NAV_SIGNALS)


def _is_fragment_title(title: str) -> bool:
    """
    Return True for sentence fragments mistakenly parsed as titles:
    - Starts with lowercase → extracted from mid-sentence context.
    - No uppercase letters at all → numeric/statistical fragment (e.g. "295% increase").
    """
    if not title:
        return True
    return title[0].islower() or not any(c.isupper() for c in title)


class HarperCarrollParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        # Prefer HTML parsing — title = link text gives cleaner results.
        # Fall back to text/plain parser if HTML yields fewer than 5 articles.
        body_lower = (email_body or "").lstrip()[:100].lower()
        is_html = body_lower.startswith("<html") or body_lower.startswith("<!doctype") or "<body" in body_lower

        if is_html:
            articles = self._parse_html(email_body, email_metadata)
            if len(articles) >= 5:
                log.info("harper_carroll_parsed", method="html", article_count=len(articles))
                return articles
            log.info(
                "harper_carroll_html_fallback",
                html_count=len(articles),
                reason="fewer than 5 articles from HTML — trying plain text",
            )

        articles = self._parse_plain_text(email_body, email_metadata)
        log.info("harper_carroll_parsed", method="plain_text", article_count=len(articles))
        return articles

    # -------------------------------------------------------------------------
    # HTML parser (primary)
    # -------------------------------------------------------------------------

    def _parse_html(self, body: str, meta: dict) -> list[RawArticle]:
        soup = BeautifulSoup(body, "lxml")

        # Remove junk elements that clutter the link walk
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()

        articles: list[RawArticle] = []
        current_section = "top_stories"
        seen_urls: set[str] = set()
        stop = False

        for element in soup.find_all(True):
            if stop:
                break

            # Stop marker — check direct string only to avoid early termination
            # from a large parent container that happens to contain the phrase.
            direct_text = element.string or ""
            if _STOP_MARKER in direct_text:
                break

            tag_name = element.name

            # Section header detection
            if tag_name in _HEADING_TAGS:
                header_text = element.get_text(strip=True)
                # Sanity: genuine section headers are 2–8 words
                if header_text and 1 <= len(header_text.split()) <= 8:
                    current_section = self._normalize_section(header_text)
                continue

            # Article link detection
            if tag_name != "a":
                continue

            href = element.get("href", "")
            if not href or not href.startswith("http"):
                continue

            # Only decode Kit tracking URLs; pass direct URLs through unchanged
            if _KIT_DOMAIN in href:
                real_url = _decode_kit_url(href)
            else:
                # Direct link — only include if it looks like a real article URL
                # (skip mailto:, tel:, anchor-only hrefs already handled above)
                real_url = self._clean_url(href)

            if not real_url or not real_url.startswith("http"):
                continue

            if real_url in seen_urls:
                continue

            title = element.get_text(strip=True)

            if not title or len(title) < 8:
                continue
            if _is_nav_link(title):
                continue
            if _is_fragment_title(title):
                continue

            # Snippet: sibling / parent text after the link
            snippet = self._extract_html_snippet(element, title)

            seen_urls.add(real_url)

            try:
                article = RawArticle(
                    id=str(uuid.uuid4()),
                    title=title,
                    url=real_url,
                    source=Source.HARPER_CARROLL,
                    sender_email=meta.get("sender_email", "hai@harpercarrollai.com"),
                    snippet=snippet or title,
                    section=current_section,
                    timestamp=meta.get("timestamp", datetime.utcnow()),
                    newsletter_date=meta.get("newsletter_date", ""),
                    extraction_confidence=0.90,
                )
                articles.append(article)
            except Exception as e:
                log.debug("harper_carroll_html_skip", title=title[:60], error=str(e))

        return articles

    def _extract_html_snippet(self, a_tag, title: str) -> str:
        """
        Extract description text near the article link.
        Strategy: take the parent element's full text, strip the title from it,
        then clean leading separators.
        """
        parent = a_tag.parent
        if parent is None:
            return title

        parent_text = parent.get_text(separator=" ", strip=True)
        # Remove the title text (appears once, at the start of the link)
        snippet = parent_text.replace(title, "", 1).strip()
        # Strip leading numbered-list prefix left behind after title removal ("1. ")
        snippet = re.sub(r"^\d+\.\s*", "", snippet)
        snippet = re.sub(r"^[\s\u2014\-\u2013:]+", "", snippet).strip()

        if len(snippet) > 600:
            snippet = snippet[:600].rsplit(" ", 1)[0] + "..."

        return snippet

    # -------------------------------------------------------------------------
    # Plain-text parser (fallback)
    # -------------------------------------------------------------------------

    def _parse_plain_text(self, body: str, meta: dict) -> list[RawArticle]:
        lines = body.splitlines()
        articles: list[RawArticle] = []
        current_section = "top_stories"
        i = 0

        while i < len(lines):
            line = lines[i]

            # Hard stop
            if _STOP_MARKER in line:
                break

            stripped = line.strip()

            # Section header detection: dash-line / title / dash-line
            if _DASH_LINE.match(stripped):
                if i + 2 < len(lines) and _DASH_LINE.match(lines[i + 2].strip()):
                    section_name = lines[i + 1].strip()
                    if section_name:
                        current_section = self._normalize_section(section_name)
                        i += 3  # consume: dash / name / dash
                        continue

            # Skip non-article lines quickly
            if not stripped or stripped.startswith("*") or _DASH_LINE.match(stripped):
                i += 1
                continue

            # Try to parse an article entry
            article, consumed = self._try_parse_article(lines, i, current_section, meta)
            if article:
                articles.append(article)
                i += consumed
            else:
                i += 1

        return articles

    # -------------------------------------------------------------------------
    # Plain-text article extraction
    # -------------------------------------------------------------------------

    def _try_parse_article(
        self, lines: list[str], start: int, section: str, meta: dict
    ) -> tuple[RawArticle | None, int]:
        """
        Try to parse a numbered or unnumbered article entry starting at `start`.

        Handles both inline and multi-line URL patterns:
          Inline:     Title (https://url) — Description
          Multi-line: Title (
                      https://url
                      ) — Description

        Returns (article, lines_consumed) or (None, 1).
        """
        raw_line = lines[start].strip()

        # Strip numbered prefix if present
        numbered = _NUMBERED_PREFIX.match(raw_line)
        body_text = numbered.group(2) if numbered else raw_line

        # Must contain '(' to hold a URL
        if "(" not in body_text:
            return None, 1

        paren_idx = body_text.index("(")
        title = body_text[:paren_idx].strip()
        after_open = body_text[paren_idx + 1:]  # everything after '('

        if not title or len(title) < 8:
            return None, 1

        # Reject sentence fragments mistakenly parsed as titles
        if _is_fragment_title(title):
            return None, 1

        # --- Resolve URL and description ---
        url_str = ""
        description = ""
        lines_consumed = 1

        if ")" in after_open:
            # Inline: entire URL and close paren on the same line
            close_idx = after_open.index(")")
            url_str = after_open[:close_idx].strip()
            rest = after_open[close_idx + 1:].strip()
            description = self._strip_separator(rest)
        else:
            # Multi-line: URL on subsequent line(s), then ') — desc'
            url_parts = [after_open.strip()] if after_open.strip() else []
            j = start + 1
            found_close = False

            while j < len(lines) and (j - start) < 6:
                next_stripped = lines[j].strip()

                if next_stripped.startswith(")"):
                    rest = next_stripped[1:].strip()
                    description = self._strip_separator(rest)
                    lines_consumed = j - start + 1
                    found_close = True
                    break
                elif _DASH_LINE.match(next_stripped) or _STOP_MARKER in next_stripped:
                    break
                else:
                    url_parts.append(next_stripped)
                    j += 1

            if not found_close:
                return None, 1

            url_str = " ".join(url_parts).strip()

        if not url_str or not url_str.startswith("http"):
            return None, 1

        # Decode Kit tracking URL → real URL
        real_url = _decode_kit_url(url_str) if _KIT_DOMAIN in url_str else self._clean_url(url_str)

        snippet = description if description else title
        if len(snippet) > 600:
            snippet = snippet[:600].rsplit(" ", 1)[0] + "..."

        try:
            article = RawArticle(
                id=str(uuid.uuid4()),
                title=title,
                url=real_url,
                source=Source.HARPER_CARROLL,
                sender_email=meta.get("sender_email", "hai@harpercarrollai.com"),
                snippet=snippet,
                section=section,
                timestamp=meta.get("timestamp", datetime.utcnow()),
                newsletter_date=meta.get("newsletter_date", ""),
                extraction_confidence=0.85,
            )
        except Exception as e:
            log.debug("harper_carroll_skip", title=title[:60], error=str(e))
            return None, 1

        return article, lines_consumed

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _normalize_section(self, section_name: str) -> str:
        """'AI Agents & Tools' → 'ai_agents_tools'"""
        clean = re.sub(r"[^a-z0-9\s]", "", section_name.lower())
        clean = re.sub(r"\s+", "_", clean.strip())
        return clean or "main"

    def _strip_separator(self, text: str) -> str:
        """Remove leading em-dash, hyphen, colon separators after the closing paren."""
        return re.sub(r"^[\s\u2014\-\u2013:]+", "", text).strip()
