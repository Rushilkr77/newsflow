"""
Shared article pool for the two-phase shared-enrich pipeline.

Phase A (GlobalEnrichPipeline) writes workspace/_shared/<date>/pool.json once per day.
Phase B (NewsFlowPipeline, per-user) reads and filters it before curate/summarize/etc.

Pool element format (pre-classification — no per-user fields):
  {
    "article":        dict,        # RawArticle.model_dump(mode="json") with full_text populated
    "all_sources":    list[str],   # Source enum values (all sources that covered this story)
    "dedup_group_id": str | None,
    "context_only":   bool,
    "variants":       list[dict],  # [{source, title, url}] duplicates folded into this story (may be absent in old pools)
  }

Pool envelope:
  {
    "date":                 "YYYY-MM-DD",
    "built_at":             ISO-8601 UTC,
    "source_ids_in_union":  list[str],   # Source values ingested in Phase A
    "articles":             list[dict],  # pool elements above
  }
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import structlog
from models.article import RawArticle

log = structlog.get_logger(__name__)

_SHARED_WORKSPACE = os.path.join("workspace", "_shared")


class Pool(TypedDict):
    date: str
    built_at: str
    source_ids_in_union: list[str]
    articles: list[dict]


def pool_dir(date: str) -> str:
    return os.path.join(_SHARED_WORKSPACE, date)


def pool_path(date: str) -> str:
    return os.path.join(pool_dir(date), "pool.json")


def is_fresh(date: str) -> bool:
    """True if pool.json exists for the given date and its date field matches."""
    p = pool_path(date)
    if not Path(p).exists():
        return False
    try:
        with open(p) as f:
            data = json.load(f)
        return data.get("date") == date
    except Exception:
        return False


def pool_source_ids(date: str) -> set[str]:
    """Return the set of source_ids that were ingested in the pool for this date."""
    p = pool_path(date)
    if not Path(p).exists():
        return set()
    try:
        with open(p) as f:
            data = json.load(f)
        return set(data.get("source_ids_in_union", []))
    except Exception:
        return set()


def save_pool(date: str, pool_articles: list[dict], source_ids_in_union: set[str]) -> str:
    """
    Write the pool to workspace/_shared/<date>/pool.json atomically.
    Uses temp-file + rename to avoid partial writes when concurrent ticks race.
    Returns the path written.
    """
    Path(pool_dir(date)).mkdir(parents=True, exist_ok=True)

    envelope: Pool = {
        "date": date,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_ids_in_union": sorted(source_ids_in_union),
        "articles": pool_articles,
    }

    target = pool_path(date)
    # Write to a temp file in the same dir, then atomic rename
    dir_ = pool_dir(date)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(envelope, f, default=str)
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    article_count = len(pool_articles)
    log.info("pool_saved", date=date, path=target, article_count=article_count,
             source_count=len(source_ids_in_union))
    return target


def load_pool(date: str) -> Pool | None:
    """
    Load the pool for a given date. Returns None if pool.json doesn't exist or is invalid.
    """
    p = pool_path(date)
    if not Path(p).exists():
        log.warning("pool_not_found", date=date, path=p)
        return None
    try:
        with open(p) as f:
            data: Pool = json.load(f)
        if data.get("date") != date:
            log.warning("pool_date_mismatch", expected=date, found=data.get("date"))
            return None
        log.info("pool_loaded", date=date, article_count=len(data.get("articles", [])),
                 source_ids=data.get("source_ids_in_union"))
        return data
    except Exception as exc:
        log.error("pool_load_failed", date=date, error=str(exc))
        return None


def pool_articles_to_raw(pool: Pool) -> list[tuple[dict, RawArticle]]:
    """
    Deserialise pool article dicts back into (pool_elem, RawArticle) pairs.
    The pool_elem carries all_sources / dedup_group_id / context_only;
    the RawArticle carries full_text and all article fields.
    """
    result = []
    for elem in pool.get("articles", []):
        try:
            raw = RawArticle.model_validate(elem["article"])
            result.append((elem, raw))
        except Exception as exc:
            log.warning("pool_article_deserialise_failed", error=str(exc))
    return result
