"""Structured outputs for the Adlib the News segment."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

from llm_from_here.schemas.story_outputs import (
    _APPLAUSE_PATTERN,
    _MUSIC_PROMPT_MAX_LEN,
    _MUSIC_PROMPT_MIN_LEN,
    _TITLE_LINE_RE,
)

_STORY_COUNT = 5
_INTRO_MIN_LEN = 40
_OUTRO_MIN_LEN = 20
_BODY_MIN_LEN = 280
_TOTAL_BODY_MIN_LEN = 2000
_STORY_PAUSE_MS = 800

_DICT_LIKE_RE = re.compile(r"[\{'\"]adlib_|original_headline|adlib_summary")
_EMOTION_TAG_RE = re.compile(
    r"^\[(?:neutral|positive|curiosity|amusement|laughs|enthusiasm|whispers)\]\s*",
    re.IGNORECASE,
)

_DEPRESSING_KEYWORDS = frozenset(
    {
        "death",
        "died",
        "killed",
        "murder",
        "mass shooting",
        "terrorist",
        "suicide",
        "funeral",
        "tragedy",
        "disaster",
        "earthquake",
        "wildfire",
        "famine",
        "genocide",
        "war crime",
        "casualties",
    }
)

_STORY_CATEGORIES = frozenset(
    {"world", "us", "science", "business", "sports", "culture", "odd"}
)


class NewsStoryItem(BaseModel):
    """One researched news story with replaceable token buckets."""

    category: str
    headline: str
    summary: str
    proper_nouns: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    adjectives: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)

    @field_validator(
        "category",
        "headline",
        "summary",
        "proper_nouns",
        "people",
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
    def _validate_story(self) -> NewsStoryItem:
        if not self.headline:
            raise ValueError("headline must not be empty")
        if not self.summary:
            raise ValueError("summary must not be empty")
        category = self.category.strip().lower()
        if category not in _STORY_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(_STORY_CATEGORIES)}")
        combined = f"{self.headline} {self.summary}".lower()
        for keyword in _DEPRESSING_KEYWORDS:
            if keyword in combined:
                raise ValueError(
                    f"story appears too grim for Adlib the News (matched {keyword!r})"
                )
        return self


class NewsResearchContext(BaseModel):
    """Five light current-news stories extracted from web research."""

    subject: str
    stories: list[NewsStoryItem]

    @field_validator("subject", mode="before")
    @classmethod
    def _strip_subject(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_context(self) -> NewsResearchContext:
        if not self.subject:
            raise ValueError("subject must not be empty")
        if len(self.stories) != _STORY_COUNT:
            raise ValueError(f"stories must contain exactly {_STORY_COUNT} items")
        categories = [story.category.strip().lower() for story in self.stories]
        if len(set(categories)) != len(categories):
            raise ValueError("stories must use five distinct categories")
        return self


class AdlibNewsStory(BaseModel):
    """One adlibbed news story: original headline preserved, body lightly scrambled."""

    headline: str
    adlib_body: str
    swapped_tokens: list[str] = Field(default_factory=list)

    @field_validator("headline", "adlib_body", "swapped_tokens", mode="before")
    @classmethod
    def _strip_strings(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, list):
            return [str(item).strip() for item in v if str(item).strip()]
        return v

    @model_validator(mode="after")
    def _validate_story(self) -> AdlibNewsStory:
        if not self.headline:
            raise ValueError("headline must not be empty")
        if len(self.adlib_body) < _BODY_MIN_LEN:
            raise ValueError(f"adlib_body must be at least {_BODY_MIN_LEN} characters")
        if _DICT_LIKE_RE.search(self.adlib_body):
            raise ValueError("adlib_body must be plain prose, not structured data")
        if len(self.swapped_tokens) < 2 or len(self.swapped_tokens) > 3:
            raise ValueError("swapped_tokens must contain 2 or 3 items")
        return self


class AdlibNewsBundle(BaseModel):
    """LLM-produced scrambled news bundle consumed by the performance prompt."""

    stories: list[AdlibNewsStory]

    @model_validator(mode="after")
    def _validate_bundle(self) -> AdlibNewsBundle:
        if len(self.stories) != _STORY_COUNT:
            raise ValueError(f"stories must contain exactly {_STORY_COUNT} items")
        return self


class NewsReadoutItem(BaseModel):
    """One newsdesk readout block with explicit transition and headline."""

    category: str
    transition_line: str
    headline: str
    body: str
    emotion_tag: str = ""
    reaction_line: str = ""

    @field_validator(
        "category",
        "transition_line",
        "headline",
        "body",
        "emotion_tag",
        "reaction_line",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_readout(self) -> NewsReadoutItem:
        if self.category.strip().lower() not in _STORY_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(_STORY_CATEGORIES)}")
        if not self.transition_line:
            raise ValueError("transition_line must not be empty")
        if not self.headline:
            raise ValueError("headline must not be empty")
        if len(self.body) < _BODY_MIN_LEN:
            raise ValueError(f"body must be at least {_BODY_MIN_LEN} characters")
        if _DICT_LIKE_RE.search(self.body) or _DICT_LIKE_RE.search(self.headline):
            raise ValueError("readout must be plain prose, not structured data")
        if _APPLAUSE_PATTERN.search(self.body) or _APPLAUSE_PATTERN.search(self.transition_line):
            raise ValueError("readout must not contain inline [APPLAUSE] cues")
        if self.emotion_tag and not _EMOTION_TAG_RE.match(self.emotion_tag):
            raise ValueError("emotion_tag must be a single bracketed Gemini tag")
        if self.reaction_line and _EMOTION_TAG_RE.search(self.reaction_line):
            raise ValueError("reaction_line must not include emotion tags")
        return self


class AdlibNewsScript(BaseModel):
    """Dris performance script for Adlib the News."""

    music_prompt: str
    intro_dialog: str
    stories: list[NewsReadoutItem]
    outro_dialog: str
    applause_duration_sec: int = Field(default=5, ge=3, le=6)

    @field_validator(
        "music_prompt",
        "intro_dialog",
        "outro_dialog",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_script(self) -> AdlibNewsScript:
        if len(self.music_prompt) < _MUSIC_PROMPT_MIN_LEN:
            raise ValueError(
                f"music_prompt must be at least {_MUSIC_PROMPT_MIN_LEN} characters"
            )
        if len(self.music_prompt) > _MUSIC_PROMPT_MAX_LEN:
            raise ValueError(
                f"music_prompt must be at most {_MUSIC_PROMPT_MAX_LEN} characters"
            )
        if len(self.intro_dialog) < _INTRO_MIN_LEN:
            raise ValueError(f"intro_dialog must be at least {_INTRO_MIN_LEN} characters")
        if len(self.outro_dialog) < _OUTRO_MIN_LEN:
            raise ValueError(f"outro_dialog must be at least {_OUTRO_MIN_LEN} characters")
        if len(self.stories) != _STORY_COUNT:
            raise ValueError(f"stories must contain exactly {_STORY_COUNT} items")
        total_len = sum(len(item.body) for item in self.stories)
        if total_len < _TOTAL_BODY_MIN_LEN:
            raise ValueError(
                f"stories total body length must be at least {_TOTAL_BODY_MIN_LEN} characters"
            )
        return self


def format_news_readout(item: NewsReadoutItem | dict) -> str:
    """Render one newsdesk readout as plain narrator prose."""
    if isinstance(item, dict):
        item = NewsReadoutItem.model_validate(item)
    parts: list[str] = []
    if item.emotion_tag:
        parts.append(item.emotion_tag)
    parts.append(item.transition_line)
    parts.append(item.headline + ".")
    parts.append(item.body)
    if item.reaction_line:
        parts.append(item.reaction_line)
    return " ".join(parts)


def adlib_news_to_segments(script: AdlibNewsScript | dict) -> list[dict]:
    """Map Adlib the News script to timeline-ready segments."""
    if isinstance(script, dict):
        script = AdlibNewsScript.model_validate(script)
    segments: list[dict] = [
        {"speaker": "background", "dialog": script.music_prompt},
        {
            "speaker": "character 1",
            "dialog": script.intro_dialog,
            "character_name": "narrator",
        },
    ]
    for index, story in enumerate(script.stories):
        segments.append(
            {
                "speaker": "character 1",
                "dialog": format_news_readout(story),
                "character_name": "narrator",
            }
        )
        if index < len(script.stories) - 1:
            segments.append(
                {
                    "speaker": "pause",
                    "dialog": f"[SILENCE duration {_STORY_PAUSE_MS}]",
                }
            )
    segments.append(
        {
            "speaker": "character 1",
            "dialog": script.outro_dialog,
            "character_name": "narrator",
        }
    )
    segments.append(
        {
            "speaker": "audience",
            "dialog": f"[APPLAUSE duration {script.applause_duration_sec}]",
        }
    )
    return segments
