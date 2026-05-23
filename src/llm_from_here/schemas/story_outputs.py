"""Structured outputs for story and outro segments."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

_MUSIC_PROMPT_MIN_LEN = 40
_MUSIC_PROMPT_MAX_LEN = 450
_STORY_MIN_PARAGRAPHS = 5
_TITLE_LINE_RE = re.compile(r"^\*\*.+\*\*\s*$")
_APPLAUSE_PATTERN = re.compile(r"\[APPLAUSE.*?\]", re.IGNORECASE)


class StoryScript(BaseModel):
    """First-person story with background music prompt and narrator paragraphs."""

    music_prompt: str
    paragraphs: list[str]
    applause_duration_sec: int = Field(default=5, ge=3, le=6)

    @field_validator("music_prompt", mode="before")
    @classmethod
    def _strip_music_prompt(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("paragraphs", mode="before")
    @classmethod
    def _strip_paragraphs(cls, v: object) -> object:
        if isinstance(v, list):
            return [str(p).strip() for p in v if str(p).strip()]
        return v

    @model_validator(mode="after")
    def _validate_story(self) -> StoryScript:
        if len(self.music_prompt) < _MUSIC_PROMPT_MIN_LEN:
            raise ValueError(
                f"music_prompt must be at least {_MUSIC_PROMPT_MIN_LEN} characters"
            )
        if len(self.music_prompt) > _MUSIC_PROMPT_MAX_LEN:
            raise ValueError(
                f"music_prompt must be at most {_MUSIC_PROMPT_MAX_LEN} characters"
            )
        if len(self.paragraphs) < _STORY_MIN_PARAGRAPHS:
            raise ValueError(
                f"paragraphs must contain at least {_STORY_MIN_PARAGRAPHS} items"
            )
        for paragraph in self.paragraphs:
            if _TITLE_LINE_RE.match(paragraph):
                raise ValueError("paragraphs must not be markdown title lines")
        return self


class OutroScript(BaseModel):
    """Outro monologue with background music prompt."""

    music_prompt: str
    dialog: str

    @field_validator("music_prompt", "dialog", mode="before")
    @classmethod
    def _strip_strings(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_outro(self) -> OutroScript:
        if len(self.music_prompt) < _MUSIC_PROMPT_MIN_LEN:
            raise ValueError(
                f"music_prompt must be at least {_MUSIC_PROMPT_MIN_LEN} characters"
            )
        if len(self.music_prompt) > _MUSIC_PROMPT_MAX_LEN:
            raise ValueError(
                f"music_prompt must be at most {_MUSIC_PROMPT_MAX_LEN} characters"
            )
        if not self.dialog:
            raise ValueError("dialog must not be empty")
        return self


def story_to_segments(story: StoryScript | dict) -> list[dict]:
    """Map validated story output to SegmentsToTimeline segment dicts."""
    if isinstance(story, dict):
        story = StoryScript.model_validate(story)
    segments: list[dict] = [
        {"speaker": "background", "dialog": story.music_prompt},
    ]
    for paragraph in story.paragraphs:
        segments.append(
            {
                "speaker": "character 1",
                "dialog": paragraph,
                "character_name": "narrator",
            }
        )
    segments.append(
        {
            "speaker": "audience",
            "dialog": f"[APPLAUSE duration {story.applause_duration_sec}]",
        }
    )
    return segments


def split_dialog_with_applause(
    dialog: str,
    *,
    character_number: int = 1,
    character_name: str = "narrator",
) -> list[dict]:
    """Split dialog on inline [APPLAUSE ...] cues into narrator + audience segments."""
    segments: list[dict] = []
    last = 0
    for match in _APPLAUSE_PATTERN.finditer(dialog):
        before = dialog[last : match.start()].strip()
        if before:
            segments.append(
                {
                    "speaker": f"character {character_number}",
                    "dialog": before,
                    "character_name": character_name,
                }
            )
        segments.append(
            {
                "speaker": "audience",
                "dialog": match.group(0),
            }
        )
        last = match.end()
    tail = dialog[last:].strip()
    if tail:
        segments.append(
            {
                "speaker": f"character {character_number}",
                "dialog": tail,
                "character_name": character_name,
            }
        )
    return segments


def outro_to_segments(outro: OutroScript | dict) -> list[dict]:
    """Map validated outro output to SegmentsToTimeline segment dicts."""
    if isinstance(outro, dict):
        outro = OutroScript.model_validate(outro)
    segments: list[dict] = [
        {"speaker": "background", "dialog": outro.music_prompt},
    ]
    segments.extend(split_dialog_with_applause(outro.dialog))
    return segments
