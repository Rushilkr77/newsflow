"""
Phase A: GlobalEnrichPipeline

Runs once per day before any per-user (Phase B) runs.
Reads from the single shared ingestion inbox (file-token, no per-user Gmail access).

Steps:
  1. Compute union of source_ids wanted by any active user (from Supabase user_sources).
  2. Ingest from the shared inbox (IngestionAgent, file-token path, source allowlist = union).
  3. Global dedup: url-dedup → semantic-dedup → cross-source overlap (CuratorAgent.run_dedup).
  4. Scrape full article text for all deduped articles (ScraperAgent).
  5. Write shared pool to workspace/_shared/<date>/pool.json (atomic).

Entry point: python3 -m orchestrator.pipeline --phase global [--date YYYY-MM-DD]
"""

import json
import os
from datetime import datetime
from pathlib import Path

import structlog
from supabase import create_client

from agents.curator import CuratorAgent
from agents.ingestion import IngestionAgent
from agents.scraper_agent import ScraperAgent
from models.article import RawArticle
from orchestrator.pool import is_fresh, pool_path, save_pool
from orchestrator.user_sources import union_source_ids

log = structlog.get_logger(__name__)


def _save_json(items, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump([i.model_dump(mode="json") if hasattr(i, "model_dump") else i for i in items], f, default=str)


def _load_supabase():
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("Supabase env vars missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
    return create_client(url, key)


class GlobalEnrichPipeline:
    """
    Phase A: ingest + dedup + scrape → shared daily pool.
    Does NOT touch any user workspace or send any emails.
    """

    def run(self, date: str | None = None) -> str:
        """
        Run Phase A. Returns the path to the pool.json written.
        Raises on failure (daily_run.sh marks the run as failed if this raises).
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        shared_dir = os.path.join("workspace", "_shared", date)
        Path(shared_dir).mkdir(parents=True, exist_ok=True)

        log.info("global_phase_start", date=date, shared_dir=shared_dir)

        # Guard: if pool already fresh, skip (idempotent across 10-min launchd ticks)
        if is_fresh(date):
            log.info("global_phase_skipped", reason="pool_already_fresh", date=date)
            return pool_path(date)

        # ── Step 1: union of source_ids ──────────────────────────────────────
        db = _load_supabase()
        source_union = union_source_ids(db)
        if not source_union:
            log.warning("global_phase_no_active_users", date=date)
            # Write an empty pool so Phase B can detect this and mark episodes as empty_inbox
            return save_pool(date, [], source_ids_in_union=set())

        log.info("union_sources", count=len(source_union), ids=sorted(source_union))

        # ── Step 2: Ingestion (file-token, shared inbox) ─────────────────────
        raw_path = os.path.join(shared_dir, "raw_articles.json")
        if Path(raw_path).exists():
            log.info("checkpoint_found", stage="ingestion")
            with open(raw_path) as f:
                raw_articles = [RawArticle.model_validate(a) for a in json.load(f)]
        else:
            # IngestionAgent with no user_id → always uses file-token (shared inbox)
            # allowed_source_ids restricts the query to sources the union actually wants
            raw_articles = IngestionAgent(allowed_source_ids=source_union).run(date=date)
            _save_json(raw_articles, raw_path)
            log.info("ingestion_complete", count=len(raw_articles))

        if not raw_articles:
            log.warning("global_phase_empty_inbox", date=date)
            return save_pool(date, [], source_ids_in_union=source_union)

        # ── Step 3: Global dedup ─────────────────────────────────────────────
        dedup_path = os.path.join(shared_dir, "pool_deduped.json")
        if Path(dedup_path).exists():
            log.info("checkpoint_found", stage="dedup")
            with open(dedup_path) as f:
                deduped: list[dict] = json.load(f)
        else:
            curator = CuratorAgent()  # no user_bio for global phase
            deduped = curator.run_dedup(raw_articles)
            # Serialise: pool element dicts with RawArticle as sub-dict
            deduped_serialisable = [
                {
                    "article": elem["article"].model_dump(mode="json"),
                    "all_sources": [s.value if hasattr(s, "value") else s for s in elem["all_sources"]],
                    "dedup_group_id": elem.get("dedup_group_id"),
                    "context_only": elem.get("context_only", False),
                    "variants": elem.get("variants", []),
                }
                for elem in deduped
            ]
            with open(dedup_path, "w") as f:
                json.dump(deduped_serialisable, f, default=str)
            log.info("dedup_complete", count=len(deduped))

        # Deserialise for scraping (need actual RawArticle objects for in-place full_text)
        if deduped and isinstance(deduped[0].get("article"), dict):
            raw_articles_for_scrape = [RawArticle.model_validate(elem["article"]) for elem in deduped]
        else:
            # Already RawArticle objects (in-memory path)
            raw_articles_for_scrape = [elem["article"] for elem in deduped]

        # ── Step 4: Scrape full article text ─────────────────────────────────
        scraper = ScraperAgent()
        scraper.run(raw_articles_for_scrape)
        log.info("scrape_complete",
                 total=len(raw_articles_for_scrape),
                 with_text=sum(1 for a in raw_articles_for_scrape if a.full_text))

        # ── Step 5: Assemble and save pool ───────────────────────────────────
        # Re-serialise pool elements with scraped full_text
        pool_articles = [
            {
                "article": raw_articles_for_scrape[i].model_dump(mode="json"),
                "all_sources": deduped[i]["all_sources"]
                    if isinstance(deduped[i]["all_sources"][0], str)
                    else [s.value for s in deduped[i]["all_sources"]],
                "dedup_group_id": deduped[i].get("dedup_group_id"),
                "context_only": deduped[i].get("context_only", False),
                "variants": deduped[i].get("variants", []),
            }
            for i in range(len(deduped))
        ]

        pool_file = save_pool(date, pool_articles, source_ids_in_union=source_union)
        log.info("global_phase_complete", date=date, pool_articles=len(pool_articles), pool_file=pool_file)
        return pool_file
