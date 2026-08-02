"""
Agent 4b: Script Validator
Post-script dedup: detects articles covered in multiple deep segments,
regenerates offending segments with excluded article lists. Max 2 iterations.
Writes validation_report.json to workspace/{date}/logs/.

Also runs a deterministic speech-marker sanitizer (sanitize_for_speech) on the
final script before returning — strips literal markdown/punctuation artifacts
that get read aloud by TTS (**, *, --, —, #, backticks, bullets) while
preserving real SSML tags (<break>, <emphasis>, <prosody>, <say-as>).
"""
import re
import structlog

from agents.script_writer import ScriptWriterAgent, _SEGMENT_ORDER, _CATEGORY_TO_SEGMENT  # noqa: F401
from models.article import ArticleSummary
from models.podcast import PodcastScript, Segment

log = structlog.get_logger(__name__)

# ── Deterministic speech-marker sanitizer ─────────────────────────────────────

# Patterns that should NEVER be read aloud. Applied in order.
# We do NOT touch SSML tags — only literal markdown/punctuation artifacts.
_SPEECH_MARKER_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Double-star bold: **text** → text (also catches lone **)
    (re.compile(r'\*\*'), ""),
    # Single-star italic or stray bullet star: * at word boundary or alone
    (re.compile(r'(?<!\w)\*(?!\w)'), ""),
    # Remaining lone asterisks between words (e.g. "foo * bar")
    (re.compile(r'\s\*\s'), " "),
    # Double-dash (markdown em-dash substitute): -- → pause via comma+space
    (re.compile(r'--'), ", "),
    # Unicode em-dash and en-dash when used as aside markers: — or – surrounded by spaces → comma
    (re.compile(r' [—–] '), ", "),
    # Backticks (inline code): `text` → text
    (re.compile(r'`([^`]*)`'), r'\1'),
    # Remaining stray backticks
    (re.compile(r'`'), ""),
    # Markdown headers: # / ## / ### at line start
    (re.compile(r'(?m)^#{1,6}\s+'), ""),
    # Markdown bullets: lines starting with "- " or "* " or numbered "1. "
    (re.compile(r'(?m)^\s*[-*]\s+'), ""),
    (re.compile(r'(?m)^\s*\d+\.\s+'), ""),
    # Collapse multiple spaces left by removals
    (re.compile(r'  +'), " "),
]


def _sanitize_text(text: str) -> str:
    """Apply speech-marker cleanup to a single string. Preserves SSML tags."""
    for pattern, replacement in _SPEECH_MARKER_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


def sanitize_for_speech(script: PodcastScript) -> PodcastScript:
    """
    Return a new PodcastScript with all segment content_ssml and content_plain
    sanitized to remove literal markdown/punctuation artifacts.
    SSML tags (e.g. <break time="1s"/>, <emphasis>) are preserved intact.
    """
    cleaned_segments: list[Segment] = []
    for seg in script.segments:
        cleaned_segments.append(
            seg.model_copy(update={
                "content_ssml": _sanitize_text(seg.content_ssml),
                "content_plain": _sanitize_text(seg.content_plain),
            })
        )
    return script.model_copy(update={"segments": cleaned_segments})


# Segments with exclusive deep-dive ownership — articles must not appear in 2+
_DEEP_SEGMENTS = frozenset({"ai_updates", "funding", "india_tech", "product_strategy"})

# Lower index = higher priority = keeps the article when conflict detected
_SEGMENT_PRIORITY: dict[str, int] = {seg_id: i for i, (seg_id, _) in enumerate(_SEGMENT_ORDER)}


