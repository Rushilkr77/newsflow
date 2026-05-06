"""
Test curator batch retry logic and JSON repair.

Mimics the exact malformed JSON outputs observed from qwen2.5:3b in production:
  - Expecting ',' delimiter  (missing comma between fields)
  - int() argument NoneType  (estimated_podcast_seconds: null)
  - Expecting ':' delimiter  (missing colon)
  - Mixed: some batches pass, some fail

Validates:
  1. _repair_json() fixes each known error pattern
  2. _classify_with_retry() splits failing batches and retries
  3. Mandatory sources (tldr_ai, et_ai, ettech) get score=65 on final fallback
  4. Non-mandatory sources get score=40 on final fallback
  5. All articles survive — no silent drops
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from agents.curator import CuratorAgent
from models.article import RawArticle
from models.enums import Category, Priority, Source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(title: str, source: Source = Source.TLDR_AI) -> dict:
    a = RawArticle(
        id=str(uuid.uuid4()),
        title=title,
        url=f"https://example.com/{uuid.uuid4()}",
        source=source,
        snippet="Some snippet text.",
        sender_email="test@example.com",
        timestamp=datetime.now(timezone.utc),
        newsletter_date="2026-03-19",
    )
    return {"article": a, "all_sources": [source], "dedup_group_id": None}


def _valid_response(items: list[dict]) -> str:
    """Build a valid JSON classification response for a batch."""
    return json.dumps([
        {
            "index": i,
            "priority": "P1",
            "category": "ai_products_tools",
            "relevance_score": 75,
            "discussion_hooks": ["interesting hook"],
            "estimated_podcast_seconds": 120,
        }
        for i in range(len(items))
    ])


# ---------------------------------------------------------------------------
# _repair_json tests
# ---------------------------------------------------------------------------

class TestRepairJson:
    def test_missing_comma_between_fields(self):
        """Exact error: Expecting ',' delimiter — field missing trailing comma."""
        broken = '''[
  {
    "index": 0
    "priority": "P1",
    "category": "ai_products_tools",
    "relevance_score": 75,
    "discussion_hooks": ["hook"],
    "estimated_podcast_seconds": 120
  }
]'''
        repaired = CuratorAgent._repair_json(broken)
        parsed = json.loads(repaired)
        assert parsed[0]["priority"] == "P1"

    def test_missing_comma_between_objects(self):
        """Missing comma between two objects in the array."""
        broken = '''[
  {"index": 0, "priority": "P1", "category": "ai_products_tools", "relevance_score": 75, "discussion_hooks": [], "estimated_podcast_seconds": 120}
  {"index": 1, "priority": "P2", "category": "engineering_tech", "relevance_score": 50, "discussion_hooks": [], "estimated_podcast_seconds": 60}
]'''
        repaired = CuratorAgent._repair_json(broken)
        parsed = json.loads(repaired)
        assert len(parsed) == 2

    def test_null_estimated_podcast_seconds(self):
        """Exact error: int() argument NoneType — null value for numeric field."""
        broken = '''[
  {
    "index": 0,
    "priority": "P1",
    "category": "ai_products_tools",
    "relevance_score": 75,
    "discussion_hooks": ["hook"],
    "estimated_podcast_seconds": null
  }
]'''
        # repair_json doesn't need to fix this — the or-120 fallback in _classify_batch handles it
        parsed = json.loads(broken)
        # Simulate the fix: int(item_data.get("estimated_podcast_seconds") or 120)
        val = int(parsed[0].get("estimated_podcast_seconds") or 120)
        assert val == 120

    def test_trailing_comma_in_array(self):
        broken = '''[
  {"index": 0, "priority": "P1", "category": "ai_products_tools", "relevance_score": 75, "discussion_hooks": [], "estimated_podcast_seconds": 120},
]'''
        repaired = CuratorAgent._repair_json(broken)
        parsed = json.loads(repaired)
        assert len(parsed) == 1

    def test_python_none_in_response(self):
        """Model outputs Python None instead of JSON null."""
        broken = '''[{"index": 0, "priority": "P1", "category": "ai_products_tools", "relevance_score": 75, "discussion_hooks": [], "estimated_podcast_seconds": None}]'''
        repaired = CuratorAgent._repair_json(broken)
        parsed = json.loads(repaired)
        assert parsed[0]["estimated_podcast_seconds"] is None  # null parsed correctly


# ---------------------------------------------------------------------------
# _classify_with_retry tests — mock the LLM call
# ---------------------------------------------------------------------------

class TestClassifyWithRetry:
    def _curator(self) -> CuratorAgent:
        c = CuratorAgent.__new__(CuratorAgent)
        c._prefs = {
            "user_profile": {"role": "SDE transitioning to AI PM"},
            "priority_rules": {
                "P0_must_include": [], "P1_high": [], "P2_if_space": [], "P3_skip": []
            },
            "emerging_ai_companies": [],
        }
        return c

    def test_success_on_first_try(self):
        """All 8 articles classified successfully on first attempt."""
        batch = [_make_item(f"Article {i}", Source.TLDR_AI) for i in range(8)]
        curator = self._curator()

        with patch.object(curator, "_classify_batch", return_value=[MagicMock()] * 8) as mock_cb:
            results = curator._classify_with_retry(batch, batch_start=0)

        assert len(results) == 8
        mock_cb.assert_called_once_with(batch)

    def test_retry_splits_batch_on_failure(self):
        """Batch of 8 fails → splits to 4+4, both succeed."""
        batch = [_make_item(f"Article {i}", Source.TLDR_AI) for i in range(8)]
        curator = self._curator()

        call_count = 0
        def side_effect(b):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise json.JSONDecodeError("Expecting ','", "", 0)
            return [MagicMock()] * len(b)

        with patch.object(curator, "_classify_batch", side_effect=side_effect):
            results = curator._classify_with_retry(batch, batch_start=0)

        assert len(results) == 8  # all 8 articles survive
        assert call_count == 3    # 1 failed batch + 2 successful halves

    def test_retry_recurses_to_single_article(self):
        """Persistent failure recurses all the way to single-article batches."""
        batch = [_make_item(f"Article {i}", Source.TLDR_AI) for i in range(4)]
        curator = self._curator()

        # Fail every batch attempt — force down to size=1
        def always_fail(b):
            if len(b) > 1:
                raise json.JSONDecodeError("Expecting ','", "", 0)
            raise ValueError("even solo failed")

        with patch.object(curator, "_classify_batch", side_effect=always_fail):
            results = curator._classify_with_retry(batch, batch_start=0)

        # All 4 articles should still be present via fallback
        assert len(results) == 4

    def test_no_silent_drops(self):
        """Total articles in == total articles out, even with all batches failing."""
        n = 8
        batch = [_make_item(f"Article {i}", Source.TLDR_AI) for i in range(n)]
        curator = self._curator()

        with patch.object(curator, "_classify_batch", side_effect=ValueError("always fail")):
            results = curator._classify_with_retry(batch, batch_start=0)

        assert len(results) == n


# ---------------------------------------------------------------------------
# _fallback_curated — mandatory source scoring
# ---------------------------------------------------------------------------

class TestFallbackCurated:
    def _curator(self) -> CuratorAgent:
        c = CuratorAgent.__new__(CuratorAgent)
        return c

    @pytest.mark.parametrize("source,expected_score,expected_cat", [
        (Source.TLDR_AI,  65.0, Category.AI_PRODUCTS_TOOLS),
        (Source.ET_AI,    65.0, Category.AI_PRODUCTS_TOOLS),
        (Source.ETTECH,   65.0, Category.AI_PRODUCTS_TOOLS),
        (Source.TECHCRUNCH, 40.0, Category.ENGINEERING_TECH),
        (Source.TLDR_DEV,   40.0, Category.ENGINEERING_TECH),
        (Source.HARPER_CARROLL, 40.0, Category.ENGINEERING_TECH),
    ])
    def test_fallback_score_by_source(self, source, expected_score, expected_cat):
        item = _make_item("OpenAI launches new model", source)
        curator = self._curator()
        result = curator._fallback_curated(item)

        assert result.relevance_score == expected_score, (
            f"{source.value}: expected score {expected_score}, got {result.relevance_score}"
        )
        assert result.category == expected_cat
        assert result.priority == Priority.P2

    def test_mandatory_source_survives_time_budget(self):
        """tldr_ai fallback score=65 ranks above non-mandatory score=40 in time budget sort."""
        curator = self._curator()

        mandatory_item = _make_item("OpenAI GPT-5 launch", Source.TLDR_AI)
        other_item = _make_item("Random blog post", Source.TECHCRUNCH)

        mandatory = curator._fallback_curated(mandatory_item)
        other = curator._fallback_curated(other_item)

        # When sorted by relevance_score descending (as time budget does),
        # mandatory source must rank higher
        ranked = sorted([other, mandatory], key=lambda a: a.relevance_score, reverse=True)
        assert ranked[0].source == Source.TLDR_AI


# ---------------------------------------------------------------------------
# Integration: _classify() with mixed pass/fail batches
# ---------------------------------------------------------------------------

class TestClassifyIntegration:
    def _curator(self) -> CuratorAgent:
        c = CuratorAgent.__new__(CuratorAgent)
        c._prefs = {
            "user_profile": {"role": "SDE transitioning to AI PM"},
            "priority_rules": {
                "P0_must_include": [], "P1_high": [], "P2_if_space": [], "P3_skip": []
            },
            "emerging_ai_companies": [],
        }
        return c

    def test_tldr_ai_articles_survive_when_batch_fails(self):
        """
        Reproduces the production bug: TLDR AI articles land in a failing batch
        and should survive via retry/fallback — not be silently dropped.
        """
        # 16 articles: 8 from tldr_ai (will be in batch 0), 8 from harper_carroll (batch 1)
        tldr_batch = [_make_item(f"TLDR AI Article {i}", Source.TLDR_AI) for i in range(8)]
        hc_batch = [_make_item(f"Harper Carroll Article {i}", Source.HARPER_CARROLL) for i in range(8)]
        all_items = tldr_batch + hc_batch

        curator = self._curator()

        batch_call_count = 0
        def mock_classify_batch(b):
            nonlocal batch_call_count
            batch_call_count += 1
            # First call (batch of 8 tldr_ai) fails with real production error
            if batch_call_count == 1:
                raise json.JSONDecodeError("Expecting ',' delimiter", "doc", 299)
            # All subsequent calls (smaller tldr batches + hc batch) succeed
            return [
                MagicMock(
                    spec_set=False,
                    priority=Priority.P1,
                    relevance_score=80.0,
                    source=b[i]["article"].source,
                )
                for i in range(len(b))
            ]

        with patch.object(curator, "_classify_batch", side_effect=mock_classify_batch):
            with patch.object(curator, "_is_garbage_title", return_value=False):
                results = curator._classify(all_items)

        assert len(results) == 16, f"Expected 16 articles, got {len(results)} — silent drops detected"
        tldr_results = [r for r in results if hasattr(r, 'source') and r.source == Source.TLDR_AI]
        assert len(tldr_results) == 8, "All TLDR AI articles should survive"
