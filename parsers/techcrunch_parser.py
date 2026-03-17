"""
TechCrunch newsletter parser — HTML email (multipart/alternative).

Confirmed structure:
  TechCrunch Top 3          ← highest priority stories
  Article Title : Summary. Read More

  Morning/Afternoon Must-Reads  ← main content
  Article Title : Summary. Read More

  Last but Not Least        ← usually 1 article, lower priority
  Article Title : Summary. Read More

Skip: "A message from [sponsor]" blocks.
URLs are embedded in "Read More" <a> tags.
"""
import re
import uuid
from datetime import datetime

from bs4 import BeautifulSoup

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser


# Section header prefixes in order of specificity (longer first to avoid partial matches)
# Each entry: (prefix_to_match, section_id)
_SECTION_HEADERS: list[tuple[str, str]] = [
    ("techcrunch top 3", "top3"),
    ("top 3", "top3"),
    ("morning must-reads", "must_reads"),
    ("afternoon must-reads", "must_reads"),
    ("must-reads", "must_reads"),
    ("must reads", "must_reads"),
    ("last but not least", "last_but_not_least"),
]


class TechCrunchParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        sender_email: str = email_metadata["sender_email"]
        timestamp: datetime = email_metadata["timestamp"]
        newsletter_date: str = email_metadata["newsletter_date"]

        soup = BeautifulSoup(email_body, "lxml")
        articles: list[RawArticle] = []

        current_section = "must_reads"

        for td in soup.find_all("td"):
            text = td.get_text(separator=" ", strip=True)
            text_lower = text.lower()

            # Skip sponsor blocks
            if "a message from" in text_lower or "(sponsor)" in text_lower:
                continue

            # Detect section header prefix — update section and strip from text body.
            # Handles compound headers like "TechCrunch Top 3 Article Title : ..."
            # and standalone headers like "Morning Must-Reads".
            body_text = text
            for header, section_id in _SECTION_HEADERS:
                if text_lower.startswith(header):
                    current_section = section_id
                    body_text = text[len(header):].strip()
                    break

            # Look for "Read More" link within this cell
            read_more = td.find("a", string=re.compile(r"read\s+more", re.IGNORECASE))
            if not read_more:
                continue

            href = read_more.get("href", "")
            if not href or not href.startswith("http"):
                continue

            url = self._clean_url(href)

            # Extract title and snippet from the text before "Read More"
            # Pattern: "Article Title : One sentence summary. Read More"
            full_text = body_text.replace("Read More", "").strip()
            if " : " in full_text:
                parts = full_text.split(" : ", 1)
                title = parts[0].strip()
                snippet = parts[1].strip().rstrip(".")
            else:
                # Fallback: first sentence is title, rest is snippet
                sentences = full_text.split(". ", 1)
                title = sentences[0].strip()
                snippet = sentences[1].strip() if len(sentences) > 1 else ""

            if not title or len(title) < 5:
                continue

            try:
                articles.append(
                    RawArticle(
                        id=str(uuid.uuid4()),
                        title=title,
                        url=url,  # type: ignore[arg-type]
                        source=Source.TECHCRUNCH,
                        sender_email=sender_email,
                        snippet=snippet,
                        section=current_section,
                        timestamp=timestamp,
                        newsletter_date=newsletter_date,
                    )
                )
            except Exception:
                pass

        return articles
