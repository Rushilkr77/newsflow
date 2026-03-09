"""
Pipeline Orchestrator
Runs the full NewsFlow pipeline sequentially with checkpoint/recovery support.
Each stage saves its output to workspace/{date}/ — re-run skips completed stages.
"""
import json
import os
from datetime import datetime
from pathlib import Path

import structlog

from agents.audio_producer import AudioProducerAgent
from agents.curator import CuratorAgent
from agents.ingestion import IngestionAgent
from agents.script_writer import ScriptWriterAgent
from agents.summarizer import SummarizerAgent
from models.article import ArticleSummary, CuratedArticle, RawArticle
from models.podcast import Episode, PodcastScript

log = structlog.get_logger(__name__)


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


class NewsFlowPipeline:
    def run(self, date: str | None = None) -> Episode:
        date = date or datetime.now().strftime("%Y-%m-%d")
        workspace = os.path.join("workspace", date)
        Path(workspace).mkdir(parents=True, exist_ok=True)

        log.info("pipeline_start", date=date, workspace=workspace)

        # ── Stage 1: Ingestion ───────────────────────────────────────────────
        raw_path = os.path.join(workspace, "raw_articles.json")
        if Path(raw_path).exists():
            log.info("checkpoint_found", stage="ingestion")
            raw_articles = _load_json(raw_path, RawArticle)
        else:
            raw_articles = IngestionAgent().run()
            _save_json(raw_articles, raw_path)
            log.info("ingestion_complete", count=len(raw_articles))

        # ── Stage 2: Curation ────────────────────────────────────────────────
        curated_path = os.path.join(workspace, "curated_articles.json")
        if Path(curated_path).exists():
            log.info("checkpoint_found", stage="curator")
            curated = _load_json(curated_path, CuratedArticle)
        else:
            curated = CuratorAgent().run(raw_articles)
            _save_json(curated, curated_path)
            log.info("curation_complete", count=len(curated))

        # ── Stage 3: Summarization (includes scraping P0/P1) ────────────────
        summaries_path = os.path.join(workspace, "summaries.json")
        enriched_path = os.path.join(workspace, "curated_articles_enriched.json")
        if Path(summaries_path).exists():
            log.info("checkpoint_found", stage="summarizer")
            summaries = _load_json(summaries_path, ArticleSummary)
        else:
            summarizer = SummarizerAgent()
            summaries = summarizer.run(curated)
            _save_json(curated, enriched_path)   # save enriched (with full_text) too
            _save_json(summaries, summaries_path)
            log.info("summarization_complete", count=len(summaries))

        # ── Stage 4: Script Writing ──────────────────────────────────────────
        script_path = os.path.join(workspace, "podcast_script.json")
        if Path(script_path).exists():
            log.info("checkpoint_found", stage="script_writer")
            script = _load_json(script_path, PodcastScript)
        else:
            script = ScriptWriterAgent().run(summaries, date)
            _save_json(script, script_path)
            log.info(
                "script_complete",
                segments=len(script.segments),
                duration_min=script.total_estimated_duration_min,
            )

        # ── Stage 5: Audio Production ────────────────────────────────────────
        metadata_path = os.path.join(workspace, "episode_metadata.json")
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
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run NewsFlow pipeline")
    parser.add_argument("--date", help="Date in YYYY-MM-DD format (default: today)")
    args = parser.parse_args()

    episode = NewsFlowPipeline().run(date=args.date)
    print(f"Episode saved to: {episode.file_path} ({episode.duration_sec // 60} min)")


if __name__ == "__main__":
    main()