class ScriptValidatorAgent:
    def run(
        self,
        script: PodcastScript,
        summaries: list[ArticleSummary],
        date: str,
        max_iterations: int = 2,
    ) -> tuple[PodcastScript, dict]:
        """
        Validate cross-segment article duplication and fix by regeneration.
        Returns (fixed_script, validation_report).
        """
        iterations_run = 0
        offenders_history: list[dict] = []

        for iteration in range(max_iterations):
            offenders = self._detect_offenders(script)
            offenders_history.append({"iteration": iteration, "offenders": offenders})

            if not offenders:
                log.info("validation_converged", iteration=iteration)
                break

            log.info(
                "script_validation_offenders",
                iteration=iteration,
                offender_count=len(offenders),
                articles=[o["article_id"] for o in offenders],
            )

            script = self._fix_offenders(script, summaries, date, offenders)
            iterations_run += 1
            fixed_segs = sorted({o["fix_segment"] for o in offenders})
            log.info("validation_regenerate", iteration=iteration, segments_fixed=fixed_segs)

        final_offenders = self._detect_offenders(script)

        report = {
            "iterations_run": iterations_run,
            "converged": len(final_offenders) == 0,
            "final_offender_count": len(final_offenders),
            "final_offenders": final_offenders,
            "history": offenders_history,
        }

        if final_offenders:
            log.warning(
                "validation_did_not_converge",
                final_offender_count=len(final_offenders),
                articles=[o["article_id"] for o in final_offenders],
            )
        else:
            log.info("validation_converged", total_iterations=iterations_run)

        # Deterministic speech-marker cleanup — always runs on the final script.
        script = sanitize_for_speech(script)
        log.info("speech_sanitizer_applied", segment_count=len(script.segments))

        return script, report

    # -------------------------------------------------------------------------

    def _detect_offenders(self, script: PodcastScript) -> list[dict]:
        """Return list of {article_id, owner_segment, fix_segment} dicts."""
        seg_to_articles: dict[str, set[str]] = {
            seg.segment_type: set(seg.source_article_ids)
            for seg in script.segments
            if seg.segment_type in _DEEP_SEGMENTS
        }

        article_to_segs: dict[str, list[str]] = {}
        for seg_id, article_ids in seg_to_articles.items():
            for art_id in article_ids:
                article_to_segs.setdefault(art_id, []).append(seg_id)

        offenders: list[dict] = []
        for art_id, segs in article_to_segs.items():
            if len(segs) <= 1:
                continue
            segs_sorted = sorted(segs, key=lambda s: _SEGMENT_PRIORITY.get(s, 99))
            owner = segs_sorted[0]
            for dupe_seg in segs_sorted[1:]:
                offenders.append({
                    "article_id": art_id,
                    "owner_segment": owner,
                    "fix_segment": dupe_seg,
                })
        return offenders

    def _fix_offenders(
        self,
        script: PodcastScript,
        summaries: list[ArticleSummary],
        date: str,
        offenders: list[dict],
    ) -> PodcastScript:
        # Group excluded article IDs by the segment that needs regeneration
        seg_exclusions: dict[str, set[str]] = {}
        for o in offenders:
            seg_exclusions.setdefault(o["fix_segment"], set()).add(o["article_id"])

        writer = ScriptWriterAgent()
        seg_by_type = {seg.segment_type: seg for seg in script.segments}
        new_segments = []

        for seg_id, _ in _SEGMENT_ORDER:
            if seg_id not in seg_by_type:
                continue
            orig = seg_by_type[seg_id]
            if seg_id not in seg_exclusions:
                new_segments.append(orig)
                continue

            excluded = seg_exclusions[seg_id]
            # Only pass summaries that were originally in this segment minus exclusions
            seg_summaries = [
                s for s in summaries
                if s.article_id in set(orig.source_article_ids) and s.article_id not in excluded
            ]

            try:
                fixed_seg = writer.regenerate_segment(
                    seg_id=seg_id,
                    summaries=seg_summaries,
                    date=date,
                    all_summaries=summaries,
                )
                new_segments.append(fixed_seg)
                log.info(
                    "segment_regenerated",
                    segment_type=seg_id,
                    excluded_count=len(excluded),
                    new_duration_sec=fixed_seg.duration_estimate_sec,
                )
            except Exception as e:
                log.error("segment_regeneration_failed", segment_type=seg_id, error=str(e))
                new_segments.append(orig)

        total_min = sum(s.duration_estimate_sec for s in new_segments) // 60
        return PodcastScript(
            episode_number=script.episode_number,
            date=script.date,
            total_estimated_duration_min=total_min,
            segments=new_segments,
            top_takeaways=script.top_takeaways,
        )
