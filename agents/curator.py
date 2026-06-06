"""
Agent 2: Curator
Deduplicates articles, classifies priority/category via local LLM (qwen2.5:3b),
enforces time budget, returns curated list ready for summarization.

Model: qwen2.5:3b (via CURATOR_LOCAL_MODEL env var) — best 3B model for
structured JSON output. Falls back to LOCAL_LLM_MODEL if not set.
"""
import json
import os
import re
import uuid
from urllib.parse import urlparse, urlunparse

import structlog
import yaml

from models.article import CuratedArticle, RawArticle
from models.enums import Category, Priority, Source
from utils.llm_client import chat

log = structlog.get_logger(__name__)

# Source priority for dedup merge — lower index = higher priority
_SOURCE_PRIORITY: list[str] = [
    "harper_carroll",
    "et_ai",
    "ettech",
    "techcrunch",
    "tldr_ai",
    "tldr",
    "tldr_dev",
    "tldr_devops",
    "tldr_fintech",
    "tldr_crypto",
    "custom",
]

_PREFS_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "preferences.yaml")

# Model for classification (best small model for JSON output)
_CURATOR_LOCAL_MODEL = os.getenv("CURATOR_LOCAL_MODEL")

_OPENROUTER_CURATOR_MODELS: list[str] = [
    m.strip()
    for m in os.getenv(
        "OPENROUTER_CURATOR_MODELS",
        "openai/gpt-oss-120b:free,nousresearch/hermes-3-llama-3.1-405b:free,meta-llama/llama-3.3-70b-instruct:free,google/gemma-4-31b-it:free",
    ).split(",")
    if m.strip()
]

# Funding/M&A signal patterns — used for post-classification override
_FUNDING_SIGNALS = re.compile(
    r'\$\d+(?:\.\d+)?[MBmb]\b'  # $38M, $1.5B, $100m
    r'|\bfunding\b'               # funding round
    r'|\bacquir(?:es?|ed|ing)\b'  # acquires, acquired, acquiring
    r'|\bacquisition\b'
    r'|\bmerger\b'
    r'|\bM&A\b'                   # re.IGNORECASE handles all case variants
    r'|\bIPO\b'
    r'|\bvaluation\b',
    re.IGNORECASE,
)


