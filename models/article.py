from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime
from typing import Optional
from .enums import Source, Priority, Category


class RawArticle(BaseModel):
    id: str = Field(description="UUID")
    title: str
    url: HttpUrl
    source: Source
    sender_email: str
    snippet: str = Field(description="Article summary from newsletter email")
    full_text: Optional[str] = Field(None, description="Full article if scraped")
    section: Optional[str] = Field(None, description="Section within newsletter, e.g. 'Headlines'")
    tags: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(description="Email send time")
    newsletter_date: str = Field(description="e.g. '2026-02-19'")
    read_more_url: Optional[HttpUrl] = Field(None, description="Actual article URL if different from url")
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class CuratedArticle(BaseModel):
    id: str
    title: str
    url: HttpUrl
    source: Source = Field(description="Best source if merged from multiple")
    all_sources: list[Source] = Field(description="All sources that covered this story")
    priority: Priority
    relevance_score: float = Field(ge=0.0, le=100.0)
    category: Category
    dedup_group_id: Optional[str] = Field(None, description="Groups merged duplicates")
    estimated_podcast_duration_sec: int
    snippet: str
    full_text: Optional[str] = None
    discussion_hooks: list[str] = Field(default_factory=list, description="Interview-ready insights")
    context_only: bool = Field(
        default=False,
        description=(
            "True when this HC story covers the same topic as a TLDR story from earlier "
            "this week — treated as editorial context rather than breaking news; "
            "priority capped at P1."
        ),
    )


class ArticleSummary(BaseModel):
    article_id: str
    title: str
    source: Source
    priority: Priority
    category: Category
    summary_text: str
    key_takeaways: list[str]
    discussion_points: list[str] = Field(description="For PM interview prep")
    related_article_ids: list[str] = Field(default_factory=list)
    word_count: int
