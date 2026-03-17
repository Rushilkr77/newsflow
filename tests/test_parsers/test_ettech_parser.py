"""
Tests for ETtechParser.

IMPORTANT: These tests require a real email fixture at:
  tests/fixtures/ettech_sample.html

To obtain it:
  1. Open Gmail and find a recent email from newsletter@ettech.com ("ETtech Top 5")
  2. Open the email, right-click → View page source (or use Gmail's "Show original")
  3. Copy the HTML body and save it to tests/fixtures/ettech_sample.html
  4. Re-run: python -m pytest tests/test_parsers/test_ettech_parser.py -v
"""
import os
from datetime import datetime

import pytest

from models.article import RawArticle
from parsers.ettech_parser import ETtechParser

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "..", "fixtures", "ettech_sample.html")

_METADATA = {
    "sender_email": "newsletter@ettech.com",
    "timestamp": datetime(2026, 3, 12, 14, 30, 0),
    "newsletter_date": "2026-03-12",
}


@pytest.fixture
def ettech_html():
    if not os.path.exists(FIXTURE_PATH):
        pytest.skip(
            "Missing fixture: tests/fixtures/ettech_sample.html — "
            "save the raw HTML body of a real ETtech Top 5 email there, then re-run."
        )
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return f.read()


def test_ettech_parser_returns_articles(ettech_html):
    articles = ETtechParser().parse(ettech_html, _METADATA)
    assert len(articles) > 0, "Parser returned no articles"
    for a in articles:
        RawArticle.model_validate(a.model_dump())  # Pydantic v2 validation


def test_ettech_parser_caps_at_five(ettech_html):
    articles = ETtechParser().parse(ettech_html, _METADATA)
    assert len(articles) <= 5, f"Expected at most 5 articles, got {len(articles)}"


def test_ettech_parser_source_field(ettech_html):
    articles = ETtechParser().parse(ettech_html, _METADATA)
    for a in articles:
        assert a.source == "ettech", f"Unexpected source: {a.source}"


def test_ettech_parser_section_field(ettech_html):
    articles = ETtechParser().parse(ettech_html, _METADATA)
    for a in articles:
        assert a.section == "top5", f"Expected section='top5', got {a.section!r}"


def test_ettech_parser_no_empty_titles(ettech_html):
    articles = ETtechParser().parse(ettech_html, _METADATA)
    for a in articles:
        assert len(a.title) >= 5, f"Title too short: {a.title!r}"


def test_ettech_parser_urls_are_clean(ettech_html):
    articles = ETtechParser().parse(ettech_html, _METADATA)
    for a in articles:
        url_str = str(a.url)
        assert "utm_" not in url_str, f"utm_ param not stripped from URL: {url_str}"


def test_ettech_parser_metadata_fields(ettech_html):
    articles = ETtechParser().parse(ettech_html, _METADATA)
    for a in articles:
        assert a.sender_email == "newsletter@ettech.com"
        assert a.newsletter_date == "2026-03-12"
