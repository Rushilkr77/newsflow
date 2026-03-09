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


_SECTION_PRIORITIES = {
    "top 3": "top3",
    "must-reads": "must_reads",
    "must reads": "must_reads",
    "last but not least": "last_but_not_least",
}


class TechCrunchParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        sender_email: str = email_metadata["sender_email"]
        timestamp: datetime = email_metadata["timestamp"]
        newsletter_date: str = email_metadata["newsletter_date"]

        soup = BeautifulSoup(email_body, "lxml")
        articles: list[RawArticle] = []

        # Walk through all text nodes looking for section headers and article blocks
        current_section = "must_reads"

        # Find all <a> tags with "Read More" text — these are article links
        # But we need title and snippet too, so parse the surrounding structure

        # Strategy: find all text blocks that contain article info
        # TechCrunch emails use <td> cells for each article
        for td in soup.find_all("td"):
            text = td.get_text(separator=" ", strip=True)

            # Detect section headers
            text_lower = text.lower()
            for header_text, section_id in _SECTION_PRIORITIES.items():
                if text_lower.strip() == header_text or text_lower.startswith(header_text + " "):
                    current_section = section_id
                    break

            # Skip sponsor blocks
            if "a message from" in text_lower or "(sponsor)" in text_lower:
                continue

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
            full_text = text.replace("Read More", "").strip()
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
