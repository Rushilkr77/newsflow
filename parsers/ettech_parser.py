"""
ETtech Top 5 newsletter parser — HTML email (multipart/mixed).

Confirmed structure:
  Daily Top 5
  A closer look at today's biggest tech and startup stories...

  [Story 1 headline + teaser paragraph + Read More link]
  [Story 2 ...]
  ... (exactly 5 stories)

India-focused: Indian startups, IT industry, government policy.
Full article may be behind ET paywall — snippet fallback handled in scraper.
"""
import re
import uuid
from datetime import datetime

from bs4 import BeautifulSoup

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser


class ETtechParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        sender_email: str = email_metadata["sender_email"]
        timestamp: datetime = email_metadata["timestamp"]
        newsletter_date: str = email_metadata["newsletter_date"]

        soup = BeautifulSoup(email_body, "lxml")
        articles: list[RawArticle] = []

        # Find all "Read More" links — each is one story
        read_more_links = soup.find_all("a", string=re.compile(r"read\s+more", re.IGNORECASE))

        for link in read_more_links:
            href = link.get("href", "")
            if not href or not href.startswith("http"):
                continue

            url = self._clean_url(href)

            # Walk up the DOM to find the containing block with title + teaser
            container = link.find_parent("td") or link.find_parent("div") or link.find_parent("p")
            if not container:
                continue

            # Get all text in the container, excluding the "Read More" text
            full_text = container.get_text(separator=" ", strip=True)
            full_text = re.sub(r"\s*read\s+more\s*", "", full_text, flags=re.IGNORECASE).strip()

            if not full_text or len(full_text) < 10:
                continue

            # Try to split into headline + teaser
            # ETtech usually has a bold headline followed by teaser text
            headline_tag = container.find(["h1", "h2", "h3", "h4", "strong", "b"])
            if headline_tag:
                title = headline_tag.get_text(strip=True)
                snippet = full_text.replace(title, "").strip().lstrip(":").strip()
            else:
                # Fallback: first sentence as title
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
                        source=Source.ETTECH,
                        sender_email=sender_email,
                        snippet=snippet,
                        section="top5",
                        timestamp=timestamp,
                        newsletter_date=newsletter_date,
                    )
                )
            except Exception:
                pass

        return articles[:5]  # ETtech Top 5 — cap at 5
