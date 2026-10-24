"""
Tests for post mode: dedup variants, apply_budget=False, and the brief writer's
no-signal-lost invariant. No LLM calls, no network.

Run: pytest tests/test_post_phase.py -v
"""
import sys
import types
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np

from agents.curator import CuratorAgent
from models.article import CuratedArticle, RawArticle
from models.enums import Category, Priority, Source
from orchestrator.post_phase import _load_tags, write_brief


def _raw(title: str, source: Source, url: str | None = None, snippet: str = "A snippet.", full_text=None) -> RawArticle:
    return RawArticle(
        id=str(uuid.uuid4()),
        title=title,
        url=url or f"https://example.com/{uuid.uuid4().hex}",
        source=source,
        sender_email="t@example.com",
        snippet=snippet,
        full_text=full_text,
        timestamp=datetime(2026, 10, 25, 5, 0, 0),
        newsletter_date="2026-10-25",
    )


def _dedup(articles: list[RawArticle], embs: np.ndarray) -> list[dict]:
    curator = CuratorAgent()
    model = MagicMock()
    model.encode.return_value = embs
    curator._embed_model = model
    fake_st = types.ModuleType("sentence_transformers")
    fake_st.SentenceTransformer = MagicMock()
    with patch.dict(sys.modules, {"sentence_transformers": fake_st}):
        return curator.run_dedup(articles)


def _pool(deduped: list[dict]) -> dict:
    return {"articles": [
        {
            "article": d["article"].model_dump(mode="json"),
            "all_sources": [s.value for s in d["all_sources"]],
            "dedup_group_id": d.get("dedup_group_id"),
            "context_only": d.get("context_only", False),
            "variants": d.get("variants", []),
        }
        for d in deduped
    ]}


def test_dedup_folds_semantic_and_url_duplicates_into_variants():
    a = _raw("OpenAI launches GPT-5 with 1M context", Source.TLDR_AI)
    b = _raw("OpenAI releases GPT-5 with huge context", Source.TECHCRUNCH)
    c = _raw("Kubernetes scheduling deep dive", Source.TLDR_DEV, url="https://example.com/k8s")
    c2 = _raw("Kubernetes scheduling deep dive", Source.TLDR, url="https://example.com/k8s")
    embs = np.array([[1, 0.05, 0], [1, 0.1, 0], [0, 0, 1], [0, 0, 1]], dtype=np.float32)

    result = _dedup([a, b, c, c2], embs)

    assert len(result) == 2
    gpt = next(r for r in result if "GPT-5" in r["article"].title)
    assert gpt["article"].source == Source.TECHCRUNCH
    assert [(v["source"], v["id"]) for v in gpt["variants"]] == [("tldr_ai", a.id)]
    k8s = next(r for r in result if "Kubernetes" in r["article"].title)
    assert len(k8s["variants"]) == 1  # URL-dedup sibling kept as variant


def test_run_rank_apply_budget_false_keeps_everything():
    curator = CuratorAgent()
    p3 = CuratedArticle(
        id="x", title="Minor thing happened", url="https://example.com/x", source=Source.TLDR,
        all_sources=[Source.TLDR], priority=Priority.P3, relevance_score=10,
        category=Category.ENGINEERING_TECH, estimated_podcast_duration_sec=30, snippet="s",
    )
    curator._classify = lambda deduped: [p3]
    curator._apply_time_budget = lambda curated: []

    assert curator.run_rank([], apply_budget=True) == []
    assert curator.run_rank([], apply_budget=False) == [p3]


def test_brief_loses_no_ingested_article(tmp_path):
    a = _raw("OpenAI launches GPT-5 with 1M context", Source.TLDR_AI)
    b = _raw("OpenAI releases GPT-5 with huge context", Source.TECHCRUNCH, full_text="Full body text.")
    solo = _raw("Startup X raises $50M Series B", Source.ETTECH)
    junk = _raw("COMPANY", Source.TLDR)
    old_pool_orphan = _raw("Merged away before variants existed", Source.TLDR_DEV)
    embs = np.array([[1, 0.05, 0], [1, 0.1, 0], [0, 0, 1], [0, 1, 0]], dtype=np.float32)

    deduped = _dedup([a, b, solo, junk], embs)
    raw = [r.model_dump(mode="json") for r in (a, b, solo, junk, old_pool_orphan)]

    path = write_brief(_pool(deduped), {}, raw, str(tmp_path), "2026-10-25", CuratorAgent())
    brief = open(path).read()

    for r in (a, b, solo, junk, old_pool_orphan):
        assert r.title in brief, f"lost: {r.title}"
    assert "(likely-non-article)" in brief and "(unaccounted)" in brief
    assert (tmp_path / "articles" / f"{b.id}.txt").read_text().endswith("Full body text.\n")


def _curated(id_: str, hooks: list[str]) -> CuratedArticle:
    return CuratedArticle(
        id=id_, title="T" * 12, url="https://example.com/t", source=Source.TLDR,
        all_sources=[Source.TLDR], priority=Priority.P2, relevance_score=40,
        category=Category.ENGINEERING_TECH, estimated_podcast_duration_sec=60, snippet="s",
        discussion_hooks=hooks,
    )


def test_fallback_tags_are_dropped_and_not_cached(tmp_path, monkeypatch):
    path = str(tmp_path / "tags.json")
    monkeypatch.setattr(CuratorAgent, "run_rank", lambda self, arts, apply_budget=True: [_curated("fb", [])])

    assert _load_tags({"articles": []}, path) == {}
    assert not (tmp_path / "tags.json").exists()  # all fallback -> retry next run

    monkeypatch.setattr(
        CuratorAgent, "run_rank",
        lambda self, arts, apply_budget=True: [_curated("fb", []), _curated("real", ["a hook"])],
    )
    assert list(_load_tags({"articles": []}, path)) == ["real"]
    assert (tmp_path / "tags.json").exists()


def test_brief_orders_by_source_coverage_and_sets_flags(tmp_path):
    popular = _raw("Anthropic ships new model", Source.TECHCRUNCH, full_text="body")
    popular_dup = _raw("Anthropic ships new model", Source.TLDR_AI, url=str(popular.url))
    funding = _raw("Startup X raises $50M Series B", Source.ETTECH)  # no full_text -> snippet-only
    embs = np.eye(3, dtype=np.float32)

    deduped = _dedup([funding, popular, popular_dup], embs)
    raw = [r.model_dump(mode="json") for r in (funding, popular, popular_dup)]
    path = write_brief(_pool(deduped), {}, raw, str(tmp_path), "2026-10-25", CuratorAgent())
    brief = open(path).read()

    assert brief.index("Anthropic ships new model") < brief.index("Startup X raises")
    funding_block = brief[brief.index("Startup X raises"):]
    assert "funding-signal" in funding_block and "snippet-only" in funding_block
    assert "| funding |" in funding_block
