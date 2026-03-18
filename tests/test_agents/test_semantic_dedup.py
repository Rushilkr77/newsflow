"""
Unit tests for CuratorAgent._semantic_dedup().

No LLM calls, no network — SentenceTransformer is mocked to return fixed
embeddings that produce known cosine-similarity scores.

Similarity layout (after L2 normalisation, via dot product):
  - articles[0] & articles[1]: "OpenAI GPT-5 launch" pair  → sim ≈ 0.95 (dup)
  - articles[2] & articles[3]: "Apple Vision Pro 2" pair   → sim ≈ 0.92 (dup)
  - articles[4] & articles[5]: unrelated articles          → sim ≈ 0.10 (not dup)

Run: pytest tests/test_agents/test_semantic_dedup.py -v
"""
import sys
import types
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agents.curator import CuratorAgent
from models.article import RawArticle
from models.enums import Source


def _patch_sentence_transformers():
    """
    Return a context manager that stubs out sentence_transformers so the
    `try: import sentence_transformers` guard in _semantic_dedup passes,
    allowing the mock _embed_model to be used.
    """
    fake_st = types.ModuleType("sentence_transformers")
    fake_st.SentenceTransformer = MagicMock()
    return patch.dict(sys.modules, {"sentence_transformers": fake_st})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_article(title: str, source: Source, snippet: str = "Some snippet text.") -> RawArticle:
    return RawArticle(
        id=str(uuid.uuid4()),
        title=title,
        url=f"https://example.com/{uuid.uuid4().hex}",
        source=source,
        sender_email="test@example.com",
        snippet=snippet,
        timestamp=datetime(2026, 3, 17, 5, 0, 0),
        newsletter_date="2026-03-17",
    )


def _unit(v: np.ndarray) -> np.ndarray:
    """Return L2-normalised copy of vector."""
    norm = np.linalg.norm(v)
    return v / norm if norm > 0 else v


# ---------------------------------------------------------------------------
# Fixed embeddings
# We build 6 embedding vectors such that:
#   cos_sim(e0, e1) ≈ 0.95  → semantic duplicates (GPT-5 pair)
#   cos_sim(e2, e3) ≈ 0.92  → semantic duplicates (Vision Pro pair)
#   all cross-pair sims < 0.30  → unrelated
# ---------------------------------------------------------------------------

def _build_fixed_embeddings() -> np.ndarray:
    # Orthogonal basis vectors in 6-D space
    basis = np.eye(6, dtype=np.float32)

    # Pair 0/1: near-identical direction (GPT-5)
    e0 = _unit(basis[0] * 10.0 + basis[1] * 0.5)
    e1 = _unit(basis[0] * 10.0 + basis[1] * 0.8)   # slightly different → sim ~0.97

    # Pair 2/3: near-identical direction (Vision Pro)
    e2 = _unit(basis[2] * 10.0 + basis[3] * 0.5)
    e3 = _unit(basis[2] * 10.0 + basis[3] * 0.9)   # slightly different → sim ~0.96

    # Pair 4/5: independent directions → sim ~0.0
    e4 = _unit(basis[4].copy())
    e5 = _unit(basis[5].copy())

    return np.stack([e0, e1, e2, e3, e4, e5])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def articles() -> list[RawArticle]:
    """
    6 articles: 2 semantic-dup pairs + 2 unrelated.

    Priority order (lower index = higher): harper_carroll > et_ai > ettech >
    techcrunch > tldr_ai > tldr_tech > tldr_dev

    Pair 1 (GPT-5):
      - articles[0]: tldr_ai       (lower priority, rank 4)
      - articles[1]: techcrunch    (higher priority, rank 3) ← should be kept

    Pair 2 (Vision Pro):
      - articles[2]: tldr_tech     (lower priority, rank 5)
      - articles[3]: et_ai         (higher priority, rank 1) ← should be kept

    Unrelated:
      - articles[4]: tldr_dev  (kept as-is)
      - articles[5]: ettech    (kept as-is)
    """
    return [
        _make_article("OpenAI launches GPT-5 with 1M context window", Source.TLDR_AI,
                      snippet="Short snippet."),
        _make_article("OpenAI releases GPT-5 model with massive context", Source.TECHCRUNCH,
                      snippet="A longer and more detailed snippet about the GPT-5 release."),
        _make_article("Apple announces Vision Pro 2 headset", Source.TLDR_TECH,
                      snippet="Short snippet."),
        _make_article("Apple Vision Pro 2 revealed with new chip", Source.ET_AI,
                      snippet="Detailed ET AI snippet about the Vision Pro second generation."),
        _make_article("How Kubernetes handles pod scheduling under load", Source.TLDR_DEV,
                      snippet="Engineering deep dive."),
        _make_article("Indian fintech Razorpay hits $10B valuation", Source.ETTECH,
                      snippet="India startup news."),
    ]


