from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_from_here.models.guest_models import GuestSegment, VideoResult


def test_video_result_valid():
    v = VideoResult(
        video_id="x",
        title="t",
        channel_title="c",
        description="d",
        duration_seconds=100,
    )
    assert v.video_id == "x"


def test_guest_segment_missing_field():
    with pytest.raises(ValidationError):
        GuestSegment.model_validate(
            {"guest_name": "A", "intro_sentence": "Hi", "duration_seconds": 1}
        )


def test_guest_segment_negative_duration():
    with pytest.raises(ValidationError):
        GuestSegment(
            guest_name="A",
            video_id="vid",
            intro_sentence="Welcome.",
            duration_seconds=-1,
        )
