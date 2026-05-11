"""Live routing smoke tests for prose / filter models."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

import llm_from_here.llm_env as le
from llm_from_here.llm_session import LlmSession
from llm_from_here.schemas.llm_outputs import LlmFilterResponse

pytestmark = pytest.mark.integration

load_dotenv()


@pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY required"
)
def test_prose_model_generates_text(monkeypatch):
    monkeypatch.setenv("LLMFH_PROSE_MODEL", "openrouter:openai/gpt-4o-mini")
    le.set_model_routing({})
    session = LlmSession("", model_slug=le.get_prose_model())
    text = session.chat("Reply with exactly: hello")
    assert text.strip()


def test_filter_model_structured_output(monkeypatch):
    le.set_model_routing({"filter_model": "ollama:qwen3:8b"})
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    if not le.check_ollama_available():
        pytest.skip("Ollama not running locally")
    prompt = (
        'Answer yes or no only via structured output. Is this appropriate for a family podcast title '
        '"Puppies Playing in Snow" channel "CuteClips" description "short montage"?'
    )
    session = LlmSession("", model_slug=le.get_filter_model())
    out = session.run_structured(prompt, LlmFilterResponse, log_prompt=False)
    assert out.get("answer") in ("yes", "no")