@pytest.fixture()
def curator() -> CuratorAgent:
    return CuratorAgent()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSemanticDedup:
    def _run_with_mock(self, curator: CuratorAgent, articles: list[RawArticle]):
        """Run _semantic_dedup with SentenceTransformer mocked to fixed embeddings."""
        fixed_embs = _build_fixed_embeddings()

        mock_model = MagicMock()
        mock_model.encode.return_value = fixed_embs
        curator._embed_model = mock_model

        with _patch_sentence_transformers():
            result = curator._semantic_dedup(articles)

        return result

    def test_reduces_count_from_6_to_4(self, curator, articles):
        result = self._run_with_mock(curator, articles)
        assert len(result) == 4, (
            f"Expected 4 articles after dedup (2 pairs merged), got {len(result)}: "
            + str([a.title for a in result])
        )

    def test_gpt5_pair_keeps_higher_priority_source(self, curator, articles):
        """techcrunch (rank 3) beats tldr_ai (rank 4) for the GPT-5 pair."""
        result = self._run_with_mock(curator, articles)
        titles = [a.title for a in result]
        # TechCrunch article should be present
        assert any("GPT-5" in t for t in titles), "GPT-5 story should be kept"
        # The kept GPT-5 article must come from TechCrunch
        gpt5_kept = [a for a in result if "GPT-5" in a.title]
        assert len(gpt5_kept) == 1
        assert gpt5_kept[0].source == Source.TECHCRUNCH, (
            f"Expected TECHCRUNCH but got {gpt5_kept[0].source}"
        )

    def test_vision_pro_pair_keeps_higher_priority_source(self, curator, articles):
        """et_ai (rank 1) beats tldr_tech (rank 5) for the Vision Pro pair."""
        result = self._run_with_mock(curator, articles)
        vision_kept = [a for a in result if "Vision Pro" in a.title]
        assert len(vision_kept) == 1
        assert vision_kept[0].source == Source.ET_AI, (
            f"Expected ET_AI but got {vision_kept[0].source}"
        )

    def test_unrelated_articles_are_preserved(self, curator, articles):
        """The two unrelated articles must both survive."""
        result = self._run_with_mock(curator, articles)
        titles = [a.title for a in result]
        assert any("Kubernetes" in t for t in titles), "Kubernetes article should survive"
        assert any("Razorpay" in t for t in titles), "Razorpay article should survive"

    def test_graceful_fallback_when_sentence_transformers_missing(self, curator, articles):
        """If sentence_transformers is not importable, return input unchanged."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("sentence_transformers not installed")
            return real_import(name, *args, **kwargs)

        curator._embed_model = None  # ensure lazy-load path is hit
        with patch("builtins.__import__", side_effect=mock_import):
            result = curator._semantic_dedup(articles)

        assert result == articles, "Should return input unchanged when library is missing"

    def test_single_article_returns_unchanged(self, curator, articles):
        single = [articles[0]]
        result = curator._semantic_dedup(single)
        assert result == single

    def test_empty_list_returns_unchanged(self, curator):
        assert curator._semantic_dedup([]) == []
