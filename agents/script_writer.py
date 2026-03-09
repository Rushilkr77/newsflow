"""
Agent 4: Script Writer
Generates the podcast script one segment at a time to stay within LLM token limits.
Each segment call is ~500-2000 tokens of output, well within any model's limit.
Uses utils.llm_client so it works with both Anthropic and local Ollama.

Model: llama3.2:3b (via SCRIPT_LOCAL_MODEL env var) — Meta's English-optimized
training makes it better for natural podcast narrative than qwen2.5:7b despite
fewer parameters.
"""
import json
import os
import re
import uuid
from datetime import datetime

import structlog

from models.article import ArticleSummary
from models.enums import Category
from models.podcast import PodcastScript, Segment
from utils.llm_client import chat

log = structlog.get_logger(__name__)

# Model for script writing (English narrative — LLaMA beats qwen for this task)
_SCRIPT_LOCAL_MODEL = os.getenv("SCRIPT_LOCAL_MODEL")

# Segment order
_SEGMENT_ORDER = [
    ("cold_open", "Cold Open"),
    ("intro", "Introduction"),
    ("ai_updates", "AI Updates"),
    ("funding", "Funding & Business"),
    ("india_tech", "India Tech"),
    ("product_strategy", "Product & Strategy"),
    ("quick_hits", "Quick Hits"),
    ("closing", "Closing"),
]

# Updated category → segment mapping for new Category enum
_CATEGORY_TO_SEGMENT = {
    Category.BIG_TECH_LAUNCHES:   "ai_updates",
    Category.AI_PRODUCTS_TOOLS:   "ai_updates",
    Category.PRODUCT_INNOVATIONS: "ai_updates",    # new innovations slot into tech updates
    Category.INDIA_STARTUPS:      "india_tech",
    Category.FUNDING_MA:          "funding",
    Category.INDUSTRY_STRATEGY:   "product_strategy",
    Category.ENGINEERING_TECH:    "quick_hits",
    Category.POLICY_SAFETY:       "quick_hits",
}

_SYSTEM_PROMPT = """You are the script writer for "NewsFlow" — a daily AI tech podcast.
Write for a single host narrating to a listener who's a software engineer building product awareness.

Voice guidelines:
- Conversational, like a sharp colleague briefing you over coffee
- Use verbal signposts: "First up...", "Now here's where it gets interesting...", "Moving on to..."
- Short sentences. Active voice. No jargon without a quick explanation.
- For SSML: wrap pauses as <break time="500ms"/>
- End each P0 story with: "If someone asks you about this in an interview, here's your edge: [INTERVIEW EDGE insight]"
- Quick hits: rapid-fire, "In quick hits today: [story 1]. [story 2]. [story 3]."

Return ONLY valid JSON — no markdown fences, no explanation."""


