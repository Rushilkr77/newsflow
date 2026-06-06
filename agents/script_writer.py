"""
Agent 4: Script Writer
Generates the podcast script one segment at a time to stay within LLM token limits.
Each segment call is ~500-2000 tokens of output, well within any model's limit.
Uses utils.llm_client so it works with both Anthropic and local Ollama.

Model: qwen2.5:7b (via SCRIPT_LOCAL_MODEL env var, default qwen2.5:7b) — switched
from llama3.2:3b due to hallucination issues. qwen2.5:7b has stronger instruction
adherence and lower hallucination rate for grounded narration tasks.
"""
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime

import structlog

from models.article import ArticleSummary
from models.enums import Category
from models.podcast import PodcastScript, Segment
from utils.llm_client import chat

log = structlog.get_logger(__name__)

# Model for script writing — qwen2.5:7b has stronger instruction adherence and
# lower hallucination rate than llama3.2:3b for grounded narration.
_SCRIPT_LOCAL_MODEL = os.getenv("SCRIPT_LOCAL_MODEL", "qwen2.5:7b")

# OpenRouter model chain for script writing — tried in order, falls back to local on error.
# Override via comma-separated env var OPENROUTER_SCRIPT_MODELS.
_OPENROUTER_SCRIPT_MODELS: list[str] = [
    m.strip()
    for m in os.getenv(
        "OPENROUTER_SCRIPT_MODELS",
        "openai/gpt-oss-120b:free,nousresearch/hermes-3-llama-3.1-405b:free,meta-llama/llama-3.3-70b-instruct:free,google/gemma-4-31b-it:free",
    ).split(",")
    if m.strip()
]

# Max retries on JSON parse failure or empty content (llama3.2:3b is stochastic)
_MAX_RETRIES = 4

# Per-segment token budgets. Sized to allow 45 min episodes with current article
# volumes; will fill toward 90 min naturally as Phase 2 ET sources add more articles.
_SEGMENT_MAX_TOKENS: dict[str, int] = {
    "opener": 512,
    "ai_updates": 5120,      # 15-18 min target; P0 deep + P1 tight
    "funding": 2048,
    "india_tech": 1536,
    "product_strategy": 2048,
    "quick_hits": 1024,
    "closing": 1024,
}

# Max total summary chars passed to a single LLM call.
# Bumped from 2000 → 3500: allows 3-4 P0 summaries per call (vs 1-2 before),
# producing denser and more coherent narration per batch.
# A single article is never split across batches.
_MAX_SUMMARY_CHARS_PER_CALL = 3500

# Spoken pace for duration estimation.
# gTTS baseline: 22452 chars → 1714 sec = ~13 chars/sec.
# Chatterbox/ElevenLabs speak ~43% faster; recalibrated from 2026-05-12 run:
# estimated 67 min (at 13 c/s) vs actual audio 47 min → true rate ≈ 18.5 chars/sec.
_CHARS_PER_SEC = 19  # conservative rounding keeps estimates slightly under actual

# Instruction injected into both call paths to prevent verbatim hint copying.
_INTERVIEW_EDGE_INSTRUCTION = """
Note on interview_edge_hint: This is a SHORT TOPIC PROMPT — expand it into 2-3 sentences showing BOTH technical understanding AND product thinking. The listener is an SDE transitioning to PM.

Bad (verbatim copy): "here's your edge: AI in enterprises"
Bad (buzzwords only): "here's your edge: enterprise AI is about augmenting decisions at scale"

Good (technical + product): "here's your edge: The architectural decision here is [what the company chose as core primitive, e.g. full-codebase context vs per-file]. This creates a moat because [technical reason]. As a PM interview answer, frame it as: [the tradeoff between option A giving X vs option B giving Y] — companies winning here solve [specific design/trust/pricing challenge], not just 'AI makes things faster'."

For every article: explain WHAT the technical decision is, WHY it creates product differentiation or risk, and WHAT a PM should say. Do NOT copy the hint verbatim."""

# Segment order
_SEGMENT_ORDER = [
    ("opener", "Opener"),
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
    Category.INDIA_TECH:          "india_tech",
    Category.FUNDING_MA:          "funding",
    Category.INDUSTRY_STRATEGY:   "product_strategy",
    Category.ENGINEERING_TECH:    "quick_hits",
    Category.POLICY_SAFETY:       "quick_hits",
}

