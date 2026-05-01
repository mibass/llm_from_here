"""Structured output models for OpenRouter + pydantic-ai.

Schema inventory (YAML / caller):
- configs * json_script_prompt_js → IntroScriptLines (intro.py, introFromGuestlist.py)
- configs * json_guest_prompt_js → GuestListJson (intro.py)
- configs * llm_filter_js → LlmFilterResponse (ytfetch.py via includes/llm_filter_vars.yml)
"""

from __future__ import annotations

from pydantic import BaseModel, Field, RootModel, field_validator


class IntroLine(BaseModel):
    speaker: str = Field(pattern=r"^(?i)(music|chris thile|audience)$")
    dialog: str = Field(
        pattern=r"^(?i)(\[music [a-z\-]+\]|\[applause duration [0-9]+\]|.+)$"
    )


IntroScriptLines = RootModel[list[IntroLine]]


class GuestEntry(BaseModel):
    guest_category: str = Field(pattern=r"^(?i)(music|comedy|author|actor|improv)$")
    guest_name: str


GuestListJson = RootModel[list[GuestEntry]]


class LlmFilterResponse(BaseModel):
    answer: str = Field(pattern=r"^(?i)(yes|no)$")

    @field_validator("answer", mode="before")
    @classmethod
    def _normalize_answer(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v
