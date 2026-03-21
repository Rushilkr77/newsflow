"""
ETtech Top 5 newsletter parser — HTML email (multipart/mixed).

Confirmed structure (as of 2026-03):
  Each story is a block containing:
    <div style="...font-size:26px;font-weight: bold...">HEADLINE</div>
    <div>...body paragraphs with inline nltrack/native links...</div>
    <td>Liked reading? Share this story</td>   ← story separator

  5 stories total. Full articles are behind the ET paywall.

Strategy: extract titles only. The scraper detects source=="ettech" and
searches inc42.com (primary) then DuckDuckGo (secondary) to get full article
content without hitting the paywall. url is set to a per-article placeholder
since the email URLs are not scrapeable.

India-focused: Indian startups, IT industry, government policy.
"""
import re
import uuid
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from models.article import RawArticle
from models.enums import Source
from parsers.base_parser import BaseParser

# ETtech headline divs use inline style with these markers
_HEADLINE_STYLE_RE = re.compile(r"font-size\s*:\s*2[46]px", re.IGNORECASE)
_LIKED_READING_RE = re.compile(r"liked\s+reading", re.IGNORECASE)


class ETtechParser(BaseParser):
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        sender_email: str = email_metadata["sender_email"]
        timestamp: datetime = email_metadata["timestamp"]
        newsletter_date: str = email_metadata["newsletter_date"]

        soup = BeautifulSoup(email_body, "lxml")
        articles: list[RawArticle] = []

        # Find all headline divs (font-size 24–26px bold)
        headline_divs = [
            tag for tag in soup.find_all("div")
            if _HEADLINE_STYLE_RE.search(tag.get("style", ""))
            and len(tag.get_text(strip=True)) > 20
        ]

        for hdiv in headline_divs:
            title = hdiv.get_text(strip=True)
            if not title or len(title) < 10:
                continue

            # Each article gets a unique placeholder URL. The scraper
            # detects source=="ettech" and performs an inc42/DDG search
            # using the title instead of trying to scrape this URL.
            article_id = str(uuid.uuid4())
            placeholder_url = f"https://ettech.placeholder/{article_id}"

            try:
                articles.append(
                    RawArticle(
                        id=article_id,
                        title=title,
                        url=placeholder_url,  # type: ignore[arg-type]
                        source=Source.ETTECH,
                        sender_email=sender_email,
                        snippet="",  # no snippet — scraper will fetch full text via search
                        section="top5",
                        timestamp=timestamp,
                        newsletter_date=newsletter_date,
                    )
                )
            except Exception:
                pass

        return articles[:5]  # ETtech Top 5 — cap at 5