_SYSTEM_PROMPT = """You are the script writer for "NewsFlow" — a daily AI tech podcast.
Write for a single host narrating to a listener who's a software engineer building product awareness.

Voice guidelines:
- Sound like a sharp, opinionated tech journalist — not a newsreader. Have a point of view.
- Transition hooks (DO NOT repeat any hook more than once per episode — these are EXAMPLES for flavor, not a list to cycle through): "Here's the part that actually matters...", "Before we move on — one thing worth sitting with...", "And look, this connects to something bigger...", "That said, there's a wrinkle...", "The headline buries the real story here...", "Worth pausing on this one...", "Pull back for a second...", "If you're building in this space, this is the one...", "You've probably seen this framed as X — here's why that's wrong...", "Real talk for a second...", "Nobody I've read has asked the obvious follow-up question...", "This one's subtle but it compounds fast...", "Set that aside for a moment...", "The counterintuitive take...", "Here's what changes for builders...", "One data point and then I'll move on...", "Not to editorialize, but...", "Okay, slight detour — worth it...", "I keep coming back to this...", "Three words: [memorable phrase]."
- CRITICAL: Do NOT use the phrases "Moving on", "What's next", "Here's the thing", or "Let me put this in perspective" — they are banned. Invent fresh transitions each time.
- After each P0 story, give a reaction or take: original framing, not a templated formula.
- Drop one rhetorical question or aside per major segment to break the pace.
- Short punchy sentences on key points. Longer conversational sentences for context. Vary the rhythm.
- Active voice. No jargon without a quick plain-English follow-up.
- For SSML (content_ssml field only): SSML is MANDATORY — every sentence must use at least one tag. Bare untagged sentences are not acceptable. Model your output on this example pattern:

  EXAMPLE (use this density and variety):
  <prosody rate="108%">Anthropic just dropped a</prosody> <emphasis level="strong">200-million-dollar</emphasis> partnership with the Gates Foundation.
  <break time="600ms"/>
  <prosody rate="95%">Here's the part that actually matters</prosody> — <prosody pitch="+1st">this isn't just philanthropic optics.</prosody>
  <break time="400ms"/>
  They're embedding <emphasis level="moderate">Claude</emphasis> directly into health and education systems across low-income countries.
  <break time="700ms"/>
  <prosody rate="92%">If someone asks you about this in an interview, your edge is this:</prosody>
  <break time="400ms"/>
  <prosody pitch="+0.5st" rate="97%">Anthropic is building distribution channels that <emphasis level="strong">bypass</emphasis> the traditional enterprise sales cycle entirely.</prosody>

  Rules for each tag type:
  * Pauses: <break time="400ms"/> sentence boundary, <break time="700ms"/> topic shift, <break time="1200ms"/> segment transition. Place AFTER punctuation.
  * Emphasis: <emphasis level="strong"> on key numbers/names/punchlines; <emphasis level="moderate"> on product names, company names, verbs that carry meaning
  * Rate: <prosody rate="108%"> on quick lead-ins and throwaway asides; <prosody rate="92%"> on insights the listener must absorb; <prosody rate="95%"> on setup phrases before a reveal
  * Pitch: <prosody pitch="+1st"> on rhetorical questions and surprising statements; <prosody pitch="+0.5st"> on interview-edge conclusions; <prosody pitch="-0.5st"> on parenthetical caveats
  * Acronyms — ALWAYS: <say-as interpret-as="characters">GPU</say-as>, <say-as interpret-as="characters">LLM</say-as>, <say-as interpret-as="characters">API</say-as>, <say-as interpret-as="characters">MCP</say-as>, <say-as interpret-as="characters">RAG</say-as>, <say-as interpret-as="characters">TPU</say-as>, <say-as interpret-as="characters">SDK</say-as>, <say-as interpret-as="characters">AI</say-as>
  * Numbers: <say-as interpret-as="cardinal">5.5 billion</say-as> for funding; <say-as interpret-as="currency" language="en-IN">1500 crore</say-as> for Indian amounts
  * SSML RULES: valid XML, balanced tags. Do NOT nest <prosody> inside <prosody>. Escape & as &amp; in text. Do NOT use SSML in content_plain.
- End each P0 story with: "If someone asks you about this in an interview, here's your edge: [INTERVIEW EDGE insight]"
- Quick hits: rapid-fire with energy, "In quick hits: [story 1]. [story 2]. [story 3]."
- You may editorialize on the *implications* of facts in the summaries — what it means, why it matters, what changes. Never invent new facts, names, numbers, or quotes.
- BREVITY IS A FEATURE. If a story doesn't yield a crisp PM takeaway in 2 sentences, move on. A well-covered 3-minute story should be 3 minutes — not padded to 6. Target total episode ~45 minutes.

CRITICAL — Factual grounding: Only use facts, names, product names, statistics, and quotes
that appear in the article summaries provided. Do not invent, extrapolate, or add any fact
not present in the data. If a detail isn't in the summaries, omit it entirely.

Return ONLY valid JSON — no markdown fences, no explanation."""


_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