class CuratorAgent:
    def __init__(self):
        self._prefs = self._load_prefs()
        self._embed_model = None  # lazy-loaded on first semantic dedup call

    def run(self, raw_articles: list[RawArticle]) -> list[CuratedArticle]:
        log.info("curator_start", input_count=len(raw_articles))

        deduped = self._url_dedup(raw_articles)
        log.info("url_dedup_complete", count=len(deduped))

        # Semantic dedup: merge stories that are the same topic but have different URLs
        sem_deduped_articles = self._semantic_dedup([item["article"] for item in deduped])
        # Rebuild the deduped list, preserving all_sources/dedup_group_id for kept articles
        kept_ids = {a.id for a in sem_deduped_articles}
        deduped = [item for item in deduped if item["article"].id in kept_ids]

        deduped = self._mark_cross_source_overlap(deduped)

        curated = self._classify(deduped)
        log.info("classification_complete", count=len(curated))

        final = self._apply_time_budget(curated)
        log.info("time_budget_applied", final_count=len(final))

        return final

    # -------------------------------------------------------------------------
    # Cross-source overlap detection
    # -------------------------------------------------------------------------

    _TITLE_STOP_WORDS: frozenset = frozenset({
        "the", "a", "an", "in", "of", "to", "for", "on", "at", "by", "is", "are",
        "was", "be", "has", "had", "have", "with", "and", "or", "but", "its", "it",
        "this", "that", "new", "how", "why", "what", "who", "all", "more", "from",
    })

    def _title_keywords(self, title: str) -> frozenset:
        """Significant keywords from a title (lowercase, no stop words, len≥3)."""
        words = re.sub(r"[^a-z0-9\s]", "", title.lower()).split()
        return frozenset(w for w in words if len(w) >= 3 and w not in self._TITLE_STOP_WORDS)

    def _title_jaccard(self, kw_a: frozenset, kw_b: frozenset) -> float:
        if not kw_a or not kw_b:
            return 0.0
        return len(kw_a & kw_b) / len(kw_a | kw_b)

    def _mark_cross_source_overlap(self, deduped: list[dict]) -> list[dict]:
        """
        Flag HC articles as context_only when they cover the same story as any
        TLDR article in the same batch. TLDR is daily so always 'earlier' than
        HC's weekly issue — the HC version becomes editorial context, not news.

        Algorithm: Jaccard similarity on significant title keywords ≥ 0.30.
        Effect: priority is capped at P1 after LLM classification.
        """
        _HC = "harper_carroll"
        _TLDR_SOURCES = {"tldr_ai", "tldr", "tldr_dev"}

        # Pre-compute keyword sets for all TLDR articles in this batch
        tldr_kw_sets: list[frozenset] = [
            self._title_keywords(item["article"].title or "")
            for item in deduped
            if item["article"].source.value in _TLDR_SOURCES
        ]

        if not tldr_kw_sets:
            return deduped  # no TLDR articles to compare against

        _OVERLAP_THRESHOLD = 0.30

        for item in deduped:
            if item["article"].source.value != _HC:
                continue
            hc_kw = self._title_keywords(item["article"].title or "")
            best = max(
                (self._title_jaccard(hc_kw, tkw) for tkw in tldr_kw_sets),
                default=0.0,
            )
            if best >= _OVERLAP_THRESHOLD:
                item["context_only"] = True
                log.info(
                    "hc_context_only_flagged",
                    title=item["article"].title[:60],
                    jaccard=round(best, 2),
                )

        return deduped

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

    def _semantic_dedup(self, articles: list[RawArticle]) -> list[RawArticle]:
        """
        Remove near-duplicate articles that cover the same story but have different URLs.
        Uses sentence-transformers to embed titles and computes cosine similarity.
        Groups with similarity >= semantic_dedup_threshold are merged: the article from
        the highest-priority source is kept; ties broken by longer snippet.
        """
        if len(articles) <= 1:
            return articles

        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError:
            log.warning(
                "semantic_dedup_skipped",
                reason="sentence_transformers or numpy not installed",
            )
            return articles

        threshold: float = (
            self._prefs.get("dedup", {}).get("semantic_dedup_threshold", 0.82)
        )

        if not hasattr(self, "_embed_model") or self._embed_model is None:
            import torch
            _dev = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
            self._embed_model = SentenceTransformer("all-MiniLM-L6-v2", device=_dev)

        titles = [a.title for a in articles]
        raw_embs = self._embed_model.encode(titles, convert_to_numpy=True)

        # L2-normalise so dot product == cosine similarity
        norms = np.linalg.norm(raw_embs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)  # avoid divide-by-zero
        embs = raw_embs / norms

        sim_matrix = np.dot(embs, embs.T)

        n = len(articles)
        merged_into: dict[int, int] = {}  # idx -> representative idx

        for i in range(n):
            if i in merged_into:
                continue
            for j in range(i + 1, n):
                if j in merged_into:
                    continue
                if sim_matrix[i, j] >= threshold:
                    # Determine which to keep: higher source priority wins
                    rank_i = self._source_rank(articles[i].source.value)
                    rank_j = self._source_rank(articles[j].source.value)
                    if rank_i <= rank_j:
                        # keep i, drop j
                        merged_into[j] = i
                    else:
                        # keep j, drop i — but we need to re-root i's group to j
                        merged_into[i] = j
                        # also remap anything already merged into i
                        for k, v in list(merged_into.items()):
                            if v == i:
                                merged_into[k] = j

        # Build set of representative indices (those NOT dropped)
        dropped = set(merged_into.keys())
        representatives = [i for i in range(n) if i not in dropped]

        result = [articles[i] for i in representatives]

        log.info(
            "semantic_dedup_complete",
            before=len(articles),
            after=len(result),
            merged=len(articles) - len(result),
        )
        return result

    # -------------------------------------------------------------------------
    # LLM Classification
    # -------------------------------------------------------------------------

    def _is_garbage_title(self, title: str) -> bool:
        """
        Return True for titles that are clearly parsing artifacts, not real articles.
        - Too short (< 10 chars) — e.g. empty string, "AI", "Tech"
        - All-uppercase with no spaces — e.g. "COMPANY", "TLDRTECH" (placeholder text)
        """
        t = title.strip()
        if len(t) < 10:
            return True
        if t.isupper() and " " not in t:
            return True
        return False

    @staticmethod
    def _has_funding_signals(title: str, snippet: str) -> bool:
        """Check whether a title or snippet contains clear funding/M&A signals."""
        text = f"{title} {snippet[:200]}"
        return bool(_FUNDING_SIGNALS.search(text))

    # ET sources always belong in india_tech regardless of LLM classification
    _INDIA_SOURCES: frozenset[Source] = frozenset({Source.ETTECH, Source.ET_AI})

    def _apply_funding_override(self, articles: list[CuratedArticle]) -> None:
        """
        Post-classification funding/india routing override (in-place).

        Two rules applied in one pass:
        1. ET sources (ettech, et_ai) → always india_tech. The LLM often
           misroutes Indian company funding rounds to funding_ma or
           industry_strategy; source is a stronger signal than content.
        2. Non-ET articles with explicit funding/M&A signals → funding_ma,
           unless already correctly classified as india_tech or funding_ma.
        """
        for ca in articles:
            if ca.source in self._INDIA_SOURCES:
                if ca.category != Category.INDIA_TECH:
                    log.info(
                        "india_source_override",
                        title=ca.title[:60],
                        original_category=ca.category.value,
                    )
                    ca.category = Category.INDIA_TECH
            elif (
                ca.category != Category.FUNDING_MA
                and ca.category != Category.INDIA_TECH
                and self._has_funding_signals(ca.title, ca.snippet or "")
            ):
                log.info(
                    "funding_override",
                    title=ca.title[:60],
                    original_category=ca.category.value,
                    new_category="funding_ma",
                )
                ca.category = Category.FUNDING_MA

    def _classify(self, deduped: list[dict]) -> list[CuratedArticle]:
        """Classify articles in batches of 8 using qwen2.5:3b.

        On JSON parse failure, retries with progressively smaller batches (4→2→1)
        before falling back. This prevents an entire batch of TLDR AI or ET articles
        from being silently dropped due to one malformed LLM response.
        """
        results: list[CuratedArticle] = []
        batch_size = 8

        # Pre-filter garbage titles — skip LLM call entirely, auto-assign P3
        to_classify = []
        for item in deduped:
            title = item["article"].title or ""
            if self._is_garbage_title(title):
                log.info("title_prefilter_skip", title=repr(title))
                # Don't add to results — P3 articles are excluded downstream anyway
            else:
                to_classify.append(item)

        log.info(
            "title_prefilter_done",
            skipped=len(deduped) - len(to_classify),
            remaining=len(to_classify),
        )

        for i in range(0, len(to_classify), batch_size):
            batch = to_classify[i : i + batch_size]
            results.extend(self._classify_with_retry(batch, batch_start=i))

        self._apply_funding_override(results)
        return results

    def _classify_with_retry(self, batch: list[dict], batch_start: int) -> list[CuratedArticle]:
        """Try classifying a batch; on failure split in half and retry recursively.

        Retry schedule: 8 → 4 → 2 → 1 → fallback per article.
        This ensures every article gets at least one solo attempt before being
        assigned the generic fallback classification.
        """
        try:
            return self._classify_batch(batch)
        except Exception as e:
            if len(batch) == 1:
                # Single article still failed — use source-aware fallback
                log.warning(
                    "classification_single_failed",
                    batch_start=batch_start,
                    title=batch[0]["article"].title[:60],
                    error=str(e),
                )
                return [self._fallback_curated(batch[0])]

            # Split and retry each half
            log.warning(
                "classification_batch_failed",
                batch_start=batch_start,
                batch_size=len(batch),
                error=str(e),
                action=f"retrying_as_{len(batch)//2}+{len(batch)-len(batch)//2}",
            )
            mid = len(batch) // 2
            left = self._classify_with_retry(batch[:mid], batch_start=batch_start)
            right = self._classify_with_retry(batch[mid:], batch_start=batch_start + mid)
            return left + right

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
    "category": "big_tech_launches" | "ai_products_tools" | "product_innovations" | "india_tech" | "funding_ma" | "industry_strategy" | "engineering_tech" | "policy_safety",
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
            max_tokens=3072,  # bumped from 2048 — longer system prompt + 8 articles needs more room
            local_model_override=_CURATOR_LOCAL_MODEL,
            openrouter_models=_OPENROUTER_CURATOR_MODELS,
        )

        # Strip markdown fences if model wraps response
        raw_json = raw_json.strip()
        if raw_json.startswith("```"):
            raw_json = raw_json.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        # Try to parse; if it fails attempt lightweight JSON repair before raising
        try:
            classifications = json.loads(raw_json)
        except json.JSONDecodeError:
            classifications = json.loads(self._repair_json(raw_json))

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

            is_context_only = bool(item.get("context_only"))

            # Context-only HC articles (same story already in TLDR): cap at P1.
            # They provide editorial depth but aren't breaking news for this run.
            if is_context_only and priority == Priority.P0:
                log.info(
                    "hc_context_only_capped",
                    title=a.title[:60],
                    original_priority="P0",
                    capped_to="P1",
                )
                priority = Priority.P1

            relevance_score = float(item_data.get("relevance_score") or 50)
            if is_context_only:
                relevance_score = max(0.0, relevance_score - 15)
            # Boost ET sources to counteract empty-snippet classification uncertainty
            if a.source in (Source.ETTECH, Source.ET_AI):
                relevance_score = min(100.0, relevance_score + 10)

            curated_articles.append(
                CuratedArticle(
                    id=a.id,
                    title=a.title,
                    url=a.url,
                    source=a.source,
                    all_sources=item["all_sources"],
                    priority=priority,
                    relevance_score=relevance_score,
                    category=category,
                    dedup_group_id=item.get("dedup_group_id"),
                    estimated_podcast_duration_sec=int(
                        item_data.get("estimated_podcast_seconds") or 120
                    ),
                    snippet=a.snippet,
                    discussion_hooks=item_data.get("discussion_hooks", []),
                    context_only=is_context_only,
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

        emerging = p.get("emerging_ai_companies", [])
        emerging_str = ", ".join(emerging) if emerging else ""

        prompt = f"""You are a content classifier for a daily AI/tech news podcast.
The listener is a {p['user_profile']['role']}.

CLASSIFICATION RULE — Title first:
Classify primarily based on the TITLE. The snippet is supplementary context.
If the title mentions: a dollar amount ≥$50M, a product launch from a known AI company,
or a high-profile event (acquisition, exec poaching, major partnership) — treat it as
important EVEN IF the snippet is thin or vague. Use the snippet to confirm/refine, not override.

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
- big_tech_launches: Launches, announcements, OR leadership/org changes at Meta, Apple, NVIDIA, Google, OpenAI, Anthropic, Microsoft — product, model, acquisition, exec hire/departure, restructure. If the article is ABOUT one of these companies, use this category NOT industry_strategy.
- ai_products_tools: AI-powered products, tools, or systems with real-world impact — developer tools, agentic AI, AI applied to security/science/medicine/other domains
- product_innovations: Non-AI products/hardware representing a real direction change (new form factor, platform, category)
- india_tech: Indian tech ecosystem — companies founded/headquartered in India, India IT/BPO sector shifts, India fintech (UPI, neobanks, payments), Indian govt AI/digital policy; use for funding rounds, product launches, exits, notable hires, and founder profiles from the Indian ecosystem
- funding_ma: Funding rounds, M&A, acquisitions, valuations — for non-big-tech companies
- industry_strategy: SaaS disruption, go-to-market moves, Series B+ company strategy — for companies NOT in the big_tech_launches list above
- engineering_tech: Technical deep dives, infra, open source (no product angle) — typically P2
- policy_safety: Regulations, AI safety, government policy, compliance — typically P2"""

        if emerging_str:
            prompt += f"""

Rising AI-native companies (same importance tier as big tech for major events):
{emerging_str}
Headlines about these companies with large funding (≥$50M), product launches, or
strategic moves (acquisitions, exec poaching) are P0 — not P1 or P2."""

        return prompt

    # Mandatory sources that should always survive the time budget even on fallback
    _MANDATORY_SOURCES = frozenset({
        Source.TLDR_AI, Source.ET_AI, Source.ETTECH,
    })

    def _fallback_curated(self, item: dict) -> CuratedArticle:
        """Fallback when LLM classification fails even for a single article.

        Mandatory sources (tldr_ai, et_ai, ettech) get score=65 so they survive
        time budget cuts over random P2 articles with score=40-50.
        """
        a = item["article"]
        is_mandatory = a.source in self._MANDATORY_SOURCES
        score = 65.0 if is_mandatory else 40.0
        log.debug(
            "classification_fallback",
            source=a.source.value,
            title=a.title[:60],
            score=score,
        )
        return CuratedArticle(
            id=a.id,
            title=a.title,
            url=a.url,
            source=a.source,
            all_sources=item["all_sources"],
            priority=Priority.P2,
            relevance_score=score,
            category=Category.AI_PRODUCTS_TOOLS if is_mandatory else Category.ENGINEERING_TECH,
            dedup_group_id=item.get("dedup_group_id"),
            estimated_podcast_duration_sec=60,
            snippet=a.snippet,
        )

    @staticmethod
    def _repair_json(raw: str) -> str:
        """Lightweight JSON repair for common qwen2.5:3b output errors.

        Handles:
        1. Missing commas between object fields (Expecting ',' delimiter)
        2. Trailing commas before ] or }
        3. Unquoted None/null values for numeric fields
        """
        # Replace Python None with JSON null
        repaired = re.sub(r':\s*None\b', ': null', raw)
        # Fix missing comma between } and { in arrays (e.g. }\n  {)
        repaired = re.sub(r'}\s*\n(\s*{)', r'},\n\1', repaired)
        # Fix missing comma between a closing quote/number and the next key
        repaired = re.sub(r'("|\d)\s*\n(\s*")', r'\1,\n\2', repaired)
        # Remove trailing commas before ] or }
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
        return repaired

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
