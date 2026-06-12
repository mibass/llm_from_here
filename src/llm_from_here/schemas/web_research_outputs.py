"""Structured outputs for YAML-configured web-research segments."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from llm_from_here.schemas.story_outputs import split_dialog_with_applause


class SourceCitation(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""


class WebResearchContext(BaseModel):
    """Generic research notes consumed by downstream dialog or transform prompts."""

    subject: str = ""
    summaries: list[str] = Field(default_factory=list)
    notes: str = ""
    entities: list[str] = Field(default_factory=list)
    proper_nouns: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    adjectives: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)

    @field_validator(
        "subject",
        "notes",
        "summaries",
        "entities",
        "proper_nouns",
        "places",
        "adjectives",
        "organizations",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return v

    @model_validator(mode="after")
    def _has_content(self) -> WebResearchContext:
        if not (
            self.subject
            or self.summaries
            or self.notes
            or self.entities
            or self.proper_nouns
            or self.places
            or self.adjectives
            or self.organizations
        ):
            raise ValueError("research context must include at least one non-empty field")
        return self


class ResearchedClipScript(BaseModel):
    """Host copy plus a YouTube search query for a researched clip segment."""

    subject: str
    intro_dialog: str
    story_dialog: str
    transition_dialog: str = ""
    youtube_search_query: str
    applause_duration_sec: int = Field(default=5, ge=3, le=6)

    @field_validator(
        "subject",
        "intro_dialog",
        "story_dialog",
        "transition_dialog",
        "youtube_search_query",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_dialog(self) -> ResearchedClipScript:
        if not self.intro_dialog:
            raise ValueError("intro_dialog must not be empty")
        if not self.story_dialog:
            raise ValueError("story_dialog must not be empty")
        if not self.youtube_search_query:
            raise ValueError("youtube_search_query must not be empty")
        return self


def researched_clip_to_segments(script: ResearchedClipScript | dict) -> list[dict]:
    """Map researched clip dialog to timeline-ready segment dicts."""
    if isinstance(script, dict):
        script = ResearchedClipScript.model_validate(script)
    segments: list[dict] = []
    for dialog in (script.intro_dialog, script.story_dialog, script.transition_dialog):
        if dialog:
            segments.extend(
                split_dialog_with_applause(
                    dialog,
                    character_number=1,
                    character_name="narrator",
                )
            )
    segments.append(
        {
            "speaker": "audience",
            "dialog": f"[APPLAUSE duration {script.applause_duration_sec}]",
        }
    )
    segments.append(
        {
            "speaker": "clip",
            "dialog": script.youtube_search_query,
            "subject": script.subject,
        }
    )
    return segments
