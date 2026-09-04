"""Structured outputs for ImprovAgent (scene setup, performer turns, SFX cues)."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CharacterSlotSetup(BaseModel):
    """One performer slot after setup (1-based slot index)."""

    slot: int = Field(..., ge=1, description="Matches speaker key character {slot}")
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)


class SceneSetup(BaseModel):
    """Director/judge output: full scene bible (no YAML scene specifics)."""

    characters: list[CharacterSlotSetup]
    setting: str = Field(..., min_length=1)
    scenario: str = Field(..., min_length=1)
    background_sound: str = Field(
        ...,
        min_length=1,
        description="Short Freesound search query for ambient bed",
    )
    sfx_palette: list[str] = Field(
        ...,
        min_length=1,
        description="3–5 recurring SFX types for this setting",
    )

    @field_validator("sfx_palette", mode="before")
    @classmethod
    def _strip_palette_strings(cls, v: object) -> object:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v


class ImprovTurn(BaseModel):
    """One performer turn: spoken line plus optional non-audio note and SFX cues."""

    dialog: str = Field(
        ...,
        min_length=1,
        description="Spoken words only. No speaker-name prefix, no bracketed cues.",
    )
    stage_direction: str = Field(
        default="",
        description="Optional short acting note; never spoken aloud.",
    )
    sfx_cues: list[str] = Field(
        default_factory=list,
        description=(
            "Zero to two concrete, audible sound-effect search queries "
            "(e.g. 'coffee machine steam', 'doorbell chime'). Not emotions or gestures."
        ),
    )

    @field_validator("sfx_cues", mode="before")
    @classmethod
    def _clean_cues(cls, v: object) -> object:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v


class ImprovSegment(BaseModel):
    """One timeline row compatible with SegmentsToTimeline segment list."""

    speaker: str
    dialog: str
    character_name: str | None = None
    sfx_search_query: str | None = None
    sfx_freesound_id: int | None = None


class ImprovSegments(BaseModel):
    """Wrapper for structured segment batches if needed."""

    segments: list[ImprovSegment]


class TurnJudgement(BaseModel):
    coherence: int = Field(..., ge=1, le=4)
    yes_and: int = Field(..., ge=1, le=4)
    character_consistency: int = Field(..., ge=1, le=4)
    pass_turn: bool
    end_scene: bool = False
    feedback: str = ""


class SfxJudgement(BaseModel):
    chosen_index: int = Field(..., ge=0)
    reasoning: str = ""
