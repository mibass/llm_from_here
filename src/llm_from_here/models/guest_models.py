from __future__ import annotations

from pydantic import BaseModel, Field


class VideoResult(BaseModel):
    """Single candidate row returned by ``search_youtube``."""

    video_id: str
    title: str
    channel_title: str
    description: str
    duration_seconds: int = Field(ge=0)


class GuestSegment(BaseModel):
    """Structured agent output: chosen clip + host intro line."""

    guest_name: str
    video_id: str
    intro_sentence: str
    duration_seconds: int = Field(ge=0)
