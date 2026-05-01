"""Structured output models for OpenRouter + pydantic-ai.

Schema inventory (YAML / caller):
- configs * json_script_prompt → IntroScriptLines.lines (intro.py, introFromGuestlist.py)
- configs * json_guest_prompt → GuestListJson.guests (intro.py)
- configs * llm_filter_js → LlmFilterResponse (ytfetch.py via includes/llm_filter_vars.yml)
"""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator, model_validator

# IntroLine / GuestEntry / LlmFilterResponse avoid Field(pattern="(?i)..."): OpenRouter/Azure
# structured-output rejects JSON Schema patterns with inline ignore-case flags.

_SPEAKER_CANON = {
    "music": "Music",
    "chris thile": "Chris Thile",
    "audience": "Audience",
}

_DIALOG_RE = re.compile(
    r"^(\[music [a-z\-]+\]|\[applause duration [0-9]+\]|.+)$",
    re.IGNORECASE,
)


class IntroLine(BaseModel):
    speaker: str
    dialog: str

    @field_validator("speaker", mode="before")
    @classmethod
    def _strip_speaker(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @field_validator("dialog", mode="before")
    @classmethod
    def _strip_dialog(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_intro_line(self) -> IntroLine:
        key = self.speaker.strip().lower()
        if key not in _SPEAKER_CANON:
            raise ValueError(
                "speaker must be Music, Chris Thile, or Audience "
                f"(case-insensitive); got {self.speaker!r}"
            )
        if not _DIALOG_RE.fullmatch(self.dialog):
            raise ValueError(f"dialog format invalid for intro line: {self.dialog!r}")
        object.__setattr__(self, "speaker", _SPEAKER_CANON[key])
        return self




class IntroScriptLines(BaseModel):
    """Object wrapper so pydantic-ai structured output gets a JSON-schema object root."""

    lines: list[IntroLine]


_GUEST_CATEGORIES = frozenset({"music", "comedy", "author", "actor", "improv"})


class GuestEntry(BaseModel):
    guest_category: str
    guest_name: str

    @field_validator("guest_category", "guest_name", mode="before")
    @classmethod
    def _strip_strings(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _normalize_category(self) -> GuestEntry:
        cat = self.guest_category.strip().lower()
        if cat not in _GUEST_CATEGORIES:
            raise ValueError(
                "guest_category must be one of Music, Comedy, Author, Actor, Improv "
                f"(case-insensitive); got {self.guest_category!r}"
            )
        object.__setattr__(self, "guest_category", cat.title())
        return self


class GuestListJson(BaseModel):
    guests: list[GuestEntry]


class LlmFilterResponse(BaseModel):
    answer: str

    @field_validator("answer", mode="before")
    @classmethod
    def _normalize_answer(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @model_validator(mode="after")
    def _validate_yes_no(self) -> LlmFilterResponse:
        if self.answer not in ("yes", "no"):
            raise ValueError(f"answer must be yes or no; got {self.answer!r}")
        return self
