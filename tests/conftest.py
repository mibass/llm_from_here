"""Shared pytest fixtures for unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from llm_from_here.llm_session import LlmSession
from llm_from_here.models.guest_models import VideoResult


@pytest.fixture
def mock_llm_session(monkeypatch):
    """Avoid constructing a real pydantic-ai Agent where tests patch at call sites."""
    session = MagicMock(spec=LlmSession)
    monkeypatch.setattr("llm_from_here.llm_session.OpenRouterModel", MagicMock())
    monkeypatch.setattr("llm_from_here.llm_session.Agent", MagicMock())
    return session


@pytest.fixture
def sample_video_result():
    return VideoResult(
        video_id="abc123xyz",
        title="Live Performance",
        channel_title="NPR Music",
        description="A wholesome concert clip.",
        duration_seconds=420,
    )
