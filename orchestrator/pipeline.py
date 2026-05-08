"""
Pipeline Orchestrator
Runs the full NewsFlow pipeline sequentially with checkpoint/recovery support.
Each stage saves its output to workspace/{date}/ — re-run skips completed stages.

Trace files are written to workspace/{date}/logs/ after each stage:
  pipeline.log          — all stdout/structlog output
  1_ingestion.txt       — articles extracted per source
  2_curation.txt        — priority + category per article
  3_summarization.txt   — content source (trafilatura/snippet) + full summary text
  4_script.txt          — all segment content (full plain text)
"""
import json
import os
import sys
import textwrap
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Windows: default console encoding (CP1252) can't handle emoji in newsletter subjects.
# Force UTF-8 for all stdout/stderr output before structlog initialises.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load .env BEFORE importing agents — llm_client.py reads USE_LOCAL_LLM at module level.
from dotenv import load_dotenv
load_dotenv(override=True)  # override=True ensures .env wins over existing system env vars

import structlog

from agents.audio_producer import AudioProducerAgent
from agents.curator import CuratorAgent
from agents.ingestion import IngestionAgent
from agents.script_writer import ScriptWriterAgent
from agents.summarizer import SummarizerAgent
from models.article import ArticleSummary, CuratedArticle, RawArticle
from models.enums import Priority
from models.podcast import Episode, PodcastScript

log = structlog.get_logger(__name__)


# ── Stdout tee (captures all structlog/print output to pipeline.log) ──────────

class _TeeOutput:
    """Writes to both the real stdout and a log file simultaneously."""
    def __init__(self, file_path: str):
        self._file = open(file_path, "w", encoding="utf-8", errors="replace")
        self._real = sys.__stdout__

    def write(self, text: str) -> int:
        self._real.write(text)
        self._file.write(text)
        return len(text)

    def flush(self):
        self._real.flush()
        self._file.flush()

    def isatty(self) -> bool:
        return False

    def close(self):
        self._file.close()

    # Make it usable as a context manager
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        sys.stdout = self._real


# ── JSON checkpoint helpers ────────────────────────────────────────────────────

