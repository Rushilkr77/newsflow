from pydantic import BaseModel, Field
from typing import Optional


class Segment(BaseModel):
    id: str
    title: str
    segment_type: str = Field(
        description="opener | ai_updates | funding | india_tech | product_strategy | quick_hits | closing"
    )
    content_ssml: str = Field(description="SSML-annotated script text")
    content_plain: str = Field(description="Plain text (for TTS that don't support SSML)")
    duration_estimate_sec: int
    source_article_ids: list[str] = Field(default_factory=list)


class PodcastScript(BaseModel):
    episode_number: int
    date: str
    total_estimated_duration_min: int
    segments: list[Segment]
    top_takeaways: list[str] = Field(description="3 discussion-ready points for closing")


class Episode(BaseModel):
    episode_number: int
    date: str
    duration_sec: int
    file_path: str
    file_size_bytes: int
    article_count: int
    sources_used: list[str]
