"""
Unit tests for:
  - llm_client.chat() OpenRouter routing and fallback behaviour
  - SummarizerAgent._validate_p0_summary() quality gate
  - SummarizerAgent._fetch_full_text() now includes P2 articles
"""
import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIError


def _api_error(message: str) -> APIError:
    """Build a minimal APIError instance for use as a mock side_effect."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return APIError(message, request, body=None)


# ---------------------------------------------------------------------------
# Helpers: build a minimal CuratedArticle without importing the heavy agent
# ---------------------------------------------------------------------------

def _make_article(priority: str, full_text: str | None = None, snippet: str = "test snippet"):
    """Return a CuratedArticle-like object via the real Pydantic model."""
    from models.article import CuratedArticle
    from models.enums import Priority, Source, Category

    return CuratedArticle(
        id="test-id",
        title="Test Article Title About AI",
        url="https://example.com/article",
        source=Source.TLDR_AI,
        all_sources=[Source.TLDR_AI],
        priority=Priority(priority),
        relevance_score=80.0,
        category=Category.AI_PRODUCTS_TOOLS,
        estimated_podcast_duration_sec=120,
        snippet=snippet,
        full_text=full_text,
        discussion_hooks=[],
    )


# ---------------------------------------------------------------------------
# llm_client tests
# ---------------------------------------------------------------------------

class TestLlmClientOpenRouter:
    """Tests for the OpenRouter routing logic in utils/llm_client.py."""

    def test_chat_falls_back_to_local_when_openrouter_model_is_none(self):
        """chat() with openrouter_model=None must never call _chat_openrouter."""
        with patch("utils.llm_client._USE_LOCAL", True), \
             patch("utils.llm_client._chat_ollama", return_value="local result") as mock_local, \
             patch("utils.llm_client._chat_openrouter") as mock_or:
            from utils.llm_client import chat
            result = chat("claude-haiku-4-5", "sys", "user", openrouter_model=None)
        assert result == "local result"
        mock_local.assert_called_once()
        mock_or.assert_not_called()

    def test_chat_falls_back_to_local_when_api_key_missing(self):
        """chat() with openrouter_model set but no key must use the local path."""
        with patch("utils.llm_client._USE_LOCAL", True), \
             patch("utils.llm_client.OPENROUTER_API_KEY", ""), \
             patch("utils.llm_client._chat_ollama", return_value="local result") as mock_local, \
             patch("utils.llm_client._chat_openrouter") as mock_or:
            from utils.llm_client import chat
            result = chat(
                "claude-haiku-4-5", "sys", "user",
                openrouter_model="meta-llama/llama-3.3-70b-instruct:free",
            )
        assert result == "local result"
        mock_local.assert_called_once()
        mock_or.assert_not_called()

    def test_chat_routes_to_openrouter_when_key_present(self):
        """chat() must call _chat_openrouter when both model and key are provided."""
        with patch("utils.llm_client._USE_LOCAL", False), \
             patch("utils.llm_client.OPENROUTER_API_KEY", "sk-or-test-key"), \
             patch("utils.llm_client._chat_openrouter", return_value="or result") as mock_or, \
             patch("utils.llm_client._chat_anthropic") as mock_ant:
            from utils.llm_client import chat
            result = chat(
                "claude-haiku-4-5", "sys", "user",
                openrouter_model="meta-llama/llama-3.3-70b-instruct:free",
            )
        assert result == "or result"
        mock_or.assert_called_once_with(
            "meta-llama/llama-3.3-70b-instruct:free", "sys", "user", 2048
        )
        mock_ant.assert_not_called()

    def test_chat_falls_back_to_anthropic_on_openrouter_error(self):
        """If _chat_openrouter raises an OpenAI APIError, chat() falls through to Anthropic."""
        with patch("utils.llm_client._USE_LOCAL", False), \
             patch("utils.llm_client.OPENROUTER_API_KEY", "sk-or-test-key"), \
             patch("utils.llm_client._chat_openrouter", side_effect=_api_error("rate limit")), \
             patch("utils.llm_client._chat_anthropic", return_value="anthropic result") as mock_ant:
            from utils.llm_client import chat
            result = chat(
                "claude-haiku-4-5", "sys", "user",
                openrouter_model="meta-llama/llama-3.3-70b-instruct:free",
            )
        assert result == "anthropic result"
        mock_ant.assert_called_once()

    def test_chat_falls_back_to_local_on_openrouter_error(self):
        """If _chat_openrouter raises an OpenAI APIError and _USE_LOCAL=True, falls through to Ollama."""
        with patch("utils.llm_client._USE_LOCAL", True), \
             patch("utils.llm_client.OPENROUTER_API_KEY", "sk-or-test-key"), \
             patch("utils.llm_client._chat_openrouter", side_effect=_api_error("timeout")), \
             patch("utils.llm_client._chat_ollama", return_value="local fallback") as mock_local:
            from utils.llm_client import chat
            result = chat(
                "claude-haiku-4-5", "sys", "user",
                openrouter_model="meta-llama/llama-3.3-70b-instruct:free",
            )
        assert result == "local fallback"
        mock_local.assert_called_once()


# ---------------------------------------------------------------------------
# SummarizerAgent._validate_p0_summary tests
# ---------------------------------------------------------------------------

def _make_summarizer():
    """Instantiate SummarizerAgent with heavy imports mocked out."""
    # Stub out the module-level side-effectful imports
    mcp_stub = types.ModuleType("mcp_servers.article_fetcher_server")
    mcp_stub.fetch_article_content = MagicMock(return_value=None)

    scraper_stub = types.ModuleType("scraper.ddg_scraper")
    scraper_stub.DDGScraper = MagicMock

    inc42_stub = types.ModuleType("scraper.inc42_scraper")
    inc42_stub.Inc42Scraper = MagicMock

    mcp_pkg = types.ModuleType("mcp_servers")
    sys.modules.setdefault("mcp_servers", mcp_pkg)
    sys.modules["mcp_servers.article_fetcher_server"] = mcp_stub
    sys.modules.setdefault("scraper.ddg_scraper", scraper_stub)
    sys.modules.setdefault("scraper.inc42_scraper", inc42_stub)

    # Force reimport so stubs are used
    if "agents.summarizer" in sys.modules:
        del sys.modules["agents.summarizer"]

    from agents.summarizer import SummarizerAgent
    return SummarizerAgent()


GOOD_SUMMARY = (
    "1. CORE NEWS: Company X released a new large language model called Helios that "
    "outperforms GPT-4 on standard benchmarks. "
    "2. SURROUNDING IMPACT: Developers and enterprises building AI applications will "
    "face a new competitive option when choosing foundation model providers. "
    "The move pressures incumbents like OpenAI and Anthropic to accelerate their own "
    "release schedules, which could compress the product lifecycle for AI tools. "
    "Mid-market SaaS companies that embedded a single LLM provider may need to "
    "re-evaluate their vendor lock-in strategies. "
    "3. COMPETITOR CONTEXT: OpenAI's GPT-4 Turbo and Anthropic's Claude series are the "
    "most directly impacted. Google's Gemini team will likely fast-track benchmark "
    "comparisons. Meta's open-source Llama ecosystem gains a commercial rival in the "
    "same performance class, giving enterprise buyers a clearer cost comparison. "
    "4. LAUNCH RATIONALE: Company X built Helios to address a gap in the market for "
    "models that balance reasoning quality with low inference latency. "
    "They identified that most current top-tier models require expensive GPU clusters "
    "to run at production scale, and Helios uses a new sparse attention mechanism to "
    "cut compute costs by thirty percent while maintaining accuracy. "
    "5. HOW IT WORKS: Helios uses a mixture-of-experts architecture with dynamic routing "
    "so only the most relevant parameter subsets activate for each token. "
    "This sparse activation means the effective parameter count during inference is "
    "roughly one-fifth of the full model size, dramatically reducing memory bandwidth "
    "requirements. The team also fine-tuned on a proprietary dataset of high-quality "
    "reasoning chains curated from competitive programming and scientific literature. "
    "6. PM INTERVIEW EDGE: The non-obvious insight is that infrastructure cost is now "
    "the primary competitive moat, not raw model capability. "
    "A strong PM candidate would note that enterprise buyers increasingly evaluate "
    "total cost of ownership over benchmark scores, so the real product decision is "
    "about pricing model design and API rate guarantees rather than model architecture. "
    "Companies that win the next wave will price inference as a utility and lock in "
    "customers through workflow integrations rather than model performance alone."
)  # ~310 words, all 6 headers present


SHORT_SUMMARY = "This is a very short summary. CORE NEWS: something happened. SURROUNDING IMPACT: ok. HOW IT WORKS: unknown. PM INTERVIEW EDGE: none."


class TestValidateP0Summary:
    def setup_method(self):
        self.agent = _make_summarizer()
        self.article = _make_article("P0")

    def test_passes_when_quality_is_sufficient(self):
        """Summary with >= 300 words and >= 4 headers passes without retry."""
        with patch.object(self.agent, "_call_llm") as mock_call:
            result = self.agent._validate_p0_summary(
                self.article, "some content", GOOD_SUMMARY
            )
        assert result == GOOD_SUMMARY
        mock_call.assert_not_called()

    def test_retries_when_word_count_too_low(self):
        """Summary below 300 words triggers a retry call."""
        retry_result = "Retried and improved summary. " * 40
        with patch.object(self.agent, "_call_llm", return_value=retry_result) as mock_call:
            result = self.agent._validate_p0_summary(
                self.article, "some content", SHORT_SUMMARY
            )
        assert result == retry_result
        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args
        assert call_kwargs.kwargs.get("use_openrouter") is True or \
               (call_kwargs.args and "use_openrouter" not in call_kwargs.kwargs)

    def test_retries_when_headers_too_few(self):
        """Summary with < 4 section headers triggers a retry even if word count ok."""
        # Build a summary with >= 300 words but only 2 headers
        sparse_summary = "CORE NEWS: something happened. " + ("extra words " * 25) + "PM EDGE: insight here."
        retry_result = "Full retry result " * 40
        with patch.object(self.agent, "_call_llm", return_value=retry_result) as mock_call:
            result = self.agent._validate_p0_summary(
                self.article, "some content", sparse_summary
            )
        assert result == retry_result
        mock_call.assert_called_once()

    def test_retry_prompt_mentions_word_count_and_sections(self):
        """The retry prompt sent to LLM mentions the actual word count and section count."""
        with patch.object(self.agent, "_call_llm", return_value="retry") as mock_call:
            self.agent._validate_p0_summary(self.article, "content", SHORT_SUMMARY)
        prompt_used = mock_call.call_args.args[0]
        assert "too short" in prompt_used
        assert "6 required sections" in prompt_used

    def test_retry_uses_openrouter(self):
        """_validate_p0_summary retry must pass use_openrouter=True to _call_llm."""
        with patch.object(self.agent, "_call_llm", return_value="retry") as mock_call:
            self.agent._validate_p0_summary(self.article, "content", SHORT_SUMMARY)
        mock_call.assert_called_once()
        _, kwargs = mock_call.call_args
        assert kwargs.get("use_openrouter") is True


# ---------------------------------------------------------------------------
# _fetch_full_text P2 inclusion tests
# ---------------------------------------------------------------------------

class TestFetchFullTextIncludesP2:
    def setup_method(self):
        self.agent = _make_summarizer()

    def test_p2_article_without_full_text_is_included_in_to_fetch(self):
        """P2 article with no full_text must be fetched (not skipped)."""
        article_p2 = _make_article("P2", full_text=None)
        article_p0 = _make_article("P0", full_text=None)
        article_p1 = _make_article("P1", full_text="already fetched")

        # Patch fetch_article_content at the module level inside agents.summarizer
        with patch("agents.summarizer.fetch_article_content", return_value="scraped content") as mock_fetch, \
             patch("agents.summarizer._ddg_scraper") as mock_ddg:
            mock_ddg.search_and_fetch.return_value = None
            self.agent._fetch_full_text([article_p2, article_p0, article_p1])

        # fetch should have been called for p2 and p0 (not p1 — already has full_text)
        assert mock_fetch.call_count == 2

    def test_p2_article_with_full_text_is_skipped(self):
        """P2 article that already has full_text must not be re-fetched."""
        article_p2 = _make_article("P2", full_text="already have it")

        with patch("agents.summarizer.fetch_article_content") as mock_fetch:
            self.agent._fetch_full_text([article_p2])

        mock_fetch.assert_not_called()

    def test_all_priorities_without_full_text_are_fetched(self):
        """P0, P1, and P2 articles without full_text must all be included."""
        articles = [
            _make_article("P0", full_text=None),
            _make_article("P1", full_text=None),
            _make_article("P2", full_text=None),
        ]

        with patch("agents.summarizer.fetch_article_content", return_value="fetched") as mock_fetch, \
             patch("agents.summarizer._ddg_scraper") as mock_ddg:
            mock_ddg.search_and_fetch.return_value = None
            self.agent._fetch_full_text(articles)

        # All three have no full_text, so fetch should be called 3 times
        assert mock_fetch.call_count == 3

    def test_p2_full_text_set_after_successful_fetch(self):
        """P2 article's full_text attribute is updated after a successful fetch."""
        article_p2 = _make_article("P2", full_text=None)
        # Must be >= 200 chars to pass the length check in _fetch_full_text
        fetched = "A" * 250

        with patch("agents.summarizer.fetch_article_content", return_value=fetched), \
             patch("agents.summarizer._ddg_scraper") as mock_ddg:
            mock_ddg.search_and_fetch.return_value = None
            self.agent._fetch_full_text([article_p2])

        assert article_p2.full_text == fetched
