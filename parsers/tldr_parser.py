"""
TLDR newsletter parser — operates on the text/plain part of the email.

Confirmed structure (verified from real Gmail fetch, Mar 6 2026):
  - Articles: "TITLE (X MINUTE READ) [N]" followed by summary paragraph
  - Section headers: emoji + ALL CAPS (e.g. "🚀 HEADLINES & LAUNCHES")
  - Links block at bottom: "[N] https://..."
  - Sponsors: "(SPONSOR)" in title line — skip
  - Stop parsing at: "Love TLDR?" line
  - QUICK LINKS articles have no summary paragraph
"""
import re
import uuid
from datetime import datetime

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser


# Matches article title lines: "SOME TITLE (X MINUTE READ) [5]"
_ARTICLE_RE = re.compile(r"^(.+?)\s+\((\d+)\s+MINUTE\s+READ\)\s+\[(\d+)\]$", re.IGNORECASE)

# Matches quick link lines: "SOME TITLE [5]" (no minute read)
_QUICK_LINK_RE = re.compile(r"^(.+?)\s+\[(\d+)\]$")

# Matches links block entries: "[5] https://..."
_LINK_ENTRY_RE = re.compile(r"^\[(\d+)\]\s+(https?://\S+)$")

# Section headers have emoji at the start (Unicode range) + ALL CAPS text
_SECTION_RE = re.compile(r"^[\U00010000-\U0010ffff\U00002600-\U000027BF\U0001F300-\U0001F9FF]\s+([A-Z &]+)$")

_SECTION_MAP = {
    "HEADLINES & LAUNCHES": "headlines",
    "DEEP DIVES & ANALYSIS": "deep_dives",
    "ENGINEERING & RESEARCH": "engineering",
    "MISCELLANEOUS": "miscellaneous",
    "QUICK LINKS": "quick_links",
}

_SOURCE_MAP = {
    "tldr_ai": Source.TLDR_AI,
    "tldr_tech": Source.TLDR_TECH,
    "tldr_dev": Source.TLDR_DEV,
}


class TLDRParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        source_id: str = email_metadata["source_id"]
        source = _SOURCE_MAP[source_id]
        sender_email: str = email_metadata["sender_email"]
        timestamp: datetime = email_metadata["timestamp"]
        newsletter_date: str = email_metadata["newsletter_date"]

        lines = email_body.splitlines()

        # Step 1: build links_map from bottom of email
        links_map = self._build_links_map(lines)

        # Step 2: parse articles walking top-to-bottom
        articles = self._parse_articles(
            lines, links_map, source, sender_email, timestamp, newsletter_date
        )

        return articles

    def _build_links_map(self, lines: list[str]) -> dict[int, str]:
        """Scan all lines for [N] https://... patterns and build index → URL map."""
        links_map: dict[int, str] = {}
        for line in lines:
            m = _LINK_ENTRY_RE.match(line.strip())
            if m:
                links_map[int(m.group(1))] = m.group(2)
        return links_map

    def _parse_articles(
        self,
        lines: list[str],
        links_map: dict[int, str],
        source: Source,
        sender_email: str,
        timestamp: datetime,
        newsletter_date: str,
    ) -> list[RawArticle]:
        articles: list[RawArticle] = []
        current_section = "unknown"
        is_quick_links = False

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Stop at end-of-articles marker
            if "Love TLDR?" in line:
                break

            # Detect section header
            section_match = _SECTION_RE.match(line)
            if section_match:
                section_name = section_match.group(1).strip()
                current_section = _SECTION_MAP.get(section_name, section_name.lower())
                is_quick_links = current_section == "quick_links"
                i += 1
                continue

            # Detect article title line
            article_match = _ARTICLE_RE.match(line)
            if article_match:
                title = article_match.group(1).strip()
                link_num = int(article_match.group(3))

                # Skip sponsors
                if "(SPONSOR)" in line.upper():
                    i += 1
                    continue

                url_raw = links_map.get(link_num)
                if not url_raw:
                    i += 1
                    continue

                url = self._clean_url(url_raw)

                # Collect summary paragraph (next non-empty lines, until blank line or next article)
                snippet_lines: list[str] = []
                if not is_quick_links:
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j].strip()
                        if not next_line:
                            j += 1
                            # Stop collecting after first blank line following content
                            if snippet_lines:
                                break
                            continue
                        # Stop if this looks like the next article or a section header
                        if _ARTICLE_RE.match(next_line) or _SECTION_RE.match(next_line):
                            break
                        if "Love TLDR?" in next_line:
                            break
                        snippet_lines.append(next_line)
                        j += 1
                    i = j
                else:
                    i += 1

                snippet = " ".join(snippet_lines).strip()

                try:
                    articles.append(
                        RawArticle(
                            id=str(uuid.uuid4()),
                            title=title,
                            url=url,  # type: ignore[arg-type]
                            source=source,
                            sender_email=sender_email,
                            snippet=snippet,
                            section=current_section,
                            timestamp=timestamp,
                            newsletter_date=newsletter_date,
                        )
                    )
                except Exception:
                    # Skip articles with invalid URLs or data
                    pass

                continue

            i += 1

        return articles
