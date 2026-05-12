"""
Unit tests for Inc42Scraper.

Mocks all network calls — no real HTTP requests are made.
Run: pytest tests/test_agents/test_inc42_scraper.py -v
"""
from unittest.mock import MagicMock, patch

import pytest

from scraper.inc42_scraper import Inc42Scraper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_DDG_RESULTS = [
    {"href": "https://inc42.com/buzz/openai-gpt5-launch-india/", "title": "OpenAI GPT-5 Launches in India"},
    {"href": "https://inc42.com/news/another-story/", "title": "Another Story"},
]

FAKE_DDG_RESULTS_STARTUPS = [
    {"href": "https://inc42.com/startups/news/dailyobjects-funding-round/", "title": "DailyObjects funding"},
]

FAKE_DDG_RESULTS_NO_VALID = [
    {"href": "https://inc42.com/tag/openai/", "title": "Tag: OpenAI"},
    {"href": "https://inc42.com/author/reporter/", "title": "Reporter"},
]

FAKE_ARTICLE_TEXT = (
    "OpenAI has officially launched GPT-5 in India with new pricing for enterprise customers. "
    "The model is available through the OpenAI API and ChatGPT. "
    "This marks a significant expansion of OpenAI's presence in the Indian market. "
    "Several Indian startups are already integrating the model into their products."
)


# ---------------------------------------------------------------------------
# Helper to mock DDGS
# ---------------------------------------------------------------------------

def _mock_ddgs(results):
    """Return a context manager that patches duckduckgo_search.DDGS."""
    mock = MagicMock()
    mock.return_value.__enter__ = MagicMock(return_value=mock.return_value)
    mock.return_value.__exit__ = MagicMock(return_value=False)
    mock.return_value.text.return_value = iter(results)
    return patch("scraper.inc42_scraper.DDGS", mock)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

class TestSearchAndFetchSuccess:
    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=FAKE_ARTICLE_TEXT)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    def test_returns_scraped_text(self, mock_fetch_url, mock_extract):
        with _mock_ddgs(FAKE_DDG_RESULTS):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("OpenAI GPT-5 launch India")
        assert result == FAKE_ARTICLE_TEXT

    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=FAKE_ARTICLE_TEXT)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    def test_uses_first_valid_article_url(self, mock_fetch_url, mock_extract):
        """Scraper should pick the first valid URL from DDG results."""
        with _mock_ddgs(FAKE_DDG_RESULTS):
            scraper = Inc42Scraper()
            scraper.search_and_fetch("OpenAI GPT-5 launch India")
        mock_fetch_url.assert_called_once_with("https://inc42.com/buzz/openai-gpt5-launch-india/")

    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=FAKE_ARTICLE_TEXT)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    def test_searches_with_site_prefix(self, mock_fetch_url, mock_extract):
        """DDG query must use site:inc42.com prefix."""
        mock_ddgs = MagicMock()
        mock_ddgs.return_value.text.return_value = iter(FAKE_DDG_RESULTS)
        with patch("scraper.inc42_scraper.DDGS", mock_ddgs):
            scraper = Inc42Scraper()
            scraper.search_and_fetch("OpenAI GPT-5 launch India")
        call_query = mock_ddgs.return_value.text.call_args[0][0]
        assert call_query.startswith("site:inc42.com ")

    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=FAKE_ARTICLE_TEXT)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    def test_accepts_startups_url(self, mock_fetch_url, mock_extract):
        """/startups/ path is a valid Inc42 article URL."""
        with _mock_ddgs(FAKE_DDG_RESULTS_STARTUPS):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("DailyObjects funding round")
        assert result == FAKE_ARTICLE_TEXT


# ---------------------------------------------------------------------------
# No-results path
# ---------------------------------------------------------------------------

class TestSearchAndFetchNoResults:
    def test_returns_none_when_only_invalid_urls(self):
        """Tag/author pages are not valid article URLs."""
        with _mock_ddgs(FAKE_DDG_RESULTS_NO_VALID):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("OpenAI GPT-5 launch India")
        assert result is None

    def test_returns_none_when_empty_results(self):
        with _mock_ddgs([]):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("OpenAI GPT-5 launch India")
        assert result is None

    def test_returns_none_on_non_inc42_url(self):
        """DDG might return results from other domains — must be filtered out."""
        with _mock_ddgs([{"href": "https://techcrunch.com/some-story/"}]):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("Some startup story")
        assert result is None


# ---------------------------------------------------------------------------
# Short-text guard
# ---------------------------------------------------------------------------

class TestSearchAndFetchShortText:
    @patch("scraper.inc42_scraper.trafilatura.extract", return_value="Too short.")
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    def test_returns_none_when_extracted_text_too_short(self, mock_fetch_url, mock_extract):
        with _mock_ddgs(FAKE_DDG_RESULTS):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("OpenAI GPT-5 launch India")
        assert result is None

    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=None)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    def test_returns_none_when_trafilatura_returns_none(self, mock_fetch_url, mock_extract):
        with _mock_ddgs(FAKE_DDG_RESULTS):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("OpenAI GPT-5 launch India")
        assert result is None


# ---------------------------------------------------------------------------
# Network error path
# ---------------------------------------------------------------------------

class TestSearchAndFetchNetworkErrors:
    def test_returns_none_on_ddg_error(self):
        mock_ddgs = MagicMock()
        mock_ddgs.return_value.text.side_effect = Exception("rate limited")
        with patch("scraper.inc42_scraper.DDGS", mock_ddgs):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("OpenAI GPT-5 launch India")
        assert result is None

    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value=None)
    def test_returns_none_when_trafilatura_fetch_fails(self, mock_fetch_url):
        with _mock_ddgs(FAKE_DDG_RESULTS):
            scraper = Inc42Scraper()
            result = scraper.search_and_fetch("OpenAI GPT-5 launch India")
        assert result is None
