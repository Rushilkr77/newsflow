"""
Post mode: shared pool -> compact brief for the /newsflow-post Claude skill.

Reuses Phase A (ingest + dedup + scrape) and the curator classifier as *tags
only*. Nothing is filtered: every ingested article ends up in the brief as a
story, a folded variant, or a line in the appendix.

Writes workspace/post/<date>/:
  brief.md          one block per story (ordered by source coverage) + appendix
  articles/<id>.txt full text, untrimmed (snippet if the scrape failed)
  tags.json         classifier output (checkpoint; re-runs cost no LLM calls)

Entry point: python3 -m orchestrator.pipeline --mode post [--date YYYY-MM-DD]
"""

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import structlog

from agents.curator import CuratorAgent
from models.article import CuratedArticle
from models.enums import Category
from orchestrator.pool import is_fresh, load_pool, pool_dir

log = structlog.get_logger(__name__)

_LAUNCH = {Category.BIG_TECH_LAUNCHES, Category.AI_PRODUCTS_TOOLS, Category.PRODUCT_INNOVATIONS}
_LEAD_WORDS = 40


def _faction(tag: CuratedArticle | None, funding_signal: bool) -> str:
    if tag is None:
        return "funding" if funding_signal else "other"
    if tag.category == Category.FUNDING_MA:
        return "funding"
    return "launch" if tag.category in _LAUNCH else "other"


def _lead(text: str | None) -> str:
    words = (text or "").split()
    return " ".join(words[:_LEAD_WORDS]) + (" …" if len(words) > _LEAD_WORDS else "")


def _load_tags(pool: dict, path: str) -> dict[str, CuratedArticle]:
    """
    Real classifier tags by article id. Cached; classifier failure just means no tags.
    When the LLM fails, CuratorAgent._fallback_curated emits default tags (P2, score 40/65)
    that carry no discussion_hooks — those are guesses, so they are dropped, and a run with
    no real tags is not cached (tomorrow's run retries).
    """
    if Path(path).exists():
        with open(path) as f:
            return {t["id"]: CuratedArticle.model_validate(t) for t in json.load(f)}
    try:
        curated = CuratorAgent().run_rank(pool["articles"], apply_budget=False)
    except Exception as exc:
        log.warning("post_tagging_failed", error=str(exc))
        return {}
    real = [c for c in curated if c.discussion_hooks]
    log.info("post_tags", real=len(real), fallback=len(curated) - len(real))
    if real:
        with open(path, "w") as f:
            json.dump([c.model_dump(mode="json") for c in real], f, default=str)
    return {c.id: c for c in real}


def write_brief(
    pool: dict,
    tags: dict[str, CuratedArticle],
    raw: list[dict],
    out_dir: str,
    date: str,
    curator: CuratorAgent,
) -> str:
    """Write brief.md + articles/*.txt. Every id in `raw` is accounted for in the output."""
    articles_dir = os.path.join(out_dir, "articles")
    Path(articles_dir).mkdir(parents=True, exist_ok=True)

    stories: list[dict] = []
    appendix: list[tuple[str, str, str, str]] = []  # (source, title, url, reason)
    covered: set[str] = set()

    for elem in pool["articles"]:
        a = elem["article"]
        variants = elem.get("variants", [])
        covered.add(a["id"])
        covered.update(v["id"] for v in variants if "id" in v)

        if curator._is_garbage_title(a["title"] or ""):
            appendix.append((a["source"], a["title"], a["url"], "likely-non-article"))
            continue

        tag = tags.get(a["id"])
        funding = curator._has_funding_signals(a["title"], a["snippet"] or "")
        sources = sorted(set(elem.get("all_sources", [])) | {a["source"]} | {v["source"] for v in variants})
        flags = [
            f for f, on in (
                ("funding-signal", funding),
                ("context-only", elem.get("context_only", False)),
                ("snippet-only", not a.get("full_text")),
            ) if on
        ]
        stories.append({
            "a": a, "tag": tag, "variants": variants, "sources": sources, "flags": flags,
            "faction": _faction(tag, funding),
        })

    stories.sort(key=lambda s: (
        -len(s["sources"]),
        -(s["tag"].relevance_score if s["tag"] else 0),
        curator._source_rank(s["a"]["source"]),
    ))

    for r in raw:
        if r["id"] not in covered:
            appendix.append((r["source"], r["title"], r["url"], "unaccounted"))

    counts: dict[str, int] = {}
    for s in stories:
        counts[s["faction"]] = counts.get(s["faction"], 0) + 1
    folded = sum(len(s["variants"]) for s in stories)
    untagged = sum(1 for s in stories if s["tag"] is None)

    lines = [
        f"# Post brief — {date}",
        f"{len(stories)} stories ({' · '.join(f'{k} {v}' for k, v in sorted(counts.items()))}) · "
        f"{folded} duplicates folded · {len(appendix)} in appendix. Ordered by source coverage.",
        "Full text: articles/<id>.txt. Tags (faction/category/priority/rel) are classifier hints, override freely."
        + (f" {untagged} stories are untagged (classifier unavailable) — judge faction yourself." if untagged else ""),
        "",
    ]
    for n, s in enumerate(stories, 1):
        a, tag = s["a"], s["tag"]
        tag_str = f"{tag.category.value} | {tag.priority.value} | rel {tag.relevance_score:.0f}" if tag else "untagged"
        lines += [
            f"### {n}. {a['title']}",
            f"id: {a['id']} | {s['faction']} | {tag_str} | sources({len(s['sources'])}): {', '.join(s['sources'])}"
            + (f" | flags: {', '.join(s['flags'])}" if s["flags"] else ""),
            f"domain: {urlparse(a['url']).netloc}",  # full (often tracking) url is in the article file
            f"lead: {_lead(a['snippet'] or a.get('full_text'))}",
            *[f"also: {v['source']}: \"{v['title']}\"" for v in s["variants"]],
            "",
        ]
        body = a.get("full_text") or a["snippet"] or ""
        with open(os.path.join(articles_dir, f"{a['id']}.txt"), "w") as f:
            f.write(f"{a['title']}\n{a['url']}\nsources: {', '.join(s['sources'])}\n\n{body}\n")

    if appendix:
        lines += ["## Appendix (not in main list)", *[f"- [{src}] {t} <{urlparse(u).netloc}> ({why})" for src, t, u, why in appendix], ""]

    brief_path = os.path.join(out_dir, "brief.md")
    with open(brief_path, "w") as f:
        f.write("\n".join(lines))
    log.info("brief_written", path=brief_path, stories=len(stories), folded=folded, appendix=len(appendix))
    return brief_path


def run_post(date: str | None = None) -> str | None:
    """Build workspace/post/<date>/brief.md. Returns its path, or None if the pool is empty."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    if not is_fresh(date):
        from orchestrator.global_phase import GlobalEnrichPipeline
        GlobalEnrichPipeline().run(date)
    pool = load_pool(date)
    if not pool or not pool["articles"]:
        log.warning("post_pool_empty", date=date)
        return None

    out_dir = os.path.join("workspace", "post", date)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    raw_path = os.path.join(pool_dir(date), "raw_articles.json")
    raw = json.load(open(raw_path)) if Path(raw_path).exists() else []

    tags = _load_tags(pool, os.path.join(out_dir, "tags.json"))
    return write_brief(pool, tags, raw, out_dir, date, CuratorAgent())
