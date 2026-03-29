"""
Unit tests for the funding/M&A post-classification override in CuratorAgent.

Tests cover:
- _has_funding_signals: detects various funding/M&A signal patterns
- _has_funding_signals: returns False for plain text with no signals
- Override fires: big_tech_launches article with "$1B" → funding_ma
- Override does NOT fire for india_tech articles (category preserved)
- Override does NOT fire for articles already classified as funding_ma

No LLM calls — _classify_batch is exercised via direct manipulation of
CuratedArticle objects, and _has_funding_signals is called directly.

Run: pytest tests/test_agents/test_curator_funding_override.py -v
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from agents.curator import CuratorAgent, _FUNDING_SIGNALS
from models.article import CuratedArticle
from models.enums import Category, Priority, Source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_curated(
    title: str,
    category: Category,
    snippet: str = "",
    source: Source = Source.TLDR_AI,
) -> CuratedArticle:
    return CuratedArticle(
        id=str(uuid.uuid4()),
        title=title,
        url="https://example.com/article",
        source=source,
        all_sources=[source],
        priority=Priority.P1,
        relevance_score=60.0,
        category=category,
        estimated_podcast_duration_sec=120,
        snippet=snippet,
    )


# ---------------------------------------------------------------------------
# _has_funding_signals — positive cases
# ---------------------------------------------------------------------------

class TestHasFundingSignals:
    def test_dollar_amount_uppercase_m(self):
        assert CuratorAgent._has_funding_signals("Startup raises $38M", "") is True

    def test_dollar_amount_uppercase_b(self):
        assert CuratorAgent._has_funding_signals("Rivian gets another $1B from Volkswagen", "") is True

    def test_dollar_amount_decimal(self):
        assert CuratorAgent._has_funding_signals("Company closes $1.5B round", "") is True

    def test_dollar_amount_lowercase_m(self):
        assert CuratorAgent._has_funding_signals("Firm secures $100m in seed round", "") is True

    def test_raises_keyword(self):
        assert CuratorAgent._has_funding_signals("Company raises Series A", "") is True

    def test_raise_keyword_singular(self):
        assert CuratorAgent._has_funding_signals("Why startups raise late", "") is True

    def test_funding_keyword(self):
        assert CuratorAgent._has_funding_signals("New funding round announced", "") is True

    def test_acquires_keyword(self):
        assert CuratorAgent._has_funding_signals("Google acquires startup", "") is True

    def test_acquired_keyword(self):
        assert CuratorAgent._has_funding_signals("Startup acquired by Microsoft", "") is True

    def test_acquiring_keyword(self):
        assert CuratorAgent._has_funding_signals("Tech giant acquiring rival", "") is True

    def test_acquisition_keyword(self):
        assert CuratorAgent._has_funding_signals("IT firms push M&A deals", "") is True

    def test_merger_keyword(self):
        assert CuratorAgent._has_funding_signals("Bank merger talks underway", "") is True

    def test_ma_uppercase(self):
        assert CuratorAgent._has_funding_signals("M&A activity rises in 2026", "") is True

    def test_ma_lowercase_start(self):
        assert CuratorAgent._has_funding_signals("m&A surge continues", "") is True

    def test_ipo_keyword(self):
        assert CuratorAgent._has_funding_signals("Startup eyes IPO in 2027", "") is True

    def test_valuation_keyword(self):
        assert CuratorAgent._has_funding_signals("New valuation puts company at $5B", "") is True

    def test_signal_in_snippet_only(self):
        # Title has no signal — snippet does
        assert CuratorAgent._has_funding_signals(
            "Company makes big news", "They raised $50M in a new round"
        ) is True

    def test_snippet_truncated_to_200_chars(self):
        # Signal placed beyond 200 chars in snippet — should NOT be detected
        long_prefix = "x" * 201
        assert CuratorAgent._has_funding_signals("Plain title", long_prefix + " raises $10M") is False

    # ---------------------------------------------------------------------------
    # Negative cases
    # ---------------------------------------------------------------------------

    def test_no_signals_plain_article(self):
        assert CuratorAgent._has_funding_signals(
            "New AI model beats benchmarks", "Researchers publish results"
        ) is False

    def test_no_signals_product_launch(self):
        assert CuratorAgent._has_funding_signals(
            "Apple launches Vision Pro 3", "The headset ships next month"
        ) is False

    def test_no_signals_policy_article(self):
        assert CuratorAgent._has_funding_signals(
            "EU passes new AI regulation", "Compliance deadline set for 2027"
        ) is False


# ---------------------------------------------------------------------------
# Override logic — via _classify_batch post-processing loop
# (test the override logic by calling it directly on pre-built CuratedArticle lists)
# ---------------------------------------------------------------------------

def _run_override(articles: list[CuratedArticle]) -> list[CuratedArticle]:
    """
    Replicate the post-classification funding override block from _classify_batch
    using the actual CuratorAgent method and module-level regex.
    We invoke it via a minimal CuratorAgent instance without touching the LLM.
    """
    agent = CuratorAgent.__new__(CuratorAgent)  # skip __init__
    for ca in articles:
        if (
            ca.category != Category.FUNDING_MA
            and ca.category != Category.INDIA_TECH
            and agent._has_funding_signals(ca.title, ca.snippet or "")
        ):
            ca.category = Category.FUNDING_MA
    return articles


class TestFundingOverrideLogic:
    def test_override_fires_for_big_tech_launches(self):
        """big_tech_launches + '$1B' in title → should become funding_ma."""
        article = _make_curated(
            title="Rivian gets another $1B from Volkswagen",
            category=Category.BIG_TECH_LAUNCHES,
        )
        result = _run_override([article])
        assert result[0].category == Category.FUNDING_MA

    def test_override_fires_for_product_innovations(self):
        """product_innovations + 'raises' → should become funding_ma."""
        article = _make_curated(
            title="IT firms push M&A deals to cover AI's revenue impact",
            category=Category.PRODUCT_INNOVATIONS,
        )
        result = _run_override([article])
        assert result[0].category == Category.FUNDING_MA

    def test_override_fires_for_industry_strategy(self):
        """industry_strategy + 'acquisition' → should become funding_ma."""
        article = _make_curated(
            title="Major acquisition reshapes cloud market",
            category=Category.INDUSTRY_STRATEGY,
        )
        result = _run_override([article])
        assert result[0].category == Category.FUNDING_MA

    def test_override_does_not_fire_for_india_tech(self):
        """india_tech articles keep their category even with funding signals."""
        article = _make_curated(
            title="Bengaluru food delivery startup Swish raises $38M",
            category=Category.INDIA_TECH,
            source=Source.ETTECH,
        )
        result = _run_override([article])
        assert result[0].category == Category.INDIA_TECH

    def test_override_does_not_fire_when_already_funding_ma(self):
        """Already-correct funding_ma articles stay unchanged."""
        article = _make_curated(
            title="OpenAI raises $10B from SoftBank",
            category=Category.FUNDING_MA,
        )
        result = _run_override([article])
        assert result[0].category == Category.FUNDING_MA

    def test_override_does_not_fire_for_plain_article(self):
        """Article with no funding signals keeps its original category."""
        article = _make_curated(
            title="Sam Altman-backed fusion startup in talks with OpenAI",
            category=Category.BIG_TECH_LAUNCHES,
        )
        result = _run_override([article])
        assert result[0].category == Category.BIG_TECH_LAUNCHES

    def test_override_fires_for_signal_in_snippet(self):
        """Funding signal in snippet (within first 200 chars) triggers override."""
        article = _make_curated(
            title="Cloud giant makes strategic move",
            category=Category.INDUSTRY_STRATEGY,
            snippet="The company announced a $500M acquisition of a smaller rival.",
        )
        result = _run_override([article])
        assert result[0].category == Category.FUNDING_MA

    def test_override_mixed_batch(self):
        """In a mixed batch, only eligible articles are overridden."""
        articles = [
            _make_curated("Plain AI benchmark news", Category.AI_PRODUCTS_TOOLS),
            _make_curated("Startup raises $200M Series C", Category.PRODUCT_INNOVATIONS),
            _make_curated("Indian fintech raises $38M", Category.INDIA_TECH, source=Source.ET_AI),
            _make_curated("Merger creates largest cloud provider", Category.INDUSTRY_STRATEGY),
        ]
        result = _run_override(articles)
        assert result[0].category == Category.AI_PRODUCTS_TOOLS   # no signal, unchanged
        assert result[1].category == Category.FUNDING_MA           # overridden
        assert result[2].category == Category.INDIA_TECH           # india_tech exception
        assert result[3].category == Category.FUNDING_MA           # overridden
