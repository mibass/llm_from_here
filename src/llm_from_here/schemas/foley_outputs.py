"""Structured outputs for the SFX/foley agent (choose / refine / give up per attempt)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class FoleyStep(BaseModel):
    """One foley-loop decision: accept a listed candidate, refine the query, or give up."""

    accept: bool = Field(default=False, description="True when candidate_ref is the final pick")
    candidate_ref: str = Field(
        default="",
        description="Exact 'provider:id' of the accepted candidate, ONLY if accept is True",
    )
    refined_query: str = Field(
        default="",
        description="Sharper concrete search query for the next attempt, or empty to finish",
    )
    give_up: bool = Field(default=False, description="True to stop looking and report nothing")
    give_up_reason: str = Field(
        default="",
        description="Short reason for giving up (only meaningful when give_up is True)",
    )

    @field_validator("candidate_ref", "refined_query", "give_up_reason", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v