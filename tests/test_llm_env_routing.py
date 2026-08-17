from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

import llm_from_here.llm_env as le


@pytest.fixture(autouse=True)
def _clear_routing():
    le.set_model_routing({})
    yield
    le.set_model_routing({})


def test_get_filter_model_default():
    assert le.get_filter_model() == "openrouter:openai/gpt-4o-mini"


def test_get_prose_model_env_override(monkeypatch):
    monkeypatch.setenv("LLMFH_PROSE_MODEL", "anthropic:claude-sonnet-4-20250514")
    assert le.get_prose_model() == "anthropic:claude-sonnet-4-20250514"


def test_set_model_routing_from_yaml_dict():
    le.set_model_routing(
        {
            "prose_model": "openrouter:openai/gpt-4o",
            "structured_model": "openrouter:openai/gpt-4o-mini",
        }
    )
    assert le.get_prose_model() == "openrouter:openai/gpt-4o"
    assert le.get_structured_model() == "openrouter:openai/gpt-4o-mini"


def test_check_ollama_available_returns_false_on_error():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("refused")
        assert le.check_ollama_available() is False


def test_deepseek_via_openrouter_defaults_to_tool_structured_output():
    # deepseek does not support pydantic-ai native structured output over OpenRouter.
    assert (
        le.get_structured_output_mode(
            "openrouter:deepseek/deepseek-v4-flash"
        )
        == "tool"
    )
    assert (
        le.get_structured_output_mode("google/gemini-2.5-flash") == "native"
    )
