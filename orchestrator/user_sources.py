"""
User-source resolution for the shared-enrich pipeline.

Provides:
  - SOURCE_ID_ALIASES: maps web/DB source_ids to pipeline Source enum values.
    The web app uses 'tldr_tech' for the base TLDR newsletter; the pipeline
    uses 'tldr'. Without this alias, every base-TLDR article is silently dropped.
  - union_source_ids(db):  set of all source_ids wanted by any active user today.
  - user_source_ids(db, user_id): set of source_ids for one user.
  - filter_pool_for_user(pool_articles, allowed_source_ids): filter pre-classification
    pool articles to those matching a user's allowed sources (checks all_sources, not
    just source, so merged cross-source stories reach the right users).
"""

import structlog
from models.enums import Source

log = structlog.get_logger(__name__)

# Maps web/DB user_sources.source_id → pipeline Source enum value.
# Only add entries that differ; anything already matching a Source.value needs none.
SOURCE_ID_ALIASES: dict[str, str] = {
    "tldr_tech": Source.TLDR.value,  # web uses 'tldr_tech'; pipeline enum is 'tldr'
}

# Inverse map: pipeline Source value → canonical web source_id (for reverse lookups)
_ALIAS_REVERSE: dict[str, str] = {v: k for k, v in SOURCE_ID_ALIASES.items()}

# All valid pipeline source values (excluding CUSTOM which is a runtime fallback)
_VALID_SOURCE_VALUES: frozenset[str] = frozenset(
    s.value for s in Source if s != Source.CUSTOM
)


def resolve_source_id(raw_id: str) -> str:
    """Map a web/DB source_id to the pipeline Source enum value, applying aliases."""
    return SOURCE_ID_ALIASES.get(raw_id, raw_id)


def validate_source_ids(source_ids: set[str]) -> set[str]:
    """
    Resolve + validate a set of source_ids from DB. Returns only those that map to
    known Source enum values. Logs a warning for any unrecognised ids.
    """
    resolved: set[str] = set()
    for sid in source_ids:
        mapped = resolve_source_id(sid)
        if mapped in _VALID_SOURCE_VALUES:
            resolved.add(mapped)
        else:
            log.warning("unknown_source_id", raw=sid, resolved=mapped)
    return resolved


def union_source_ids(db) -> set[str]:
    """
    Query the set of all source_ids that any active, episode-enabled user has enabled.
    Returns resolved pipeline Source values (alias-mapped, validated).

    Used by Phase A (GlobalEnrichPipeline) to build the Gmail query allowlist.
    """
    result = (
        db.table("user_sources")
        .select("source_id, users!inner(active, episode_generation_enabled)")
        .eq("enabled", True)
        .eq("users.active", True)
        .eq("users.episode_generation_enabled", True)
        .execute()
    )
    raw_ids: set[str] = {row["source_id"] for row in (result.data or [])}
    resolved = validate_source_ids(raw_ids)
    log.info("union_source_ids", raw_count=len(raw_ids), resolved_count=len(resolved), ids=sorted(resolved))
    return resolved


def user_source_ids(db, user_id: str) -> set[str]:
    """
    Query the source_ids enabled by a specific user.
    Returns resolved pipeline Source values (alias-mapped, validated).

    Used by Phase B (per-user filter) to select pool articles for this user.
    """
    result = (
        db.table("user_sources")
        .select("source_id")
        .eq("user_id", user_id)
        .eq("enabled", True)
        .execute()
    )
    raw_ids: set[str] = {row["source_id"] for row in (result.data or [])}
    resolved = validate_source_ids(raw_ids)
    log.info("user_source_ids", user_id=user_id, raw_count=len(raw_ids), resolved_count=len(resolved), ids=sorted(resolved))
    return resolved


def filter_pool_for_user(pool_articles: list[dict], allowed_source_ids: set[str]) -> list[dict]:
    """
    Filter pre-classification pool articles to those relevant for a user's source selection.

    Checks article['all_sources'] (list of Source enum values), NOT just article['source'],
    so a merged cross-source story (e.g. techcrunch + tldr_ai) reaches a user who
    subscribed to either contributing source.

    pool_articles: list of pool element dicts (each has 'article' RawArticle dict,
                   'all_sources': list[str], 'dedup_group_id', 'context_only').
    allowed_source_ids: resolved pipeline Source values for this user.
    """
    if not allowed_source_ids:
        log.warning("filter_pool_for_user_empty_allowed", hint="User has no enabled sources")
        return []

    filtered = []
    for elem in pool_articles:
        article_sources: list[str] = elem.get("all_sources", [])
        # Normalise: article may store Source enum values or raw strings
        article_source_values = {
            s.value if isinstance(s, Source) else str(s) for s in article_sources
        }
        if article_source_values & allowed_source_ids:
            filtered.append(elem)

    log.info(
        "pool_filtered_for_user",
        total_pool=len(pool_articles),
        allowed_sources=sorted(allowed_source_ids),
        filtered_count=len(filtered),
    )
    return filtered


def all_catalog_source_ids_from_config(senders_config: dict) -> set[str]:
    """
    Return the set of pipeline Source values for all entries in senders.yaml,
    regardless of enabled flag. Used to validate that the web catalog is in sync.
    """
    ids: set[str] = set()
    for sender in senders_config.get("senders", []):
        sid = sender.get("id")
        if sid and sid != "custom":
            ids.add(sid)
    return ids