class ScriptWriterAgent:
    def run(
        self,
        summaries: list[ArticleSummary],
        date: str,
        expansion_mode: bool = False,
        coverage_gaps: list[str] | None = None,
    ) -> PodcastScript:
        self._expansion_mode = expansion_mode
        self._coverage_gaps = coverage_gaps or []
        log.info(
            "script_writer_start",
            summary_count=len(summaries),
            date=date,
            expansion_mode=expansion_mode,
            gap_count=len(self._coverage_gaps),
        )

        grouped = self._group_by_segment(summaries)
        formatted_date = self._format_date(date)

        segments: list[Segment] = []
        generated_plain_texts: list[str] = []

        # Segments that always run even with no routed articles
        _ALWAYS_GENERATE = {"opener", "closing"}

        for seg_id, seg_title in _SEGMENT_ORDER:
            seg_summaries = grouped.get(seg_id, [])

            # Opener receives no article summaries — it builds a section-preview
            # from all_summaries via _build_segment_prompt special handling.
            if seg_id == "opener":
                seg_summaries = []

            # Skip content segments with no articles — avoids LLM hallucinating invented stories
            if not seg_summaries and seg_id not in _ALWAYS_GENERATE:
                log.info("segment_skipped_empty", segment_type=seg_id)
                continue

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
                log.info("segment_done", segment_type=seg_id, duration_sec=seg.duration_estimate_sec, chars=len(seg.content_plain))
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

    def expand_segments(
        self,
        script: PodcastScript,
        summaries: list[ArticleSummary],
        date: str,
        coverage_gaps: list[str],
    ) -> PodcastScript:
        """Regenerate only the segments that contain gap articles.

        All other segments are preserved verbatim from *script* so LLM variance
        cannot shrink segments that were already adequate.
        """
        self._expansion_mode = True
        self._coverage_gaps = coverage_gaps

        gap_set = set(coverage_gaps)
        gap_seg_types: set[str] = {
            _CATEGORY_TO_SEGMENT.get(s.category, "quick_hits")
            for s in summaries
            if s.article_id in gap_set
        }

        if not gap_seg_types:
            return script

        log.info("expansion_targeted", gap_seg_types=sorted(gap_seg_types))

        grouped = self._group_by_segment(summaries)
        formatted_date = self._format_date(date)

        seg_by_type = {seg.segment_type: seg for seg in script.segments}
        new_segments: list[Segment] = []
        generated_plain_texts: list[str] = []

        for seg_id, seg_title in _SEGMENT_ORDER:
            if seg_id not in seg_by_type:
                continue

            if seg_id not in gap_seg_types:
                orig = seg_by_type[seg_id]
                new_segments.append(orig)
                generated_plain_texts.append(orig.content_plain)
                continue

            seg_summaries = [] if seg_id == "opener" else grouped.get(seg_id, [])
            if not seg_summaries:
                orig = seg_by_type[seg_id]
                new_segments.append(orig)
                generated_plain_texts.append(orig.content_plain)
                continue

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
                new_segments.append(seg)
                generated_plain_texts.append(seg.content_plain)
                log.info("segment_expanded", segment_type=seg_id, duration_sec=seg.duration_estimate_sec)
            except Exception as e:
                log.error("segment_expansion_failed", segment_type=seg_id, error=str(e))
                orig = seg_by_type[seg_id]
                new_segments.append(orig)
                generated_plain_texts.append(orig.content_plain)

        total_min = sum(s.duration_estimate_sec for s in new_segments) // 60
        return PodcastScript(
            episode_number=script.episode_number,
            date=script.date,
            total_estimated_duration_min=total_min,
            segments=new_segments,
            top_takeaways=script.top_takeaways,
        )

    # -------------------------------------------------------------------------
    # Segment generation
    # -------------------------------------------------------------------------

    def _batch_summaries(self, summaries: list[ArticleSummary]) -> list[list[ArticleSummary]]:
        """
        Pack summaries into batches where no batch exceeds _MAX_SUMMARY_CHARS_PER_CALL
        of total summary text. A single article is never split across batches — if one
        article alone exceeds the limit, it gets its own batch.
        """
        if not summaries:
            return [[]]

        batches: list[list[ArticleSummary]] = []
        current: list[ArticleSummary] = []
        current_chars = 0

        for article in summaries:
            article_chars = len(article.summary_text or "")
            if current and current_chars + article_chars > _MAX_SUMMARY_CHARS_PER_CALL:
                batches.append(current)
                current = [article]
                current_chars = article_chars
            else:
                current.append(article)
                current_chars += article_chars

        if current:
            batches.append(current)

        return batches

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
        batches = self._batch_summaries(summaries)

        if len(batches) <= 1:
            # Single call — existing JSON path (no regression for short segments)
            return self._generate_segment_single(
                seg_id, seg_title, summaries, formatted_date, all_summaries, prior_plain_texts
            )

        # Multi-call path — each batch returns plain text (avoids JSON truncation failures)
        log.info(
            "segment_multi_call",
            segment_type=seg_id,
            batch_count=len(batches),
            total_articles=len(summaries),
        )
        parts: list[str] = []
        all_source_ids: list[str] = []

        expand = getattr(self, "_expansion_mode", False)
        for i, batch in enumerate(batches):
            is_opener = (i == 0)
            batch_summary_chars = sum(len(s.summary_text or "") for s in batch)
            part_text = self._generate_segment_part(
                seg_id, batch, is_opener,
                expansion_mode=expand,
                batch_summary_chars=batch_summary_chars,
            )
            parts.append(part_text)
            all_source_ids.extend(s.article_id for s in batch)

        combined_plain = ' '.join(re.sub(r"<[^>]+>", "", p) for p in parts)
        combined_ssml = ' <break time="1000ms"/> '.join(parts)
        duration_sec = max(30, len(combined_plain) // _CHARS_PER_SEC)

        return Segment(
            id=str(uuid.uuid4()),
            title=seg_title,
            segment_type=seg_id,
            content_ssml=combined_ssml,
            content_plain=combined_plain,
            duration_estimate_sec=duration_sec,
            source_article_ids=all_source_ids,
        )

    def _get_expansion_note(self, seg_id: str, summaries: list[ArticleSummary] | None = None) -> str:
        """Segment-specific expansion instructions for the multi-call plain-text path."""
        # Build the targeted gap list if we have specific gap article IDs
        gap_titles: list[str] = []
        if self._coverage_gaps and summaries:
            gap_set = set(self._coverage_gaps)
            gap_titles = [s.title for s in summaries if s.article_id in gap_set]

        if gap_titles:
            gap_list = "\n".join(f"  - {t}" for t in gap_titles)
            prefix = (
                "EXPANSION MODE — the following articles were not adequately covered in "
                "the first pass and MUST be narrated now:\n"
                f"{gap_list}\n\n"
                "For EACH article listed above, ensure the narration covers:\n"
                "  1. Core news (what happened)\n"
                "  2. Surrounding impact (who it affects, ecosystem shift)\n"
                "  3. Competitor context (if present in the summary)\n"
                "  4. Why it was built/launched\n"
                "  5. How it works technically\n"
                "  6. PM interview edge\n\n"
                "Do NOT re-cover articles that are already well-narrated. "
                "Do NOT pad. Focus only on the gaps listed above.\n"
            )
        else:
            prefix = (
                "EXPANSION MODE — your only goal is to ensure EVERY article in the list below "
                "has been covered at appropriate depth. Check for articles that were skipped or "
                "only mentioned in passing in the first pass and give them proper coverage. "
                "Do NOT make already-covered articles longer. Do NOT pad. "
                "If all articles are already well-covered, the right answer is a shorter episode — "
                "accept it and do not inflate content.\n"
            )
        notes = {
            "ai_updates": (
                prefix +
                "For each article: what happened → technical angle → why it matters for a PM. "
                "Treat P1 articles with the same structure as P0, but keep each story to 2-3 sentences "
                "per section. Move on as soon as the key insight is clear."
            ),
            "funding": (
                prefix +
                "For each funding story: round size + lead backer → what the valuation implies → "
                "one PM insight about the business model or competitive shift. Then move on."
            ),
            "india_tech": (
                prefix +
                "For each India story: what the company does → what happened → founder/market context → "
                "one PM angle. Concise — Indian ecosystem stories are often self-contained."
            ),
            "product_strategy": (
                prefix +
                "For each story: the strategic move → who wins/loses → one PM decision framework angle. "
                "Keep it tight — strategy stories land better as punchy insights than long explanations."
            ),
            "quick_hits": (
                prefix +
                "2-3 sentences per story max: what happened + why it matters for engineers building AI. "
                "No padding — if a story only warrants one sentence, keep it one sentence."
            ),
        }
        return notes.get(seg_id, prefix + "Cover each story clearly then move to the next.")

    def _generate_segment_part(
        self,
        seg_id: str,
        summaries: list[ArticleSummary],
        is_opener: bool,
        expansion_mode: bool = False,
        batch_summary_chars: int = 0,
    ) -> str:
        """
        Generate one part of a multi-batch segment as plain text (no JSON wrapper).
        Plain text avoids the JSON truncation failures that occur when output hits
        the token limit mid-string-value.

        In expansion_mode, token budget scales dynamically with content richness:
        output_tokens ≈ batch_summary_chars // 3 (1:3 ratio), capped at segment max.
        """
        summaries_json = json.dumps(
            [
                {
                    "article_id": s.article_id,
                    "title": s.title,
                    "priority": s.priority.value,
                    "summary": s.summary_text,
                    "interview_edge_hint": s.discussion_points[0] if s.discussion_points else "",
                }
                for s in summaries
            ],
            indent=2,
        )

        opener_note = (
            self._get_segment_opener(seg_id) if is_opener
            else "Continue the segment — no new signpost intro, just keep going from the previous article."
        )

        expansion_note = f"\n{self._get_expansion_note(seg_id, summaries)}\n" if expansion_mode else ""

        user_prompt = f"""Write podcast narration for the following articles. Return PLAIN TEXT only — no JSON, no markdown.

Segment: {seg_id}
{opener_note}
{expansion_note}
DEPTH RULE: Cover each article to the right level of depth — what happened, why it matters technically, and the PM angle. Once that is clear, STOP and move to the next article. Do not pad, repeat, or add filler sentences to reach a word count target. A well-covered 2-minute story should be 2 minutes, not 4.
CRITICAL: Only use facts that appear in the summaries below. Do not invent product names, statistics, or facts.
For each article end with a 2-3 sentence interview insight starting with "If someone asks you about this in an interview, here's your edge:"
{_INTERVIEW_EDGE_INSTRUCTION}

Articles:
{summaries_json}"""

        # Dynamic token budget: in expansion mode, scale to content richness (1:3 output-to-input).
        # In normal mode, cap at 1024 — plain text truncation is safe but we don't need more.
        if expansion_mode and batch_summary_chars > 0:
            max_tokens = min(
                _SEGMENT_MAX_TOKENS.get(seg_id, 2048),
                max(1024, batch_summary_chars // 3),
            )
        else:
            max_tokens = min(1024, _SEGMENT_MAX_TOKENS.get(seg_id, 1024))

        last_error: Exception = RuntimeError("no attempts made")
        for attempt in range(_MAX_RETRIES + 1):
            try:
                text = chat(
                    model_hint="claude-sonnet-4-6",
                    system=_SYSTEM_PROMPT,
                    user=user_prompt,
                    max_tokens=max_tokens,
                    local_model_override=_SCRIPT_LOCAL_MODEL,
                    openrouter_models=_OPENROUTER_SCRIPT_MODELS,
                )
                text = text.strip()
                # qwen2.5:7b sometimes wraps in markdown fences (```json ... ```) or
                # a JSON object ({"podcast_narration": "..."}) despite plain-text instructions.
                # Strip both so neither appears verbatim in the audio.
                text = self._strip_fences(text)
                text = self._unwrap_json_plain(text)
                if len(text) < 20:
                    raise ValueError(f"part too short ({len(text)} chars)")
                suspect_count = self._grounding_check(text, summaries, seg_id)
                if suspect_count >= 3:
                    raise ValueError(f"grounding_check failed: {suspect_count} suspect facts — regenerating")
                return text
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    log.warning("segment_part_retry", segment_type=seg_id, attempt=attempt + 1, error=str(e))

        # Fallback — return a brief filler so the rest of the segment still assembles
        log.error("segment_part_failed", segment_type=seg_id, error=str(last_error))
        return f"Continuing with more {seg_id.replace('_', ' ')} coverage."

    def _get_segment_opener(self, seg_id: str) -> str:
        """Return the verbal signpost that opens a segment (used in multi-call parts)."""
        openers = {
            "opener": "Open with: \"Hey, welcome to today's episode of NewsFlow.\"",
            "ai_updates": "Open with a fresh segment bridge into AI and tech — do not say 'Moving on'.",
            "funding": "Open with a fresh segment bridge into funding and business news — do not say 'Moving on'.",
            "india_tech": "Open with a fresh segment bridge into India tech news — do not say 'Moving on'.",
            "product_strategy": "Open with a fresh segment bridge into product and strategy — do not say 'Moving on'.",
            "quick_hits": "Open with: \"In quick hits today:\"",
        }
        return openers.get(seg_id, f"Begin the {seg_id} segment.")

    def _build_opener_section_map(self, all_summaries: list[ArticleSummary]) -> str:
        """Build a section-wise article title preview for the opener segment."""
        section_order = [
            ("ai_updates", "AI & big tech"),
            ("funding", "Funding"),
            ("india_tech", "India tech"),
            ("product_strategy", "Product & strategy"),
            ("quick_hits", "Quick hits"),
        ]
        section_tops: dict[str, list[str]] = {}
        for s in all_summaries:
            seg = _CATEGORY_TO_SEGMENT.get(s.category)
            if seg and seg in {sid for sid, _ in section_order}:
                if len(section_tops.get(seg, [])) < 2:
                    section_tops.setdefault(seg, []).append(s.title)

        lines = []
        for seg_id, label in section_order:
            titles = section_tops.get(seg_id, [])
            if titles:
                lines.append(f"  {label}: {' / '.join(titles)}")
        return "\n".join(lines) if lines else "  (no articles available)"

    def _generate_segment_single(
        self,
        seg_id: str,
        seg_title: str,
        summaries: list[ArticleSummary],
        formatted_date: str,
        all_summaries: list[ArticleSummary],
        prior_plain_texts: list[str],
    ) -> Segment:
        """Single-call path — existing JSON-based generation for small segments."""
        user_prompt = self._build_segment_prompt(
            seg_id, seg_title, summaries, formatted_date, all_summaries, prior_plain_texts
        )
        base_tokens = _SEGMENT_MAX_TOKENS.get(seg_id, 2048)
        _eff = summaries if summaries else all_summaries[:5]
        if getattr(self, "_expansion_mode", False) and _eff:
            total_summary_chars = sum(len(s.summary_text or "") for s in _eff)
            # Scale to content richness (1:3 output-to-input), floor at base, ceiling at 2× base
            max_tokens = min(base_tokens * 2, max(base_tokens, total_summary_chars // 3))
        else:
            max_tokens = base_tokens

        last_error: Exception = RuntimeError("no attempts made")
        for attempt in range(_MAX_RETRIES + 1):
            try:
                raw = chat(
                    model_hint="claude-sonnet-4-6",
                    system=_SYSTEM_PROMPT,
                    user=user_prompt,
                    max_tokens=max_tokens,
                    local_model_override=_SCRIPT_LOCAL_MODEL,
                    openrouter_models=_OPENROUTER_SCRIPT_MODELS,
                )

                raw = self._strip_fences(raw)
                raw = self._clean_json(raw)
                data = json.loads(raw)

                content_plain = data.get("content_plain", "")
                # If the model wrapped plain text in a JSON object inside content_plain
                # (e.g. {"podcast_narration": "..."}), unwrap it.
                content_plain = self._unwrap_json_plain(content_plain)
                # Strip any HTML/XML tags the model inserted (e.g. <br><br>) — only SSML
                # tags belong in content_ssml, content_plain must be tag-free.
                content_plain = re.sub(r"<[^>]+>", "", content_plain)
                # Detect placeholder text that the model returned verbatim from the template
                _PLACEHOLDER_SIGNALS = (
                    "WRITE THE FULL SCRIPT",
                    "WRITE THE SAME SCRIPT",
                    "SSML TAGS HERE",
                )
                if len(content_plain) < 30 or any(p in content_plain for p in _PLACEHOLDER_SIGNALS):
                    raise ValueError(f"placeholder/empty content_plain ({len(content_plain)} chars)")

                suspect_count = self._grounding_check(content_plain, summaries, seg_id)
                if suspect_count >= 3:
                    raise ValueError(f"grounding_check failed: {suspect_count} suspect facts — regenerating")

                # Compute duration from actual content length.
                # The model always returns 120 regardless of length, so we ignore its estimate.
                # Measured gTTS pace: ~13 chars/sec (22452 chars → 1714s actual).
                duration_sec = max(30, len(content_plain) // _CHARS_PER_SEC)

                content_ssml = data.get("content_ssml", content_plain)
                content_ssml = self._validate_ssml(content_ssml, content_plain)

                return Segment(
                    id=data.get("id", str(uuid.uuid4())),
                    title=seg_title,
                    segment_type=seg_id,
                    content_ssml=content_ssml,
                    content_plain=content_plain,
                    duration_estimate_sec=duration_sec,
                    source_article_ids=data.get("source_article_ids", []),
                )
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    log.warning("segment_retry", segment_type=seg_id, attempt=attempt + 1, error=str(e))

        raise last_error

    @staticmethod
    def _validate_ssml(ssml: str, plain_fallback: str) -> str:
        """Return ssml if it parses as valid XML, otherwise fall back to plain text.

        Wraps in a dummy <s> root since content_ssml is a fragment, not a doc.
        Strips markdown bold/italic markers first so TTS doesn't narrate asterisks.
        """
        # Strip markdown bold (**text** or __text__) and italic (*text* or _text_)
        # before XML validation — free-tier LLMs leak markdown into SSML.
        cleaned = re.sub(r"\*{1,2}|_{1,2}", "", ssml)
        try:
            ET.fromstring(f"<s>{cleaned}</s>")
            return cleaned
        except ET.ParseError:
            log.warning("ssml_invalid_xml_fallback", chars=len(cleaned))
            return plain_fallback

    def _build_segment_prompt(
        self,
        seg_id: str,
        seg_title: str,
        summaries: list[ArticleSummary],
        formatted_date: str,
        all_summaries: list[ArticleSummary],
        prior_plain_texts: list[str],
    ) -> str:
        instructions = self._segment_instructions(seg_id, formatted_date, all_summaries, prior_plain_texts)

        # Opener uses a section-title map, not full article summaries
        if seg_id == "opener":
            section_map = self._build_opener_section_map(all_summaries)
            return f"""Write the "Opener" segment for today's NewsFlow podcast.

{instructions}

Section topics available today (paraphrase — do not list titles verbatim):
{section_map}

Return ONLY this JSON object:
{{
  "id": "{uuid.uuid4()}",
  "segment_type": "opener",
  "content_ssml": "WRITE THE OPENER HERE using <break time=\\"800ms\\"/> for pauses, <emphasis level=\\"moderate\\">key terms</emphasis>, and <say-as interpret-as=\\"characters\\">GPU</say-as> for acronyms",
  "content_plain": "WRITE THE SAME OPENER HERE but with no SSML tags",
  "duration_estimate_sec": 40,
  "source_article_ids": []
}}"""

        # For all other segments with no routed articles (closing), fall back to top 5
        effective_summaries = summaries if summaries else all_summaries[:5]

        summaries_json = json.dumps(
            [
                {
                    "article_id": s.article_id,
                    "title": s.title,
                    "priority": s.priority.value,
                    "summary": s.summary_text,
                    # Renamed from "interview_edge" → "interview_edge_hint" so the model
                    # treats it as a topic prompt to expand, not text to copy verbatim.
                    "interview_edge_hint": s.discussion_points[0] if s.discussion_points else "",
                }
                for s in effective_summaries
            ],
            indent=2,
        )

        return f"""Write the "{seg_title}" segment for today's NewsFlow podcast ({formatted_date}).

{instructions}

{"Articles for this segment:" if effective_summaries else "No articles for this segment — write a brief transition."}
{summaries_json if effective_summaries else "[]"}

{_INTERVIEW_EDGE_INSTRUCTION}

Return ONLY this JSON object. Fill in every field with real content — do not return placeholder text:
{{
  "id": "{uuid.uuid4()}",
  "segment_type": "{seg_id}",
  "content_ssml": "WRITE THE FULL SCRIPT HERE using SSML: <break time=\\"800ms\\"/> for pauses, <emphasis level=\\"moderate\\">key terms</emphasis>, <prosody rate=\\"92%\\">dense technical clauses</prosody>, <say-as interpret-as=\\"characters\\">LLM</say-as> for acronyms",
  "content_plain": "WRITE THE SAME SCRIPT HERE but with no SSML tags at all",
  "duration_estimate_sec": 120,
  "source_article_ids": ["article_id_1", "article_id_2"]
}}"""

    def _segment_instructions(
        self,
        seg_id: str,
        formatted_date: str,
        all_summaries: list[ArticleSummary],
        prior_plain_texts: list[str],
    ) -> str:
        expand = getattr(self, "_expansion_mode", False)

        instructions = {
            "opener": (
                "Duration: <=45 seconds (~110 words max). "
                "Open naturally: 'Hey, welcome to today's episode of NewsFlow.' "
                "Do NOT mention the date. Then in one flowing paragraph, preview each section "
                "by paraphrasing its 1-2 key topics. Order: AI & big tech, funding, India tech, "
                "product strategy, quick hits. Skip any section with zero articles. "
                "Each section preview is 1 sentence max — tease, do not explain or deep-dive. "
                "End with a short energy line like 'Let's get into it.' "
                "Strictly base previews on the section topics provided below. Do not invent."
            ),
            "ai_updates": (
                "Duration: 15-18 minutes. "
                "P0 stories: deep dive, 3-4 minutes each (what happened → technical angle → PM takeaway + INTERVIEW EDGE). Cover max 3 P0 stories. "
                "P1 stories: 60-90 seconds each (what happened in 2-3 sentences + 1 crisp PM takeaway). "
                "P2 stories: skip — they belong in quick_hits. "
                + (
                    "EXPANSION MODE — a P0 article was missed in the first pass. Cover it now with full depth: "
                    "CORE NEWS + technical angle + PM INTERVIEW EDGE. Keep other stories at their current depth. "
                    if expand else ""
                )
                + "Use signpost: 'Let's start with what's new in tech and AI...' "
                "End EVERY P0 story with the INTERVIEW EDGE insight. Move on once the key insight is clear."
            ),
            "funding": (
                "Duration: 6-8 minutes. "
                "Cover top 3-4 funding rounds: round size + lead backer → what valuation implies → one PM insight. "
                "1 minute per story max. If more rounds exist, name them in one quick-list sentence at the end. "
                + (
                    "EXPANSION MODE — cover any missed funding story now. Add: what the round signals for the ecosystem + PM angle. "
                    if expand else ""
                )
                + "Open with a fresh segment bridge into this section — do not say 'Moving on'."
            ),
            "india_tech": (
                "Duration: 4-5 minutes. India-focused startup and tech stories. "
                "ALWAYS render this section — never skip it, even if only 1-2 stories. "
                "If thin: cover 1-2 stories at normal depth. Do not pad or invent context. "
                + (
                    "EXPANSION MODE — cover any missed India story now with full context: company + what happened + market angle. "
                    if expand else ""
                )
                + "Open with a fresh segment bridge into India tech — do not say 'Moving on' or 'Now a look at'."
            ),
            "product_strategy": (
                "Duration: 5-7 minutes. Industry strategy, SaaS disruption, Series B+ moves. "
                "Top 2-3 stories: strategic move → who wins/loses → one PM decision framework angle. "
                "Keep punchy — strategy stories land better as crisp insights than long explanations. "
                + (
                    "EXPANSION MODE — cover any missed strategy story now. Focus on the business model angle and PM takeaway. "
                    if expand else ""
                )
                + "Open with a fresh segment bridge into product and strategy — do not say 'Moving on' or 'Time for product'."
            ),
            "quick_hits": (
                "Duration: 3-4 minutes. Rapid-fire — one-liner per story: title paraphrase + one sentence on why it matters. "
                "No interview edges here, no deep dives. Move fast. "
                + (
                    "EXPANSION MODE — give each story 2 sentences max. No more. "
                    if expand else ""
                )
                + "Start: 'In quick hits today:' then cover each story. Keep energy high."
            ),
            "closing": (
                "Duration: 2-3 minutes. '3 things to remember from today' — one sentence each. "
                "Reference the strongest P0 stories and their interview edges. "
                "End with: 'That's your NewsFlow for today. Stay sharp. See you tomorrow.'"
            ),
        }
        return instructions.get(seg_id, f"Write the {seg_id} segment.")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def regenerate_segment(
        self,
        seg_id: str,
        summaries: list[ArticleSummary],
        date: str,
        all_summaries: list[ArticleSummary] | None = None,
    ) -> Segment:
        """Public method: regenerate a single segment (used by ScriptValidatorAgent)."""
        self._expansion_mode = False
        self._coverage_gaps = []
        formatted_date = self._format_date(date)
        seg_title = {sid: title for sid, title in _SEGMENT_ORDER}.get(seg_id, seg_id.replace("_", " ").title())
        effective_all = all_summaries if all_summaries is not None else summaries
        return self._generate_segment(
            seg_id=seg_id,
            seg_title=seg_title,
            summaries=summaries,
            date=date,
            formatted_date=formatted_date,
            all_summaries=effective_all,
            prior_plain_texts=[],
        )

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

    def _unwrap_json_plain(self, text: str) -> str:
        """
        qwen2.5:7b sometimes wraps plain-text responses in a JSON object despite
        being told to return plain text. Two patterns observed in production:

        1. String value:  {"podcast_narration": "Let's start with..."}
        2. List of dicts: {"podcast_narration": [{"segment": "...", "summary": "..."}, ...]}
           (seen in ai_updates multi-call batches)

        For case 2, find the key whose list items have the most total text,
        then concatenate those string values with a space.
        """
        stripped = text.strip()
        if not stripped.startswith("{"):
            return text
        try:
            data = json.loads(stripped)
            if not isinstance(data, dict):
                return text

            for v in data.values():
                # Case 1: direct string value
                if isinstance(v, str) and len(v) > 20:
                    return v
                # Case 2a: list of strings — join them
                if isinstance(v, list) and v and all(isinstance(item, str) for item in v):
                    joined = " ".join(item for item in v if len(item) > 10)
                    if joined:
                        return joined
                # Case 2b: list of dicts — extract the longest string field per item
                if isinstance(v, list) and v:
                    parts = []
                    for item in v:
                        if not isinstance(item, dict):
                            break
                        # Pick the string field with the most text in this item
                        best = max(
                            (val for val in item.values() if isinstance(val, str)),
                            key=len,
                            default=None,
                        )
                        if best and len(best) > 10:
                            parts.append(best)
                    if parts:
                        return " ".join(parts)
        except (json.JSONDecodeError, ValueError):
            pass
        return text

    def _insert_missing_comma(self, raw: str) -> str:
        """
        Fix missing commas between JSON fields using JSONDecodeError position info.
        qwen2.5:7b sometimes omits the comma after a long field value:
          "content_plain": "..."     ← no comma here
          "duration_estimate_sec": 120
        json.loads reports exact position of the unexpected token — insert comma there.
        Up to 5 insertions per string (handles multiple missing commas).
        """
        for _ in range(5):
            try:
                json.loads(raw)
                return raw  # already valid
            except json.JSONDecodeError as e:
                if "Expecting ',' delimiter" in str(e) and e.pos > 0:
                    raw = raw[:e.pos] + "," + raw[e.pos:]
                else:
                    return raw  # different error — let the state machine handle it
        return raw

    def _clean_json(self, raw: str) -> str:
        """
        Fix common JSON formatting issues from local LLM output:
          1. Missing commas between fields (qwen2.5:7b omits after long values)
          2. Unescaped control characters (literal \\n/\\t inside strings)
          3. Invalid escape sequences (\\< from SSML, \\[ etc.)
          4. Trailing content after the closing } of the JSON object
          5. Unescaped double-quotes inside string values (e.g. <audio"> in SSML)

        Uses a state-machine that walks char-by-char, tracking string context.
        For case 5: when inside a string and we see '"', look ahead past whitespace;
        if the next structural character is NOT in ':,}]' then this quote is an
        unescaped inner quote (not the end of the string) — escape it.
        """
        # Step 1: Extract just the first complete JSON object
        # (handles trailing text / explanation after the closing brace)
        raw = self._extract_first_object(raw)

        # Step 2: Walk char-by-char, fixing string content
        # NOTE: _insert_missing_comma is intentionally called AFTER the state machine.
        # Calling it before fails when content_ssml contains unescaped SSML quotes like
        # <break time="500ms"/> — json.loads reports the error at the SSML quote position,
        # not at the actual missing comma, so the comma gets inserted in the wrong place.
        # The state machine escapes those inner quotes first; then comma insertion works.
        _VALID_ESCAPES = set('"\\bfnrtu/')
        _CTRL_ESC = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
        # Also include '"' — handles missing comma between fields ("value"\n"key":)
        _STRING_TERMINATORS = frozenset(':,}]"')
        result: list[str] = []
        in_string = False
        i = 0
        while i < len(raw):
            c = raw[i]
            if c == "\\" and in_string:
                nxt = raw[i + 1] if i + 1 < len(raw) else ""
                if nxt in _VALID_ESCAPES:
                    # Valid escape — keep as-is
                    result.append(c)
                    result.append(nxt)
                    i += 2
                else:
                    # Invalid escape (e.g. \< from SSML) — drop the backslash
                    result.append(nxt)
                    i += 2
                continue
            if c == '"':
                if in_string:
                    # Look ahead past whitespace to find the next structural character.
                    # If it's a JSON terminator (:,}]) this quote ends the string.
                    # Otherwise it's an unescaped inner quote — escape it.
                    j = i + 1
                    while j < len(raw) and raw[j] in ' \t\r\n':
                        j += 1
                    next_ch = raw[j] if j < len(raw) else ''
                    if next_ch in _STRING_TERMINATORS:
                        in_string = False
                        result.append(c)
                    else:
                        # Unescaped quote inside a string value — escape it
                        result.append('\\')
                        result.append(c)
                else:
                    in_string = True
                    result.append(c)
            elif in_string and ord(c) < 0x20:
                result.append(_CTRL_ESC.get(c, ""))
            else:
                result.append(c)
            i += 1

        cleaned = "".join(result)
        # Post-walk: fix any missing commas now that unescaped quotes are resolved
        cleaned = self._insert_missing_comma(cleaned)
        return cleaned

    def _extract_first_object(self, raw: str) -> str:
        """Return the substring from the first '{' to its matching '}'."""
        start = raw.find("{")
        if start == -1:
            return raw
        depth = 0
        in_string = False
        i = start
        while i < len(raw):
            c = raw[i]
            if c == "\\" and in_string:
                i += 2
                continue
            if c == '"':
                in_string = not in_string
            elif not in_string:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return raw[start: i + 1]
            i += 1
        return raw[start:]  # no matching close brace — return from { to end

    def _extract_top_takeaways(self, summaries: list[ArticleSummary]) -> list[str]:
        takeaways = []
        for s in summaries:
            if s.key_takeaways:
                takeaways.extend(s.key_takeaways)
            if len(takeaways) >= 3:
                break
        return takeaways[:3]

    def _fallback_segment(self, seg_id: str, seg_title: str) -> Segment:
        _BRIDGES = [
            f"We'll catch up on {seg_title} in tomorrow's episode.",
            f"Nothing on {seg_title} today — back tomorrow.",
            f"{seg_title} coverage picks up in the next episode.",
            f"Skipping {seg_title} today — nothing that clears the bar.",
        ]
        text = _BRIDGES[hash(seg_id) % len(_BRIDGES)]
        return Segment(
            id=str(uuid.uuid4()),
            title=seg_title,
            segment_type=seg_id,
            content_ssml=text,
            content_plain=text,
            duration_estimate_sec=10,
            source_article_ids=[],
        )

    def _grounding_check(
        self,
        script_text: str,
        source_summaries: list[ArticleSummary],
        seg_id: str,
    ) -> int:
        """
        Check numeric claims in script against source summaries.
        Returns count of suspect sentences (unmatched dollar amounts / percentages).
        Caller raises ValueError to trigger retry when count is too high.
        """
        if not source_summaries:
            return 0

        all_summary_text = " ".join(
            (s.summary_text or "") + " " + s.title for s in source_summaries
        ).lower()

        # Match: $50B, $1.2M, 95%, 50 billion, etc.
        fact_pattern = re.compile(
            r'\$[\d.,]+\s*[BMKbmk]?\b|\b\d[\d.,]*\s*%', re.IGNORECASE
        )

        sentences = re.split(r'(?<=[.!?])\s+', script_text)
        total_warned = 0
        for sentence in sentences:
            for match in fact_pattern.finditer(sentence):
                # Extract just the digit sequence for loose matching
                digits = re.sub(r'[^0-9]', '', match.group())
                if digits and digits not in all_summary_text.replace(',', '').replace('.', ''):
                    log.warning(
                        "grounding_suspect_fact",
                        segment=seg_id,
                        fact=match.group(),
                        sentence=sentence[:120],
                    )
                    total_warned += 1
                    break  # one warning per sentence is enough

        if total_warned:
            log.warning(
                "grounding_check_summary",
                segment=seg_id,
                suspect_sentences=total_warned,
                note="Review script for possible hallucinated numeric facts",
            )
        return total_warned
