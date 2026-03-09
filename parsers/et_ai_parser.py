"""
ET AI newsletter parser — HTML email (multipart/mixed).

Confirmed structure:
  Good morning Reader,
  In today's newsletter:
  [Headline 1..N]   ← table of contents, skip

  [Story 1: Headline + teaser + Read More]
  ...

Detection: must verify from_display_name contains "ET AI" OR subject starts with "ET AI:"
before routing to this parser — done in IngestionAgent.

Full article may be behind ET paywall — snippet fallback handled in scraper.
"""
import re
import uuid
from datetime import datetime

from bs4 import BeautifulSoup

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser


class ETAIParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        sender_email: str = email_metadata["sender_email"]
        timestamp: datetime = email_metadata["timestamp"]
        newsletter_date: str = email_metadata["newsletter_date"]

        soup = BeautifulSoup(email_body, "lxml")
        articles: list[RawArticle] = []

        # Find all "Read More" links — skip table-of-contents links (no surrounding teaser)
        read_more_links = soup.find_all("a", string=re.compile(r"read\s+more", re.IGNORECASE))

        for link in read_more_links:
            href = link.get("href", "")
            if not href or not href.startswith("http"):
                continue

            url = self._clean_url(href)

            # Walk up to find the story container
            container = link.find_parent("td") or link.find_parent("div") or link.find_parent("p")
            if not container:
                continue

            full_text = container.get_text(separator=" ", strip=True)
            full_text = re.sub(r"\s*read\s+more\s*", "", full_text, flags=re.IGNORECASE).strip()

            # Skip TOC entries — they're very short (just the headline)
            if len(full_text) < 40:
                continue

            if not full_text:
                continue

            # ET AI has a bold/heading tag for the story headline
            headline_tag = container.find(["h1", "h2", "h3", "h4", "strong", "b"])
            if headline_tag:
                title = headline_tag.get_text(strip=True)
                snippet = full_text.replace(title, "").strip().lstrip(":").strip()
            else:
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
                        source=Source.ET_AI,
                        sender_email=sender_email,
                        snippet=snippet,
                        section="main",
                        timestamp=timestamp,
                        newsletter_date=newsletter_date,
                    )
                )
            except Exception:
                pass

        return articles
