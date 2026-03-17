"""
Unit tests for ScriptWriterAgent JSON cleaning helpers.

Uses the exact patterns observed in production qwen2.5:7b output —
no LLM calls, no fixtures, no pipeline required.
Run: pytest tests/test_agents/test_script_writer_json.py -v
"""
import json
import pytest
from agents.script_writer import ScriptWriterAgent

@pytest.fixture
def sw():
    return ScriptWriterAgent()


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------

class TestStripFences:
    def test_strips_json_fence(self, sw):
        raw = '```json\n{"key": "value"}\n```'
        assert sw._strip_fences(raw) == '{"key": "value"}'

    def test_strips_plain_fence(self, sw):
        raw = '```\n{"key": "value"}\n```'
        assert sw._strip_fences(raw) == '{"key": "value"}'

    def test_no_fence_unchanged(self, sw):
        raw = '{"key": "value"}'
        assert sw._strip_fences(raw) == raw

    def test_plain_text_no_fence_unchanged(self, sw):
        raw = "Let's start with what's new in AI today."
        assert sw._strip_fences(raw) == raw


# ---------------------------------------------------------------------------
# _unwrap_json_plain — STRING value case (original)
# ---------------------------------------------------------------------------

class TestUnwrapJsonPlainString:
    def test_unwraps_podcast_narration_string(self, sw):
        inner = "Let's start with what's new in AI today. First up, the story..."
        raw = json.dumps({"podcast_narration": inner})
        result = sw._unwrap_json_plain(raw)
        assert result == inner

    def test_unwraps_content_key_string(self, sw):
        inner = "Moving on to funding news..."
        raw = json.dumps({"content": inner})
        result = sw._unwrap_json_plain(raw)
        assert result == inner

    def test_plain_text_unchanged(self, sw):
        raw = "This is just plain narration text, no JSON."
        assert sw._unwrap_json_plain(raw) == raw

    def test_short_string_value_skipped(self, sw):
        # String value <= 20 chars — should not unwrap (likely a metadata value)
        raw = json.dumps({"key": "too short"})
        assert sw._unwrap_json_plain(raw) == raw


# ---------------------------------------------------------------------------
# _unwrap_json_plain — LIST OF DICTS case (production bug pattern)
# This is the exact pattern qwen2.5:7b returned for ai_updates SSML.
# ---------------------------------------------------------------------------

class TestUnwrapJsonPlainListOfDicts:
    def _make_list_wrapper(self, summaries: list[str]) -> str:
        """Reproduce exact qwen2.5:7b output format for multi-batch segments."""
        return json.dumps({
            "podcast_narration": [
                {
                    "segment": f"Segment {i+1}",
                    "article_id": f"article-{i}",
                    "summary": text,
                }
                for i, text in enumerate(summaries)
            ]
        }, indent=2)

    def test_extracts_summaries_from_list_of_dicts(self, sw):
        summaries = [
            "First up, the AI landscape has dramatically shifted.",
            "Next, a major funding round for a legal AI startup.",
        ]
        raw = self._make_list_wrapper(summaries)
        result = sw._unwrap_json_plain(raw)
        # Should NOT return the raw JSON
        assert not result.strip().startswith("{"), "JSON wrapper not stripped"
        # Should contain the actual narration text
        assert "AI landscape" in result
        assert "legal AI startup" in result

    def test_real_production_pattern(self, sw):
        """Exact truncated snippet from 2026-03-14 ai_updates SSML."""
        raw = (
            '{\n    "podcast_narration": [\n'
            '        {\n'
            '            "segment": "AI Landscape Evolves: New Era of Autonomous AI Management",\n'
            '            "article_id": "002e4ed4-333a-4a4d-b18e-fb6001be33e3",\n'
            '            "summary": "First up, the AI landscape has dramatically shifted. '
            "We're now well into 2025 and entering an era where AI isn't just assisting "
            'but managing significant human tasks autonomously."\n'
            '        }\n'
            '    ]\n}'
        )
        result = sw._unwrap_json_plain(raw)
        assert not result.strip().startswith("{"), "JSON wrapper not stripped"
        assert "AI landscape has dramatically shifted" in result

    def test_list_with_multiple_batches(self, sw):
        """4-batch ai_updates: all summaries should appear in output."""
        summaries = [
            "Cursor is raising at a fifty billion dollar valuation.",
            "Meta AI is now responding to buyers in Facebook Marketplace.",
            "OpenAI releases new reasoning model with chain-of-thought.",
            "Google DeepMind publishes Gemini safety report.",
        ]
        raw = self._make_list_wrapper(summaries)
        result = sw._unwrap_json_plain(raw)
        assert not result.strip().startswith("{")
        for text in summaries:
            assert text[:20] in result, f"Missing: {text[:40]}"


