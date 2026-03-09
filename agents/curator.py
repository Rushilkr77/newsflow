"""
Agent 2: Curator
Deduplicates articles, classifies priority/category via local LLM (qwen2.5:3b),
enforces time budget, returns curated list ready for summarization.

Model: qwen2.5:3b (via CURATOR_LOCAL_MODEL env var) — best 3B model for
structured JSON output. Falls back to LOCAL_LLM_MODEL if not set.
"""
import json
import os
import uuid
from urllib.parse import urlparse, urlunparse

import structlog
import yaml

from models.article import CuratedArticle, RawArticle
from models.enums import Category, Priority
from utils.llm_client import chat

log = structlog.get_logger(__name__)

# Source priority for dedup merge — lower index = higher priority
_SOURCE_PRIORITY: list[str] = [
    "harper_carroll",
    "et_ai",
    "ettech",
    "techcrunch",
    "tldr_ai",
    "tldr_tech",
    "tldr_dev",
    "custom",
]

_PREFS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "preferences.yaml")

# Model for classification (best small model for JSON output)
_CURATOR_LOCAL_MODEL = os.getenv("CURATOR_LOCAL_MODEL")


class CuratorAgent:
    def __init__(self):
        self._prefs = self._load_prefs()

    def run(self, raw_articles: list[RawArticle]) -> list[CuratedArticle]:
        log.info("curator_start", input_count=len(raw_articles))

        deduped = self._url_dedup(raw_articles)
        log.info("url_dedup_complete", count=len(deduped))

        curated = self._classify(deduped)
        log.info("classification_complete", count=len(curated))

        final = self._apply_time_budget(curated)
        log.info("time_budget_applied", final_count=len(final))

        return final

    # -------------------------------------------------------------------------
    # Deduplication
    # -------------------------------------------------------------------------

    def _url_dedup(self, articles: list[RawArticle]) -> list[dict]:
        """
        Group articles by normalized URL. Keep the article from the highest-priority
        source and record all sources that covered the story.
        """
        groups: dict[str, list[RawArticle]] = {}
        for article in articles:
            key = self._normalize_url(str(article.url))
            groups.setdefault(key, []).append(article)

        deduped = []
        for url_key, group in groups.items():
            best = min(group, key=lambda a: self._source_rank(a.source.value))
            all_sources = list({a.source for a in group})
            deduped.append(
                {
                    "article": best,
                    "all_sources": all_sources,
                    "dedup_group_id": str(uuid.uuid4()) if len(group) > 1 else None,
                }
            )

        return deduped

    def _normalize_url(self, url: str) -> str:
        """Strip utm params, trailing slash, www prefix for comparison."""
        from urllib.parse import parse_qs, urlencode

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        clean_params = {k: v for k, v in params.items() if not k.startswith("utm_")}
        clean_query = urlencode(clean_params, doseq=True)
        hostname = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path.rstrip("/")
        return urlunparse(parsed._replace(netloc=hostname, path=path, query=clean_query))

    def _source_rank(self, source_id: str) -> int:
        try:
            return _SOURCE_PRIORITY.index(source_id)
        except ValueError:
            return len(_SOURCE_PRIORITY)

    # -------------------------------------------------------------------------
    # LLM Classification
    # -------------------------------------------------------------------------

    def _classify(self, deduped: list[dict]) -> list[CuratedArticle]:
        """Classify articles in batches of 8 using qwen2.5:3b."""
        results: list[CuratedArticle] = []
        batch_size = 8

        for i in range(0, len(deduped), batch_size):
            batch = deduped[i : i + batch_size]
            try:
                classified = self._classify_batch(batch)
                results.extend(classified)
            except Exception as e:
                log.error("classification_batch_failed", batch_start=i, error=str(e))
                for item in batch:
                    results.append(self._fallback_curated(item))

        return results

    def _classify_batch(self, batch: list[dict]) -> list[CuratedArticle]:
        articles_for_prompt = []
        for idx, item in enumerate(batch):
            a = item["article"]
            articles_for_prompt.append(
                {
                    "index": idx,
                    "title": a.title,
                    "source": a.source.value,
                    "snippet": a.snippet[:500],
                }
            )

        system_prompt = self._build_system_prompt()
        user_prompt = f"""Classify each article below. Return a JSON array with one object per article, in the same order.

Articles:
{json.dumps(articles_for_prompt, indent=2)}

Return ONLY a JSON array (no markdown, no explanation):
[
  {{
    "index": 0,
    "priority": "P0" | "P1" | "P2" | "P3",
    "category": "big_tech_launches" | "ai_products_tools" | "product_innovations" | "india_startups" | "funding_ma" | "industry_strategy" | "engineering_tech" | "policy_safety",
    "relevance_score": 0-100,
    "discussion_hooks": ["one insight for AI PM or developer interview at a Series B+ startup"],
    "estimated_podcast_seconds": 30-420
  }},
  ...
]"""

        raw_json = chat(
            model_hint="claude-haiku-4-5",
            system=system_prompt,
            user=user_prompt,
            max_tokens=2048,
            local_model_override=_CURATOR_LOCAL_MODEL,
        )

        # Strip markdown fences if model wraps response
        raw_json = raw_json.strip()
        if raw_json.startswith("```"):
            raw_json = raw_json.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        classifications = json.loads(raw_json)

        curated_articles = []
        for item_data in classifications:
            idx = item_data["index"]
            item = batch[idx]
            a = item["article"]

            try:
                priority = Priority(item_data["priority"])
                category = Category(item_data["category"])
            except ValueError:
                priority = Priority.P2
                category = Category.ENGINEERING_TECH

            curated_articles.append(
                CuratedArticle(
                    id=a.id,
                    title=a.title,
                    url=a.url,
                    source=a.source,
                    all_sources=item["all_sources"],
                    priority=priority,
                    relevance_score=float(item_data.get("relevance_score", 50)),
                    category=category,
                    dedup_group_id=item.get("dedup_group_id"),
                    estimated_podcast_duration_sec=int(
                        item_data.get("estimated_podcast_seconds", 120)
                    ),
                    snippet=a.snippet,
                    discussion_hooks=item_data.get("discussion_hooks", []),
                )
            )

        return curated_articles

    def _build_system_prompt(self) -> str:
        p = self._prefs
        rules = p.get("priority_rules", {})

        p0 = "\n".join(f"  - {r}" for r in rules.get("P0_must_include", []))
        p1 = "\n".join(f"  - {r}" for r in rules.get("P1_high", []))
        p2 = "\n".join(f"  - {r}" for r in rules.get("P2_if_space", []))
        p3 = "\n".join(f"  - {r}" for r in rules.get("P3_skip", []))

        return f"""You are a content classifier for a daily AI/tech news podcast.
The listener is a {p['user_profile']['role']}.

Priority rules:
P0 — Must include (deep dive, 5-7 min):
{p0}

P1 — High priority (standard, 2-3 min):
{p1}

P2 — Quick hit (30-60 sec, no scraping needed):
{p2}

P3 — Skip entirely:
{p3}

Categories:
- big_tech_launches: Major launches or announcements from Meta, Apple, NVIDIA, Google, OpenAI, Anthropic, Microsoft — product OR model
- ai_products_tools: AI-powered products and tools from startups or big tech that change how software is built
- product_innovations: Non-AI products/hardware representing a real direction change (new form factor, platform, category)
- india_startups: Indian startup ecosystem — founders, product launches, local funding, policy
- funding_ma: Funding rounds, M&A, acquisitions, valuations
- industry_strategy: SaaS disruption, go-to-market moves, Series B+ company strategy
- engineering_tech: Technical deep dives, infra, open source (no product angle) — typically P2
- policy_safety: Regulations, AI safety, government policy, compliance — typically P2"""

    def _fallback_curated(self, item: dict) -> CuratedArticle:
        a = item["article"]
        return CuratedArticle(
            id=a.id,
            title=a.title,
            url=a.url,
            source=a.source,
            all_sources=item["all_sources"],
            priority=Priority.P2,
            relevance_score=40.0,
            category=Category.ENGINEERING_TECH,
            dedup_group_id=item.get("dedup_group_id"),
            estimated_podcast_duration_sec=60,
            snippet=a.snippet,
        )

    # -------------------------------------------------------------------------
    # Time Budget Enforcement
    # -------------------------------------------------------------------------

    def _apply_time_budget(self, articles: list[CuratedArticle]) -> list[CuratedArticle]:
        budget = self._prefs.get("time_budget", {})
        p0_max = budget.get("p0_deep_dive", {}).get("max_articles", 6)
        p0_max_sec = budget.get("p0_deep_dive", {}).get("total_max_min", 35) * 60
        p1_max_sec = budget.get("p1_standard", {}).get("total_max_min", 30) * 60
        p2_max_sec = budget.get("p2_quick_hit", {}).get("total_max_min", 12) * 60

        p0 = sorted(
            [a for a in articles if a.priority == Priority.P0],
            key=lambda a: a.relevance_score,
            reverse=True,
        )
        p1 = sorted(
            [a for a in articles if a.priority == Priority.P1],
            key=lambda a: a.relevance_score,
            reverse=True,
        )
        p2 = sorted(
            [a for a in articles if a.priority == Priority.P2],
            key=lambda a: a.relevance_score,
            reverse=True,
        )

        selected: list[CuratedArticle] = []

        p0_sec = 0
        for a in p0[:p0_max]:
            if p0_sec + a.estimated_podcast_duration_sec <= p0_max_sec:
                selected.append(a)
                p0_sec += a.estimated_podcast_duration_sec

        p1_sec = 0
        for a in p1:
            if p1_sec + a.estimated_podcast_duration_sec <= p1_max_sec:
                selected.append(a)
                p1_sec += a.estimated_podcast_duration_sec

        p2_sec = 0
        for a in p2:
            if p2_sec + a.estimated_podcast_duration_sec <= p2_max_sec:
                selected.append(a)
                p2_sec += a.estimated_podcast_duration_sec

        return selected

    def _load_prefs(self) -> dict:
        with open(_PREFS_PATH, "r") as f:
            return yaml.safe_load(f)
