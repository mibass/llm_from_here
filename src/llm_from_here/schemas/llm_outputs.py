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
    "dris thile": "Dris Thile",
    "audience": "Audience",
}

# Legacy LLM/cached scripts may still say "Chris Thile"; normalize to Dris.
_SPEAKER_ALIASES = {
    "chris thile": "dris thile",
}

_MUSIC_CUE_RE = re.compile(r"^\[MUSIC .+\]$", re.IGNORECASE)
_APPLAUSE_CUE_RE = re.compile(r"^\[applause duration [0-9]+\]$", re.IGNORECASE)
_MUSIC_CUE_MAX_LEN = 500
_MUSIC_CUE_MIN_INNER_LEN = 40


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
        key = _SPEAKER_ALIASES.get(self.speaker.strip().lower(), self.speaker.strip().lower())
        if key not in _SPEAKER_CANON:
            raise ValueError(
                "speaker must be Music, Dris Thile, or Audience "
                f"(case-insensitive); got {self.speaker!r}"
            )
        dialog = self.dialog.strip()
        if key == "music":
            if not _MUSIC_CUE_RE.fullmatch(dialog):
                raise ValueError(
                    "Music dialog must be [MUSIC <full music generation prompt>]; "
                    f"got {self.dialog!r}"
                )
            inner = re.sub(r"^\[MUSIC\s*", "", dialog, flags=re.IGNORECASE).rstrip("]")
            if len(inner.strip()) < _MUSIC_CUE_MIN_INNER_LEN:
                raise ValueError(
                    "Music dialog prompt is too short; include duration, instruments, "
                    "mood, BPM, and instrumental-only instruction"
                )
            if len(dialog) > _MUSIC_CUE_MAX_LEN:
                raise ValueError(
                    f"Music dialog exceeds {_MUSIC_CUE_MAX_LEN} characters"
                )
        elif key == "audience":
            if not _APPLAUSE_CUE_RE.fullmatch(dialog):
                raise ValueError(
                    f"Audience dialog must be [APPLAUSE duration N]; got {self.dialog!r}"
                )
        elif not dialog:
            raise ValueError(f"dialog must not be empty for speaker {self.speaker!r}")
        object.__setattr__(self, "speaker", _SPEAKER_CANON[key])
        return self




class IntroScriptLines(BaseModel):
    """Object wrapper so pydantic-ai structured output gets a JSON-schema object root."""

    lines: list[IntroLine]


def intro_lines_to_longform_segments(
    lines: list[IntroLine] | list[dict],
) -> list[dict]:
    """Merge consecutive Dris Thile lines into blocks for gemini_longform_TTS."""
    segments: list[dict] = []
    narrator_parts: list[str] = []

    def flush_narrator() -> None:
        if narrator_parts:
            segments.append(
                {
                    "speaker": "dris thile",
                    "dialog": "\n\n".join(narrator_parts),
                }
            )
            narrator_parts.clear()

    for raw in lines:
        line = raw if isinstance(raw, IntroLine) else IntroLine.model_validate(raw)
        key = line.speaker.strip().lower()
        if key == "music":
            flush_narrator()
            segments.append({"speaker": "music", "dialog": line.dialog})
        elif key == "audience":
            flush_narrator()
            segments.append({"speaker": "audience", "dialog": line.dialog})
        elif key == "dris thile":
            narrator_parts.append(line.dialog)

    flush_narrator()
    return segments


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
