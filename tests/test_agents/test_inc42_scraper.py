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

FAKE_SEARCH_HTML_WITH_RESULTS = """
<!DOCTYPE html>
<html>
<body>
  <article>
    <h2><a href="https://inc42.com/buzz/openai-gpt5-launch-india/">OpenAI GPT-5 Launches in India</a></h2>
    <p>OpenAI has officially launched GPT-5 in India...</p>
  </article>
  <article>
    <h2><a href="https://inc42.com/news/another-story/">Another Story</a></h2>
    <p>Some other content.</p>
  </article>
</body>
</html>
"""

FAKE_SEARCH_HTML_NO_RESULTS = """
<!DOCTYPE html>
<html>
<body>
  <p>No results found.</p>
</body>
</html>
"""

FAKE_SEARCH_HTML_ONLY_INVALID_URLS = """
<!DOCTYPE html>
<html>
<body>
  <article>
    <h2><a href="https://inc42.com/tag/openai/">Tag: OpenAI</a></h2>
  </article>
  <article>
    <h2><a href="https://inc42.com/author/reporter/">Reporter</a></h2>
  </article>
</body>
</html>
"""

FAKE_ARTICLE_TEXT = (
    "OpenAI has officially launched GPT-5 in India with new pricing for enterprise customers. "
    "The model is available through the OpenAI API and ChatGPT. "
    "This marks a significant expansion of OpenAI's presence in the Indian market. "
    "Several Indian startups are already integrating the model into their products."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(html: str, status_code: int = 200) -> MagicMock:
    """Return a mock requests.Response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html
    resp.raise_for_status = MagicMock()  # does nothing (success)
    return resp


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

class TestSearchAndFetchSuccess:
    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=FAKE_ARTICLE_TEXT)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    @patch("scraper.inc42_scraper.requests.get")
    def test_returns_scraped_text(self, mock_get, mock_fetch_url, mock_extract):
        mock_get.return_value = _make_response(FAKE_SEARCH_HTML_WITH_RESULTS)

        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result == FAKE_ARTICLE_TEXT

    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=FAKE_ARTICLE_TEXT)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    @patch("scraper.inc42_scraper.requests.get")
    def test_uses_first_valid_article_url(self, mock_get, mock_fetch_url, mock_extract):
        """The scraper should pick the first /buzz/ or /news/ or /features/ URL."""
        mock_get.return_value = _make_response(FAKE_SEARCH_HTML_WITH_RESULTS)

        scraper = Inc42Scraper()
        scraper.search_and_fetch("OpenAI GPT-5 launch India")

        # trafilatura should have been called with the first result URL
        mock_fetch_url.assert_called_once_with(
            "https://inc42.com/buzz/openai-gpt5-launch-india/"
        )

    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=FAKE_ARTICLE_TEXT)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    @patch("scraper.inc42_scraper.requests.get")
    def test_search_url_encodes_title(self, mock_get, mock_fetch_url, mock_extract):
        """Special characters in the title must be URL-encoded."""
        mock_get.return_value = _make_response(FAKE_SEARCH_HTML_WITH_RESULTS)

        scraper = Inc42Scraper()
        scraper.search_and_fetch("AI & ML: India's Future")

        call_url = mock_get.call_args[0][0]
        # The query string should not contain raw spaces or '&'
        assert " " not in call_url
        assert call_url.startswith("https://inc42.com/?s=")


# ---------------------------------------------------------------------------
# No-results path
# ---------------------------------------------------------------------------

class TestSearchAndFetchNoResults:
    @patch("scraper.inc42_scraper.requests.get")
    def test_returns_none_when_no_article_links(self, mock_get):
        mock_get.return_value = _make_response(FAKE_SEARCH_HTML_NO_RESULTS)

        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result is None

    @patch("scraper.inc42_scraper.requests.get")
    def test_returns_none_when_only_invalid_urls(self, mock_get):
        """Tag/author pages are not valid article URLs — should be skipped."""
        mock_get.return_value = _make_response(FAKE_SEARCH_HTML_ONLY_INVALID_URLS)

        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result is None


# ---------------------------------------------------------------------------
# Short-text guard
# ---------------------------------------------------------------------------

class TestSearchAndFetchShortText:
    @patch("scraper.inc42_scraper.trafilatura.extract", return_value="Too short.")
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    @patch("scraper.inc42_scraper.requests.get")
    def test_returns_none_when_extracted_text_too_short(
        self, mock_get, mock_fetch_url, mock_extract
    ):
        mock_get.return_value = _make_response(FAKE_SEARCH_HTML_WITH_RESULTS)

        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result is None

    @patch("scraper.inc42_scraper.trafilatura.extract", return_value=None)
    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value="<html>...</html>")
    @patch("scraper.inc42_scraper.requests.get")
    def test_returns_none_when_trafilatura_returns_none(
        self, mock_get, mock_fetch_url, mock_extract
    ):
        mock_get.return_value = _make_response(FAKE_SEARCH_HTML_WITH_RESULTS)

        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result is None


# ---------------------------------------------------------------------------
# Network error path
# ---------------------------------------------------------------------------

class TestSearchAndFetchNetworkErrors:
    @patch("scraper.inc42_scraper.requests.get", side_effect=ConnectionError("timeout"))
    def test_returns_none_on_connection_error(self, mock_get):
        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result is None

    @patch("scraper.inc42_scraper.requests.get", side_effect=Exception("unexpected"))
    def test_returns_none_on_generic_exception(self, mock_get):
        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result is None

    @patch("scraper.inc42_scraper.requests.get")
    def test_returns_none_on_http_error(self, mock_get):
        from requests.exceptions import HTTPError

        resp = MagicMock()
        resp.raise_for_status.side_effect = HTTPError("503 Service Unavailable")
        mock_get.return_value = resp

        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result is None

    @patch("scraper.inc42_scraper.trafilatura.fetch_url", return_value=None)
    @patch("scraper.inc42_scraper.requests.get")
    def test_returns_none_when_trafilatura_fetch_fails(self, mock_get, mock_fetch_url):
        """trafilatura.fetch_url returning None (e.g. connection refused) is handled."""
        mock_get.return_value = _make_response(FAKE_SEARCH_HTML_WITH_RESULTS)

        scraper = Inc42Scraper()
        result = scraper.search_and_fetch("OpenAI GPT-5 launch India")

        assert result is None