class ScriptWriterAgent:
    def run(self, summaries: list[ArticleSummary], date: str) -> PodcastScript:
        log.info("script_writer_start", summary_count=len(summaries), date=date)

        grouped = self._group_by_segment(summaries)
        formatted_date = self._format_date(date)

        segments: list[Segment] = []
        generated_plain_texts: list[str] = []

        for seg_id, seg_title in _SEGMENT_ORDER:
            seg_summaries = grouped.get(seg_id, [])

            try:
                seg = self._generate_segment(
                    seg_id=seg_id,
                    seg_title=seg_title,
                    summaries=seg_summaries,
                    date=date,
                    formatted_date=formatted_date,
                    all_summaries=summaries,
                    prior_plain_texts=generated_plain_texts,
                )
                segments.append(seg)
                generated_plain_texts.append(seg.content_plain)
                log.info("segment_done", segment_type=seg_id, duration_sec=seg.duration_estimate_sec)
            except Exception as e:
                log.error("segment_failed", segment_type=seg_id, error=str(e))
                segments.append(self._fallback_segment(seg_id, seg_title))

        total_min = sum(s.duration_estimate_sec for s in segments) // 60
        top_takeaways = self._extract_top_takeaways(summaries)

        script = PodcastScript(
            episode_number=1,
            date=date,
            total_estimated_duration_min=total_min,
            segments=segments,
            top_takeaways=top_takeaways,
        )

        log.info(
            "script_writer_complete",
            segments=len(script.segments),
            duration_min=script.total_estimated_duration_min,
        )
        return script

    # -------------------------------------------------------------------------
    # Segment generation
    # -------------------------------------------------------------------------

    def _generate_segment(
        self,
        seg_id: str,
        seg_title: str,
        summaries: list[ArticleSummary],
        date: str,
        formatted_date: str,
        all_summaries: list[ArticleSummary],
        prior_plain_texts: list[str],
    ) -> Segment:
        user_prompt = self._build_segment_prompt(
            seg_id, seg_title, summaries, formatted_date, all_summaries, prior_plain_texts
        )

        raw = chat(
            model_hint="claude-sonnet-4-5",
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=2048,
            local_model_override=_SCRIPT_LOCAL_MODEL,
        )

        raw = self._strip_fences(raw)
        data = json.loads(raw)

        return Segment(
            id=data.get("id", str(uuid.uuid4())),
            title=seg_title,
            segment_type=seg_id,
            content_ssml=data.get("content_ssml", data.get("content_plain", "")),
            content_plain=data.get("content_plain", ""),
            duration_estimate_sec=data.get("duration_estimate_sec", 120),
            source_article_ids=data.get("source_article_ids", []),
        )

    def _build_segment_prompt(
        self,
        seg_id: str,
        seg_title: str,
        summaries: list[ArticleSummary],
        formatted_date: str,
        all_summaries: list[ArticleSummary],
        prior_plain_texts: list[str],
    ) -> str:
        summaries_json = json.dumps(
            [
                {
                    "article_id": s.article_id,
                    "title": s.title,
                    "priority": s.priority.value,
                    "summary": s.summary_text,
                    "interview_edge": s.discussion_points[0] if s.discussion_points else "",
                }
                for s in summaries
            ],
            indent=2,
        )

        instructions = self._segment_instructions(seg_id, formatted_date, all_summaries, prior_plain_texts)

        return f"""Write the "{seg_title}" segment for today's NewsFlow podcast ({formatted_date}).

{instructions}

{"Articles for this segment:" if summaries else "No articles for this segment — write a brief transition."}
{summaries_json if summaries else "[]"}

Return ONLY this JSON (no markdown):
{{
  "id": "{uuid.uuid4()}",
  "segment_type": "{seg_id}",
  "content_ssml": "<script with <break time=\\"500ms\\"/> pauses>",
  "content_plain": "<same script without any SSML tags>",
  "duration_estimate_sec": <integer>,
  "source_article_ids": ["<article_id>", ...]
}}"""

    def _segment_instructions(
        self,
        seg_id: str,
        formatted_date: str,
        all_summaries: list[ArticleSummary],
        prior_plain_texts: list[str],
    ) -> str:
        top_titles = [s.title for s in all_summaries[:3]]

        instructions = {
            "cold_open": (
                "Duration: ~30 seconds. Hook the listener with the single most interesting story today. "
                "Start punchy — no intro, just dive in. End with: 'That and more, coming up.'"
            ),
            "intro": (
                f"Duration: ~2 minutes. Start: 'Good morning! It's {formatted_date}.' "
                f"Preview these top 3 stories: {top_titles}. "
                "Tell the listener what they'll learn today. Keep it energetic."
            ),
            "ai_updates": (
                "Duration: 15-25 minutes. Cover P0 stories first (deep dive), then P1. "
                "Covers big tech launches, AI products, and standout product innovations. "
                "Use signpost: 'Let's start with what's new in tech and AI...' "
                "End each P0 story with the INTERVIEW EDGE insight."
            ),
            "funding": (
                "Duration: 10-15 minutes. Cover investment news, M&A, valuations. "
                "Use signpost: 'Moving on to funding and business news...'"
            ),
            "india_tech": (
                "Duration: 5-10 minutes. India-focused startup and tech stories. "
                "Use signpost: 'Now, a look at what's happening in India tech...' "
                "Skip gracefully if no articles: 'Nothing major in India tech today.'"
            ),
            "product_strategy": (
                "Duration: 10-15 minutes. Industry strategy, SaaS disruption, Series B+ moves. "
                "Use signpost: 'Time for product and strategy...' "
                "Make connections to what engineers at Series B+ startups should know."
            ),
            "quick_hits": (
                "Duration: 5-10 minutes. Rapid-fire P2 stories (policy, safety, engineering). "
                "Start: 'In quick hits today:' then cover each in 1-2 sentences. "
                "Keep energy high, move fast."
            ),
            "closing": (
                "Duration: 3-5 minutes. Wrap up with '3 things to remember from today'. "
                "Reference the strongest stories and their interview edges. "
                "End with: 'That's your NewsFlow for today. Stay sharp. See you tomorrow.'"
            ),
        }
        return instructions.get(seg_id, f"Write the {seg_id} segment.")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _group_by_segment(self, summaries: list[ArticleSummary]) -> dict[str, list[ArticleSummary]]:
        groups: dict[str, list[ArticleSummary]] = {seg_id: [] for seg_id, _ in _SEGMENT_ORDER}
        for s in summaries:
            seg_id = _CATEGORY_TO_SEGMENT.get(s.category, "quick_hits")
            groups[seg_id].append(s)
        return groups

    def _format_date(self, date: str) -> str:
        dt = datetime.strptime(date, "%Y-%m-%d")
        raw = dt.strftime("%A, %B %d, %Y")
        return re.sub(r"\b0(\d)\b", r"\1", raw)

    def _strip_fences(self, raw: str) -> str:
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            raw = raw.rsplit("```", 1)[0]
        return raw.strip()

    def _extract_top_takeaways(self, summaries: list[ArticleSummary]) -> list[str]:
        takeaways = []
        for s in summaries:
            if s.key_takeaways:
                takeaways.extend(s.key_takeaways)
            if len(takeaways) >= 3:
                break
        return takeaways[:3]

    def _fallback_segment(self, seg_id: str, seg_title: str) -> Segment:
        text = f"Moving on. {seg_title} coverage will be available in the next episode."
        return Segment(
            id=str(uuid.uuid4()),
            title=seg_title,
            segment_type=seg_id,
            content_ssml=text,
            content_plain=text,
            duration_estimate_sec=10,
            source_article_ids=[],
        )
