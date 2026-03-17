"""
ET AI newsletter parser — HTML email (multipart/mixed).

Confirmed structure:
  Good morning Reader,
  In today's newsletter:
  [Headline 1..N]   ← table of contents, anchor links (#) or repeated URLs — skip

  [Story 1: Headline + teaser + Read More]
  ...

Detection: must verify from_display_name contains "ET AI" OR subject starts with "ET AI:"
before routing to this parser — done in IngestionAgent.

Full article may be behind ET paywall — snippet fallback handled in scraper.

Strategy for TOC vs. story blocks
----------------------------------
The email has two passes over each article:
  1. Table of contents (top): short anchor links OR the article URL repeated with only
     the headline as link text — no surrounding teaser prose.
  2. Story blocks (body): headline + multi-sentence teaser paragraph + "Read More" link.

We anchor on "Read More" links (always present in story blocks, never in TOC).
For each "Read More" link we walk up the DOM to find the smallest container that holds
both a headline tag AND more than one sentence of prose.  If the container only has the
headline text (< _MIN_TEASER_CHARS chars after stripping the headline), we skip it —
that's a TOC false-positive from a compound cell.
"""
import re
import uuid
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser

# Minimum teaser text length (excluding headline) to accept a block as a story
_MIN_TEASER_CHARS = 60

# Headline tag names, in preference order
_HEADLINE_TAGS = ("h1", "h2", "h3", "h4", "strong", "b")

# Preamble phrases to strip from extracted text
_PREAMBLE_PATTERNS = re.compile(
    r"^(good\s+morning[\w\s,!.]*|in\s+today['']s\s+newsletter\s*:?)\s*",
    re.IGNORECASE,
)


def _is_toc_link(href: str) -> bool:
    """Return True if the link is an in-page anchor (table of contents entry)."""
    return href.startswith("#") or not href.startswith("http")


def _find_story_container(link_tag: Tag) -> Tag | None:
    """
    Walk up from a "Read More" anchor to find the smallest block-level container
    that plausibly holds the full story teaser (headline + prose).

    We prefer <td> containers (common in HTML email tables) but also accept
    <div> and <p>.  We stop at the first container that has enough text.
    """
    for parent in link_tag.parents:
        if not isinstance(parent, Tag):
            continue
        tag_name = parent.name
        if tag_name in ("td", "div", "p", "li", "section", "article"):
            # Check that this container has enough text beyond the link itself
            container_text = parent.get_text(separator=" ", strip=True)
            link_text = link_tag.get_text(strip=True)
            remaining = container_text.replace(link_text, "").strip()
            if len(remaining) >= _MIN_TEASER_CHARS:
                return parent
        # Stop climbing past table/body boundaries
        if tag_name in ("table", "body", "html", "[document]"):
            return None
    return None


def _extract_title_and_snippet(container: Tag, read_more_text: str) -> tuple[str, str]:
    """
    Extract (title, snippet) from a story container.

    Priority order:
      1. First heading tag (h1-h4, strong, b) → title; remaining prose → snippet
      2. First sentence of the block → title; rest → snippet
    """
    # Get all text, removing the "Read More" anchor text
    full_text = container.get_text(separator=" ", strip=True)
    full_text = re.sub(
        r"\s*" + re.escape(read_more_text) + r"\s*", " ", full_text, flags=re.IGNORECASE
    ).strip()
    full_text = re.sub(r"\s{2,}", " ", full_text)

    # Strip preamble phrases that appear at the start of some ET AI blocks
    full_text = _PREAMBLE_PATTERNS.sub("", full_text).strip()

    # Try to locate a headline element
    headline_tag = container.find(_HEADLINE_TAGS)
    if headline_tag:
        title = headline_tag.get_text(strip=True)
        # Remove title from full_text to get snippet
        snippet = full_text
        # Replace only the first occurrence to avoid trimming repeated words
        idx = snippet.find(title)
        if idx != -1:
            snippet = (snippet[:idx] + snippet[idx + len(title):]).strip().lstrip(":").strip()
    else:
        # Fallback: split on first ". " boundary
        sentences = full_text.split(". ", 1)
        title = sentences[0].strip().rstrip(".")
        snippet = sentences[1].strip() if len(sentences) > 1 else ""

    return title, snippet


class ETAIParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        sender_email: str = email_metadata["sender_email"]
        timestamp: datetime = email_metadata["timestamp"]
        newsletter_date: str = email_metadata["newsletter_date"]

        soup = BeautifulSoup(email_body, "lxml")
        articles: list[RawArticle] = []
        seen_urls: set[str] = set()

        # Find every "Read More" anchor in the email
        read_more_links = soup.find_all(
            "a", string=re.compile(r"read\s+(more|full\s+article\s+here)", re.IGNORECASE)
        )

        for link in read_more_links:
            href = link.get("href", "").strip()

            # Skip in-page anchors (TOC) and empty/relative hrefs
            if _is_toc_link(href):
                continue

            url = self._clean_url(href)

            # Deduplicate by URL (ET AI sometimes repeats a story)
            if url in seen_urls:
                continue

            # Find a container big enough to hold a real teaser
            container = _find_story_container(link)
            if container is None:
                # Fallback: direct parent
                container = link.find_parent("td") or link.find_parent("div") or link.find_parent("p")
                if container is None:
                    continue

            read_more_text = link.get_text(strip=True)
            title, snippet = _extract_title_and_snippet(container, read_more_text)

            if not title or len(title) < 5 or title.upper().startswith("(SPONSOR)"):
                continue

            # Final guard: if snippet is too short, this is likely still a TOC entry
            # (some editors put a "Read More" in the TOC with a short description)
            if len(snippet) < _MIN_TEASER_CHARS:
                continue

            seen_urls.add(url)

            try:
                articles.append(
                    RawArticle(
                        id=str(uuid.uuid4()),
                        title=title,
                        url=url,  # type: ignore[arg-type]
                        source=Source.ET_AI,
                        sender_email=sender_email,
                        snippet=snippet,
                        section="main",
                        timestamp=timestamp,
                        newsletter_date=newsletter_date,
                        # ET articles are often behind a paywall; flag lower confidence
                        extraction_confidence=0.8,
                    )
                )
            except Exception:
                pass

        return articles
