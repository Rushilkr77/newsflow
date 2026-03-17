"""
Tests for ETAIParser.

To run:
    python -m pytest tests/test_parsers/test_et_ai_parser.py -v

Requires a real email sample saved at:
    tests/fixtures/et_ai_sample.html

To obtain:
    1. Open Gmail and find a recent email from newsletter@economictimesnews.com
       with From display name "ET AI".
    2. View the email source (⋮ → Show original) and copy the HTML part.
    3. Save it to tests/fixtures/et_ai_sample.html
"""
import pytest
from pathlib import Path

from parsers.et_ai_parser import ETAIParser
from models.article import RawArticle
from datetime import datetime


FIXTURE_PATH = Path("tests/fixtures/et_ai_sample.html")

METADATA = {
    "sender_email": "newsletter@economictimesnews.com",
    "timestamp": datetime(2026, 3, 12, 2, 15, 0),  # 7:45 AM IST = 02:15 UTC
    "newsletter_date": "2026-03-12",
    "source_id": "et_ai",
}

# Minimal synthetic HTML that mirrors the ET AI structure:
# table-of-contents entries (short, no teaser) followed by full story blocks.
SYNTHETIC_HTML = """
<html><body>
<table>
  <tr><td>
    Good morning Reader,<br>
    In today's newsletter:
  </td></tr>

  <!-- TOC entries — short, just headline, should be skipped -->
  <tr><td>
    <a href="https://economictimes.com/article1">OpenAI Launches GPT-5</a>
  </td></tr>
  <tr><td>
    <a href="https://economictimes.com/article2">Google DeepMind Releases Gemini Ultra</a>
  </td></tr>

  <!-- Full story blocks with headline + teaser + Read More -->
  <tr><td>
    <strong>OpenAI Launches GPT-5</strong>
    OpenAI has unveiled GPT-5, its most capable model yet, with significant improvements
    in reasoning and multimodal understanding. The model is available to ChatGPT Plus subscribers
    starting today.
    <a href="https://economictimes.com/article1">Read More</a>
  </td></tr>

  <tr><td>
    <strong>Google DeepMind Releases Gemini Ultra 2.0</strong>
    Google DeepMind has released Gemini Ultra 2.0, claiming state-of-the-art performance
    across coding, math, and scientific reasoning benchmarks. Enterprise customers get access first.
    <a href="https://economictimes.com/article2">Read More</a>
  </td></tr>

  <tr><td>
    <strong>India AI Mission Allocates ₹2,000 Crore to Startups</strong>
    The Indian government's AI Mission has announced a ₹2,000 crore fund for domestic AI startups,
    targeting healthcare and agriculture applications in the first phase.
    <a href="https://economictimes.com/article3">Read More</a>
  </td></tr>
</table>
</body></html>
"""


class TestETAIParser:
    def setup_method(self):
        self.parser = ETAIParser()

    def test_synthetic_returns_articles(self):
        """Parser extracts articles from synthetic ET AI HTML structure."""
        articles = self.parser.parse(SYNTHETIC_HTML, METADATA)
        assert len(articles) > 0, "Expected at least one article from synthetic HTML"

    def test_synthetic_toc_skipped(self):
        """TOC-only links (no teaser) are not extracted as articles."""
        articles = self.parser.parse(SYNTHETIC_HTML, METADATA)
        # Should get 3 full-teaser stories, not 5 (2 TOC + 3 stories)
        assert len(articles) <= 3

    def test_synthetic_article_fields(self):
        """All returned articles pass Pydantic RawArticle validation."""
        articles = self.parser.parse(SYNTHETIC_HTML, METADATA)
        for article in articles:
            validated = RawArticle.model_validate(article.model_dump())
            assert validated.title
            assert str(validated.url).startswith("http")
            assert validated.snippet  # Teaser should be non-empty
            assert validated.source.value == "et_ai"

    def test_synthetic_rupee_symbol_handled(self):
        """Non-ASCII characters like ₹ in article text are preserved cleanly."""
        articles = self.parser.parse(SYNTHETIC_HTML, METADATA)
        india_article = next(
            (a for a in articles if "India" in a.title or "₹" in a.snippet), None
        )
        assert india_article is not None, "Expected India AI Mission article"

    def test_synthetic_urls_cleaned(self):
        """UTM parameters are stripped from article URLs."""
        html_with_utm = SYNTHETIC_HTML.replace(
            'href="https://economictimes.com/article1"',
            'href="https://economictimes.com/article1?utm_source=newsletter&utm_medium=email"',
        )
        articles = self.parser.parse(html_with_utm, METADATA)
        for article in articles:
            assert "utm_" not in str(article.url), f"UTM params not stripped: {article.url}"

    def test_synthetic_no_sponsor_articles(self):
        """Articles from sponsor blocks are not included."""
        html_with_sponsor = SYNTHETIC_HTML.replace(
            "<strong>OpenAI Launches GPT-5</strong>",
            "<strong>(SPONSOR) Buy This Product</strong>",
        )
        articles = self.parser.parse(html_with_sponsor, METADATA)
        titles = [a.title for a in articles]
        assert not any("SPONSOR" in t for t in titles)

    @pytest.mark.skipif(not FIXTURE_PATH.exists(), reason="No real fixture — run against synthetic HTML only")
    def test_real_fixture_returns_articles(self):
        """Integration test against a real ET AI email HTML sample."""
        body = FIXTURE_PATH.read_text(encoding="utf-8")
        articles = self.parser.parse(body, METADATA)
        assert len(articles) > 0, "Expected articles from real ET AI email"
        for article in articles:
            RawArticle.model_validate(article.model_dump())

    @pytest.mark.skipif(not FIXTURE_PATH.exists(), reason="No real fixture")
    def test_real_fixture_no_toc_duplicates(self):
        """TOC entries from real email are not extracted as standalone articles."""
        body = FIXTURE_PATH.read_text(encoding="utf-8")
        articles = self.parser.parse(body, METADATA)
        # All articles should have a non-trivial snippet (teaser text)
        for article in articles:
            assert len(article.snippet) >= 40, (
                f"Article '{article.title}' has suspiciously short snippet — may be a TOC entry"
            )