def _unload_ollama() -> None:
    """Send keep_alive=0 to Ollama to unload the model and free VRAM for TTS."""
    import urllib.request
    local_model = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
    try:
        payload = json.dumps({"model": local_model, "keep_alive": 0}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log.info("ollama_unloaded", model=local_model)
    except Exception as e:
        log.debug("ollama_unload_skipped", reason=str(e))


def _save_json(data, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, list):
            json.dump([item.model_dump(mode="json") for item in data], f, indent=2, default=str)
        else:
            json.dump(data.model_dump(mode="json"), f, indent=2, default=str)


def _load_json(path: str, model_cls):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return [model_cls.model_validate(item) for item in raw]
    return model_cls.model_validate(raw)


# ── Per-stage trace writers ────────────────────────────────────────────────────

def _write_ingestion_trace(articles: list[RawArticle], logs_dir: str) -> None:
    """Stage 1 — one line per article, grouped by source."""
    by_source: dict[str, list[RawArticle]] = defaultdict(list)
    for a in articles:
        by_source[a.source.value].append(a)

    lines = [
        "=" * 70,
        "NEWSFLOW — STAGE 1: INGESTION TRACE",
        "=" * 70,
        f"Total articles extracted: {len(articles)}",
        "",
        "Source breakdown:",
    ]
    for src, arts in sorted(by_source.items(), key=lambda x: -len(x[1])):
        lines.append(f"  {src:<20} {len(arts):>3} articles")
    lines.append("")

    for src, arts in sorted(by_source.items()):
        lines.append(f"{'─' * 70}")
        lines.append(f"[{src.upper()}]  ({len(arts)} articles)")
        lines.append("")
        for i, a in enumerate(arts, 1):
            snippet_preview = (a.snippet or "")[:120].replace("\n", " ")
            lines.append(f"  {i:>2}. {a.title}")
            lines.append(f"      URL:     {a.url}")
            lines.append(f"      Snippet: {snippet_preview}{'...' if len(a.snippet or '') > 120 else ''}")
            lines.append("")

    _write_log(os.path.join(logs_dir, "1_ingestion.txt"), lines)


def _write_curation_trace(
    raw_articles: list[RawArticle],
    curated: list[CuratedArticle],
    logs_dir: str,
) -> None:
    """Stage 2 — priority + category + score, grouped P0→P1→P2. Shows drop count."""
    by_priority: dict[str, list[CuratedArticle]] = defaultdict(list)
    for a in curated:
        by_priority[a.priority.value].append(a)

    # Sort each group by relevance_score descending
    for p in by_priority:
        by_priority[p].sort(key=lambda a: a.relevance_score, reverse=True)

    dropped = len(raw_articles) - len(curated)

    lines = [
        "=" * 70,
        "NEWSFLOW — STAGE 2: CURATION TRACE",
        "=" * 70,
        f"Raw articles in:    {len(raw_articles)}",
        f"Curated articles:   {len(curated)}",
        f"Dropped (P3/dedup/time-budget/title-filter): {dropped}",
        "",
        f"P0: {len(by_priority.get('P0', []))}  |  "
        f"P1: {len(by_priority.get('P1', []))}  |  "
        f"P2: {len(by_priority.get('P2', []))}",
        "",
    ]

    for priority_label in ("P0", "P1", "P2"):
        arts = by_priority.get(priority_label, [])
        if not arts:
            continue
        lines.append(f"{'─' * 70}")
        lines.append(f"[{priority_label}]  {len(arts)} articles")
        lines.append("")
        for i, a in enumerate(arts, 1):
            sources = ", ".join(s.value for s in a.all_sources)
            hook = a.discussion_hooks[0] if a.discussion_hooks else ""
            lines.append(
                f"  {i:>2}. [{a.category.value:<22}  score={a.relevance_score:>5.1f}]  {a.title}"
            )
            lines.append(f"        Sources: {sources}")
            lines.append(f"        Est. dur: {a.estimated_podcast_duration_sec}s")
            if hook:
                hook_wrapped = textwrap.fill(hook, width=65, initial_indent="        Hook: ", subsequent_indent="              ")
                lines.append(hook_wrapped)
            lines.append("")

    _write_log(os.path.join(logs_dir, "2_curation.txt"), lines)


def _write_summarization_trace(
    summaries: list[ArticleSummary],
    enriched_path: str,
    logs_dir: str,
) -> None:
    """
    Stage 3 — for each article: content source (trafilatura chars / snippet-only),
    word count, summary text, key takeaways, interview edge.
    """
    # Build article_id → full_text_chars from enriched JSON if available
    full_text_chars: dict[str, int] = {}
    if Path(enriched_path).exists():
        try:
            with open(enriched_path, "r", encoding="utf-8") as f:
                enriched_list = json.load(f)
            for item in enriched_list:
                ft = item.get("full_text") or ""
                if ft:
                    full_text_chars[item["id"]] = len(ft)
        except Exception:
            pass

    # Build a quick lookup from article_id → CuratedArticle id
    # ArticleSummary.article_id == CuratedArticle.id
    by_priority: dict[str, list[ArticleSummary]] = defaultdict(list)
    for s in summaries:
        by_priority[s.priority.value].append(s)

    total_words = sum(s.word_count for s in summaries)

    lines = [
        "=" * 70,
        "NEWSFLOW — STAGE 3: SUMMARIZATION TRACE",
        "=" * 70,
        f"Total summaries:    {len(summaries)}",
        f"Total words:        {total_words}",
        f"Trafilatura used:   {len(full_text_chars)} articles (full text scraped)",
        f"Snippet-only:       {len(summaries) - len(full_text_chars)} articles",
        "",
    ]

    for priority_label in ("P0", "P1", "P2"):
        arts = by_priority.get(priority_label, [])
        if not arts:
            continue
        lines.append(f"{'─' * 70}")
        lines.append(f"[{priority_label}]  {len(arts)} articles")
        lines.append("")
        for s in arts:
            chars = full_text_chars.get(s.article_id, 0)
            if chars:
                content_src = f"TRAFILATURA — {chars} chars scraped"
            else:
                content_src = "snippet only  (trafilatura not used / fallback)"

            lines.append(f"  ── {s.title}")
            lines.append(f"     Content source: {content_src}")
            lines.append(f"     Word count:     {s.word_count}")
            lines.append("")
            # Indent the summary text
            for line in s.summary_text.splitlines():
                lines.append(f"     {line}")
            lines.append("")
            if s.key_takeaways:
                lines.append("     Key takeaways:")
                for kt in s.key_takeaways:
                    lines.append(f"       • {kt}")
            if s.discussion_points:
                lines.append("     Interview edge:")
                for dp in s.discussion_points:
                    lines.append(f"       • {dp}")
            lines.append("")

    _write_log(os.path.join(logs_dir, "3_summarization.txt"), lines)


def _write_script_trace(script: PodcastScript, logs_dir: str) -> None:
    """Stage 4 — full content_plain for every segment, articles referenced."""
    lines = [
        "=" * 70,
        "NEWSFLOW — STAGE 4: SCRIPT TRACE",
        "=" * 70,
        f"Episode:          #{script.episode_number}",
        f"Date:             {script.date}",
        f"Total duration:   ~{script.total_estimated_duration_min} min",
        f"Segments:         {len(script.segments)}",
        "",
        "Segment overview:",
    ]
    for seg in script.segments:
        dur_min = seg.duration_estimate_sec // 60
        dur_sec = seg.duration_estimate_sec % 60
        dur_str = f"{dur_min}m {dur_sec:02d}s" if dur_min else f"{dur_sec}s"
        lines.append(
            f"  {seg.segment_type:<22} {dur_str:>8}   {len(seg.content_plain):>5} chars"
        )
    lines.append("")

    for seg in script.segments:
        dur_min = seg.duration_estimate_sec // 60
        dur_sec = seg.duration_estimate_sec % 60
        dur_str = f"~{dur_min}m {dur_sec:02d}s" if dur_min else f"~{dur_sec}s"
        lines.append("=" * 70)
        lines.append(f"[{seg.segment_type.upper()}]  {seg.title}  ({dur_str})")
        if seg.source_article_ids:
            lines.append(f"Articles used: {', '.join(seg.source_article_ids[:6])}")
        lines.append("─" * 70)
        lines.append("")
        lines.append(seg.content_plain)
        lines.append("")

    if script.top_takeaways:
        lines.append("=" * 70)
        lines.append("TOP TAKEAWAYS")
        lines.append("─" * 70)
        for t in script.top_takeaways:
            lines.append(f"  • {t}")

    _write_log(os.path.join(logs_dir, "4_script.txt"), lines)


def _write_log(path: str, lines: list[str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log.info("trace_written", path=path)


# ── Coverage gap detection ─────────────────────────────────────────────────────

def _find_coverage_gaps(script: PodcastScript, summaries: list[ArticleSummary]) -> dict:
    """
    Detect P0/P1 articles that were skipped or have thin coverage in the script.

    "Skipped" = article title keywords not found anywhere in the narrated text.
    "Undercovered" = P0 article whose summary contains rich structured sections
      (CORE NEWS, SURROUNDING IMPACT, HOW IT WORKS, PM INTERVIEW EDGE) but may
      not have been fully narrated — flagged for expansion pass.

    Returns {"skipped": [...article_ids], "undercovered": [...article_ids]}
    NOTE: source_article_ids on segments records what went IN to the LLM, not
    what was actually narrated. This function uses content_plain text search instead.
    """
    all_plain_text = " ".join(s.content_plain.lower() for s in script.segments)

    skipped: list[str] = []
    undercovered: list[str] = []

    for summary in summaries:
        if summary.priority not in (Priority.P0, Priority.P1):
            continue

        # Check if meaningful title words appear anywhere in the narrated text
        title_words = [w.lower() for w in summary.title.split() if len(w) > 4]
        mentioned = any(w in all_plain_text for w in title_words[:3])

        if not mentioned:
            skipped.append(summary.article_id)
        elif summary.priority == Priority.P0:
            # P0 is mentioned but check if its rich summary content was narrated.
            # A P0 summary has 6 sections; if ≥3 key sections are present in the
            # summary text, there's rich material that should be narrated in depth.
            sections_present = sum(
                1 for marker in [
                    "CORE NEWS", "SURROUNDING IMPACT", "HOW IT WORKS", "PM INTERVIEW EDGE"
                ]
                if marker in summary.summary_text.upper()
            )
            if sections_present >= 3:
                # Rich summary available — flag for targeted expansion coverage check
                undercovered.append(summary.article_id)

    return {"skipped": skipped, "undercovered": undercovered}


# ── Expansion diff helper ──────────────────────────────────────────────────────

def _build_expansion_diff(
    pre_min: int,
    pre_segments: dict,
    pre_gaps: dict,
    post_script: PodcastScript,
    post_gaps: dict,
    gap_ids: list[str],
) -> dict:
    """Build the expansion diff dict comparing pre/post expansion state.

    Note: articles in the 'undercovered' bucket of post_gaps will structurally
    remain flagged after expansion because _find_coverage_gaps checks summary_text
    section markers (which are never mutated). A non-zero gaps_remaining for
    undercovered articles does not necessarily mean they were not narrated.
    """
    gaps_before = set(gap_ids)
    post_all_gap_ids = set(post_gaps["skipped"] + post_gaps["undercovered"])
    gaps_filled = sorted(gaps_before - post_all_gap_ids)
    gaps_remaining = sorted(post_all_gap_ids)

    post_segments = {
        seg.segment_type: {
            "duration_sec": seg.duration_estimate_sec,
            "article_ids": seg.source_article_ids,
            "char_count": len(seg.content_plain),
        }
        for seg in post_script.segments
    }

    return {
        "pre_expansion": {
            "duration_min": pre_min,
            "segments": pre_segments,
            "gaps": pre_gaps,
        },
        "post_expansion": {
            "duration_min": post_script.total_estimated_duration_min,
            "segments": post_segments,
            "gaps": post_gaps,
        },
        "summary": {
            "gaps_before": len(gaps_before),
            "gaps_after": len(post_all_gap_ids),
            "gaps_filled": gaps_filled,
            "gaps_remaining": gaps_remaining,
            "duration_gain_min": post_script.total_estimated_duration_min - pre_min,
        },
    }


# ── Main pipeline ──────────────────────────────────────────────────────────────

class NewsFlowPipeline:
    def run(self, date: str | None = None) -> Episode:
        date = date or datetime.now().strftime("%Y-%m-%d")
        workspace = os.path.join("workspace", date)
        logs_dir = os.path.join(workspace, "logs")
        Path(logs_dir).mkdir(parents=True, exist_ok=True)

        # Tee all stdout output (structlog uses print → stdout) to pipeline.log
        tee = _TeeOutput(os.path.join(logs_dir, "pipeline.log"))
        sys.stdout = tee

        try:
            return self._run(date, workspace, logs_dir)
        finally:
            sys.stdout = sys.__stdout__
            tee.close()

    def _run(self, date: str, workspace: str, logs_dir: str) -> Episode:
        log.info("pipeline_start", date=date, workspace=workspace)

        # ── Stage 1: Ingestion ───────────────────────────────────────────────
        raw_path = os.path.join(workspace, "raw_articles.json")
        if Path(raw_path).exists():
            log.info("checkpoint_found", stage="ingestion")
            raw_articles = _load_json(raw_path, RawArticle)
        else:
            raw_articles = IngestionAgent().run(date=date)
            _save_json(raw_articles, raw_path)
            log.info("ingestion_complete", count=len(raw_articles))

        _write_ingestion_trace(raw_articles, logs_dir)

        # ── Stage 2: Curation ────────────────────────────────────────────────
        curated_path = os.path.join(workspace, "curated_articles.json")
        if Path(curated_path).exists():
            log.info("checkpoint_found", stage="curator")
            curated = _load_json(curated_path, CuratedArticle)
        else:
            curated = CuratorAgent().run(raw_articles)
            _save_json(curated, curated_path)
            log.info("curation_complete", count=len(curated))

        _write_curation_trace(raw_articles, curated, logs_dir)

        # ── Stage 3: Summarization (includes scraping P0/P1) ────────────────
        summaries_path = os.path.join(workspace, "summaries.json")
        enriched_path = os.path.join(workspace, "curated_articles_enriched.json")
        summarizer = SummarizerAgent()
        summaries = summarizer.run(curated, partial_path=summaries_path)
        # Only write enriched if it doesn't exist — a resume run skips _fetch_full_text
        # and would overwrite the enriched file (with full_text populated) with nulls.
        if not Path(enriched_path).exists():
            _save_json(curated, enriched_path)
        log.info("summarization_complete", count=len(summaries))

        _write_summarization_trace(summaries, enriched_path, logs_dir)

        # ── Stage 4: Script Writing ──────────────────────────────────────────
        script_path = os.path.join(workspace, "podcast_script.json")
        metadata_path = os.path.join(workspace, "episode_metadata.json")
        script_from_checkpoint = Path(script_path).exists()

        if script_from_checkpoint:
            log.info("checkpoint_found", stage="script_writer")
            script = _load_json(script_path, PodcastScript)
        else:
            script = ScriptWriterAgent().run(summaries, date)

        # Coverage gap detection — only run on freshly generated scripts.
        # If loading from checkpoint, expansion was already applied; skip re-detection.
        gap_ids = []
        if not script_from_checkpoint:
            gaps = _find_coverage_gaps(script, summaries)
            skipped_ids = gaps["skipped"]
            undercovered_ids = gaps["undercovered"]
            gap_ids = skipped_ids + undercovered_ids

        if gap_ids:
            log.info(
                "coverage_gaps_detected",
                skipped=len(skipped_ids),
                undercovered=len(undercovered_ids),
                gap_article_ids=gap_ids,
                action="running_targeted_expansion",
            )
            pre_expansion_min = script.total_estimated_duration_min
            pre_expansion_segments = {
                seg.segment_type: {
                    "duration_sec": seg.duration_estimate_sec,
                    "article_ids": seg.source_article_ids,
                    "char_count": len(seg.content_plain),
                }
                for seg in script.segments
            }
            script = ScriptWriterAgent().expand_segments(script, summaries, date, coverage_gaps=gap_ids)
            _save_json(script, script_path)

            # Post-expansion gap re-check and diff logging
            post_gaps = _find_coverage_gaps(script, summaries)
            gain = script.total_estimated_duration_min - pre_expansion_min
            expansion_diff = _build_expansion_diff(
                pre_min=pre_expansion_min,
                pre_segments=pre_expansion_segments,
                pre_gaps={"skipped": skipped_ids, "undercovered": undercovered_ids},
                post_script=script,
                post_gaps=post_gaps,
                gap_ids=gap_ids,
            )
            diff_path = os.path.join(logs_dir, "expansion_diff.json")
            with open(diff_path, "w", encoding="utf-8") as f:
                json.dump(expansion_diff, f, indent=2, default=str)

            gaps_filled = expansion_diff["summary"]["gaps_filled"]
            gaps_remaining = expansion_diff["summary"]["gaps_remaining"]
            log.info(
                "expansion_coverage_result",
                gaps_before=expansion_diff["summary"]["gaps_before"],
                gaps_after=expansion_diff["summary"]["gaps_after"],
                gaps_filled=gaps_filled,
                gaps_remaining=gaps_remaining,
            )
            if gain < 3:
                log.info(
                    "expansion_minimal_gain",
                    before_min=pre_expansion_min,
                    after_min=script.total_estimated_duration_min,
                    gain_min=gain,
                    note="all articles covered at appropriate depth — accepting current length",
                )
            else:
                log.info(
                    "script_expanded",
                    segments=len(script.segments),
                    duration_min=script.total_estimated_duration_min,
                    gain_min=gain,
                )
            # Clear audio checkpoint so TTS re-runs against the expanded script.
            if Path(metadata_path).exists():
                os.remove(metadata_path)
                log.info("audio_checkpoint_cleared", reason="script_expanded")
        elif not script_from_checkpoint:
            _save_json(script, script_path)
            log.info(
                "script_complete",
                segments=len(script.segments),
                duration_min=script.total_estimated_duration_min,
            )
            # Script was freshly generated — clear audio checkpoint so TTS re-runs
            # against the new script (not the stale MP3 from a previous run).
            if Path(metadata_path).exists():
                os.remove(metadata_path)
                log.info("audio_checkpoint_cleared", reason="script_regenerated")

        _write_script_trace(script, logs_dir)

        # ── Stage 5: Audio Production ────────────────────────────────────────
        # Unload Ollama model from VRAM before TTS — frees GPU memory for F5-TTS/Chatterbox.
        _unload_ollama()

        if Path(metadata_path).exists():
            log.info("checkpoint_found", stage="audio_producer")
            episode = _load_json(metadata_path, Episode)
        else:
            episode = AudioProducerAgent().run(script, workspace)
            _save_json(episode, metadata_path)
            log.info(
                "episode_complete",
                duration_sec=episode.duration_sec,
                file_path=episode.file_path,
            )

        log.info("pipeline_complete", date=date, episode_file=episode.file_path)
        return episode



def main():
    import argparse
    import yaml

    parser = argparse.ArgumentParser(description="Run NewsFlow pipeline")
    parser.add_argument("--date", help="Date in YYYY-MM-DD format (default: today)")
    parser.add_argument("--skip-email", action="store_true", help="Skip email delivery step")
    args = parser.parse_args()

    episode = NewsFlowPipeline().run(date=args.date)
    print(f"Episode saved to: {episode.file_path} ({episode.duration_sec // 60} min)")

    if args.skip_email:
        return

    run_date = args.date or datetime.now().strftime("%Y-%m-%d")

    prefs_path = Path(__file__).parent.parent / "config" / "preferences.yaml"
    with open(prefs_path) as f:
        prefs = yaml.safe_load(f)
    delivery_cfg = prefs.get("delivery", {})
    recipient = delivery_cfg.get("recipient_email")
    if not recipient:
        log.warning("email_skipped", reason="delivery.recipient_email not set in preferences.yaml")
        return

    workspace = Path(__file__).parent.parent / "workspace" / run_date
    metadata_path = workspace / "episode_metadata.json"
    episode_metadata: dict = {}
    if metadata_path.exists():
        with open(metadata_path) as f:
            episode_metadata = json.load(f)

    from orchestrator import run_review
    review_path: Path | None = None
    try:
        review_path = run_review.generate(run_date)
    except Exception as exc:
        log.warning("review_report_failed", error=str(exc))

    from delivery.drive_uploader import upload_episode
    drive_link: str | None = None
    try:
        drive_link = upload_episode(Path(episode.file_path), run_date)
    except Exception as exc:
        log.warning("drive_upload_failed", error=str(exc))

    from delivery.email_sender import send_episode_email
    try:
        send_episode_email(
            recipient=recipient,
            mp3_path=Path(episode.file_path),
            review_md_path=review_path,
            episode_metadata=episode_metadata,
            drive_link=drive_link,
        )
    except Exception as exc:
        log.warning("email_failed", recipient=recipient, error=str(exc))


if __name__ == "__main__":
    main()
