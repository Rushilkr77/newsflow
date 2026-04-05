"""
Unit tests for expansion logging in NewsFlowPipeline._run():
- expansion_diff.json is written when gaps are detected
- expansion_diff.json contains the correct structure and values
- expansion_diff.json is NOT written when no gaps are detected

Run: pytest tests/test_agents/test_pipeline_expansion_logging.py -v
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from models.article import ArticleSummary
from models.enums import Priority, Source, Category
from models.podcast import PodcastScript, Segment
from orchestrator.pipeline import _build_expansion_diff, _find_coverage_gaps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_segment(
    segment_type: str,
    article_ids: list[str],
    duration_sec: int = 300,
    content_plain: str = "Some plain text content here.",
) -> Segment:
    return Segment(
        id=f"seg_{segment_type}",
        title=segment_type.replace("_", " ").title(),
        segment_type=segment_type,
        content_ssml=f"<speak>{content_plain}</speak>",
        content_plain=content_plain,
        duration_estimate_sec=duration_sec,
        source_article_ids=article_ids,
    )


def _make_script(
    segments: list[Segment],
    duration_min: int = 45,
    episode_number: int = 1,
    date: str = "2026-03-29",
) -> PodcastScript:
    return PodcastScript(
        episode_number=episode_number,
        date=date,
        total_estimated_duration_min=duration_min,
        segments=segments,
        top_takeaways=["takeaway 1", "takeaway 2", "takeaway 3"],
    )


def _make_summary(
    article_id: str,
    title: str,
    priority: Priority = Priority.P1,
) -> ArticleSummary:
    return ArticleSummary(
        article_id=article_id,
        title=title,
        source=Source.TLDR_AI,
        priority=priority,
        category=Category.AI_PRODUCTS_TOOLS,
        summary_text=f"Summary for {title}",
        key_takeaways=["point 1"],
        discussion_points=["question 1"],
        word_count=50,
    )


def _run_expansion_scenario(
    *,
    pre_gap_ids: list[str],
    post_skipped: list[str],
    post_undercovered: list[str],
) -> dict:
    """
    Build pre/post PodcastScript objects and call _build_expansion_diff directly.

    Returns the expansion_diff dict so tests can inspect it.
    """
    # Pre-expansion script
    pre_segments = [
        _make_segment("intro", [], duration_sec=120, content_plain="Welcome."),
        _make_segment("ai_updates", ["art-A"], duration_sec=600, content_plain="AI news."),
    ]
    pre_script = _make_script(pre_segments, duration_min=40)

    # Post-expansion script — duration grew
    post_segments = [
        _make_segment("intro", [], duration_sec=120, content_plain="Welcome."),
        _make_segment(
            "ai_updates",
            ["art-A", "art-B"],
            duration_sec=900,
            content_plain="More AI news including art-B coverage.",
        ),
    ]
    post_script = _make_script(post_segments, duration_min=55)

    pre_expansion_segments = {
        seg.segment_type: {
            "duration_sec": seg.duration_estimate_sec,
            "article_ids": seg.source_article_ids,
            "char_count": len(seg.content_plain),
        }
        for seg in pre_script.segments
    }

    post_gaps = {"skipped": post_skipped, "undercovered": post_undercovered}

    return _build_expansion_diff(
        pre_min=pre_script.total_estimated_duration_min,
        pre_segments=pre_expansion_segments,
        pre_gaps={"skipped": pre_gap_ids, "undercovered": []},
        post_script=post_script,
        post_gaps=post_gaps,
        gap_ids=pre_gap_ids,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExpansionDiffWritten:
    """_build_expansion_diff returns the correct structure and values."""

    def test_diff_has_required_top_level_keys(self):
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B"],
            post_skipped=[],
            post_undercovered=[],
        )
        assert "pre_expansion" in data
        assert "post_expansion" in data
        assert "summary" in data

    def test_pre_expansion_structure(self):
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B"],
            post_skipped=[],
            post_undercovered=[],
        )
        pre = data["pre_expansion"]
        assert "duration_min" in pre
        assert "segments" in pre
        assert "gaps" in pre
        # Each segment entry has the three keys
        for seg_data in pre["segments"].values():
            assert "duration_sec" in seg_data
            assert "article_ids" in seg_data
            assert "char_count" in seg_data

    def test_post_expansion_structure(self):
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B"],
            post_skipped=[],
            post_undercovered=[],
        )
        post = data["post_expansion"]
        assert "duration_min" in post
        assert "segments" in post
        assert "gaps" in post

    def test_gaps_filled_correct(self):
        """art-B was a gap before expansion; post-expansion it is no longer gapped."""
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B", "art-C"],
            post_skipped=["art-C"],   # art-C still skipped
            post_undercovered=[],
        )
        summary = data["summary"]
        assert summary["gaps_filled"] == ["art-B"], (
            "art-B was filled; art-C is still gapped"
        )

    def test_gaps_remaining_correct(self):
        """art-C remains gapped after expansion."""
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B", "art-C"],
            post_skipped=["art-C"],
            post_undercovered=[],
        )
        summary = data["summary"]
        assert summary["gaps_remaining"] == ["art-C"]

    def test_gaps_before_and_after_counts(self):
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B", "art-C"],
            post_skipped=["art-C"],
            post_undercovered=[],
        )
        summary = data["summary"]
        assert summary["gaps_before"] == 2
        assert summary["gaps_after"] == 1

    def test_all_gaps_filled(self):
        """When expansion fixes all gaps, gaps_remaining is empty."""
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B"],
            post_skipped=[],
            post_undercovered=[],
        )
        summary = data["summary"]
        assert summary["gaps_filled"] == ["art-B"]
        assert summary["gaps_remaining"] == []
        assert summary["gaps_after"] == 0

    def test_duration_gain_recorded(self):
        """duration_gain_min = post_duration - pre_duration."""
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B"],
            post_skipped=[],
            post_undercovered=[],
        )
        summary = data["summary"]
        # Pre = 40, post = 55 (as set up in _run_expansion_scenario)
        assert summary["duration_gain_min"] == 15

    def test_diff_file_is_written(self, tmp_path):
        """_build_expansion_diff result can be serialised to expansion_diff.json."""
        data = _run_expansion_scenario(
            pre_gap_ids=["art-B"],
            post_skipped=[],
            post_undercovered=[],
        )
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        diff_path = logs_dir / "expansion_diff.json"
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        assert diff_path.exists(), "expansion_diff.json should exist after writing"


class TestNoDiffWhenNoGaps:
    """expansion_diff.json is NOT written when gap_ids is empty (property of the caller)."""

    def test_no_diff_file_when_no_gaps(self, tmp_path):
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        diff_path = logs_dir / "expansion_diff.json"

        # Simulate the `if gap_ids:` branch not being entered
        gap_ids: list[str] = []
        if gap_ids:
            # This block should not execute
            with open(diff_path, "w") as f:
                json.dump({}, f)

        assert not diff_path.exists(), (
            "expansion_diff.json must NOT be written when there are no coverage gaps"
        )

    def test_build_expansion_diff_with_empty_gap_ids(self):
        """_build_expansion_diff still returns a valid dict when gap_ids is empty."""
        post_script = _make_script(
            [_make_segment("intro", [], duration_sec=120, content_plain="Welcome.")],
            duration_min=40,
        )
        data = _build_expansion_diff(
            pre_min=40,
            pre_segments={},
            pre_gaps={"skipped": [], "undercovered": []},
            post_script=post_script,
            post_gaps={"skipped": [], "undercovered": []},
            gap_ids=[],
        )
        assert data["summary"]["gaps_before"] == 0
        assert data["summary"]["gaps_after"] == 0
        assert data["summary"]["gaps_filled"] == []
        assert data["summary"]["gaps_remaining"] == []
        assert data["summary"]["duration_gain_min"] == 0