# ---------------------------------------------------------------------------
# _insert_missing_comma
# ---------------------------------------------------------------------------

class TestInsertMissingComma:
    def test_fixes_single_missing_comma(self, sw):
        # qwen2.5:7b omits comma after content_plain
        raw = '{"content_plain": "Hello world"\n"duration_estimate_sec": 120}'
        fixed = sw._insert_missing_comma(raw)
        parsed = json.loads(fixed)
        assert parsed["content_plain"] == "Hello world"
        assert parsed["duration_estimate_sec"] == 120

    def test_fixes_multiple_missing_commas(self, sw):
        raw = '{"a": "one"\n"b": "two"\n"c": "three"}'
        fixed = sw._insert_missing_comma(raw)
        parsed = json.loads(fixed)
        assert parsed == {"a": "one", "b": "two", "c": "three"}

    def test_valid_json_unchanged(self, sw):
        raw = '{"a": "one", "b": 2}'
        assert sw._insert_missing_comma(raw) == raw

    def test_different_error_passthrough(self, sw):
        # Unterminated string — not a missing comma, should not corrupt further
        raw = '{"a": "unterminated'
        result = sw._insert_missing_comma(raw)
        # Should not raise, should return something
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _clean_json — integration (exercises the full pipeline)
# ---------------------------------------------------------------------------

class TestCleanJson:
    def test_fixes_missing_comma_then_parses(self, sw):
        raw = (
            '{"id": "abc123", '
            '"content_plain": "Good morning and welcome to NewsFlow today."\n'
            '"duration_estimate_sec": 120, '
            '"source_article_ids": []}'
        )
        cleaned = sw._clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["content_plain"] == "Good morning and welcome to NewsFlow today."

    def test_fixes_unescaped_newline_in_string(self, sw):
        raw = '{"content_plain": "Line one.\nLine two.", "d": 1}'
        cleaned = sw._clean_json(raw)
        parsed = json.loads(cleaned)
        assert "Line one." in parsed["content_plain"]

    def test_strips_trailing_text_after_brace(self, sw):
        raw = '{"content_plain": "Hello."}\nHere is some extra explanation.'
        cleaned = sw._clean_json(raw)
        parsed = json.loads(cleaned)
        assert parsed["content_plain"] == "Hello."

    def test_ssml_unescaped_quotes_plus_missing_comma(self, sw):
        """
        Production pattern for product_strategy retries:
        content_ssml has SSML <break time="500ms"/> with unescaped quotes,
        AND the comma between content_ssml and content_plain is missing.

        _insert_missing_comma called BEFORE the state machine fails here:
        json.loads sees the SSML quote as ending the string, reports the error
        at the wrong position (inside the SSML tag, not between fields),
        inserts a comma there, corrupts the string.

        Fix: call _insert_missing_comma AFTER the state machine so SSML quotes
        are escaped first, then the missing comma is at the correct position.
        """
        raw = (
            '{"id": "abc", "segment_type": "product_strategy", '
            '"content_ssml": "Moving on to product strategy. <break time="500ms"/> '
            'First story here. If someone asks in an interview, here\'s your edge: '
            'the key insight is about platform moats."'
            '\n"content_plain": "Moving on to product strategy. First story here.", '
            '"duration_estimate_sec": 200, "source_article_ids": ["a1"]}'
        )
        cleaned = sw._clean_json(raw)
        parsed = json.loads(cleaned)
        assert "Moving on to product strategy" in parsed["content_plain"]
        assert parsed["duration_estimate_sec"] == 200

    def test_ssml_multiple_break_tags_plus_missing_comma(self, sw):
        """Multiple SSML break tags with unescaped quotes — variant seen in longer segments."""
        raw = (
            '{"id": "xyz", "segment_type": "product_strategy", '
            '"content_ssml": "Story one. <break time="500ms"/> Story two. <break time="1000ms"/> Done."'
            '\n"content_plain": "Story one. Story two. Done.", '
            '"duration_estimate_sec": 150, "source_article_ids": []}'
        )
        cleaned = sw._clean_json(raw)
        parsed = json.loads(cleaned)
        assert "Story one" in parsed["content_plain"]
        assert parsed["duration_estimate_sec"] == 150
