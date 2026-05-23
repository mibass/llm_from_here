from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import llm_from_here.llm_env as le
from llm_from_here.agents import guest_agent as ga


@pytest.fixture(autouse=True)
def _routing_and_cache():
    le.set_model_routing({"structured_model": "openrouter:openai/gpt-4o-mini"})
    ga.clear_guest_agent_cache_for_tests()
    yield
    ga.clear_guest_agent_cache_for_tests()
    le.set_model_routing({})


def test_run_filter_llm_yes():
    with patch.object(ga, "LlmSession") as mock_sess_cls:
        mock_sess = MagicMock()
        mock_sess_cls.return_value = mock_sess
        mock_sess.run_structured.return_value = {"answer": "yes"}
        assert ga._run_filter_llm("t", "c", "d", "Pat Smith") is True


def test_run_filter_llm_no():
    with patch.object(ga, "LlmSession") as mock_sess_cls:
        mock_sess = MagicMock()
        mock_sess_cls.return_value = mock_sess
        mock_sess.run_structured.return_value = {"answer": "no"}
        assert ga._run_filter_llm("t", "c", "d") is False


def test_run_filter_llm_prompt_includes_guest_name():
    with patch.object(ga, "LlmSession") as mock_sess_cls:
        mock_sess = MagicMock()
        mock_sess_cls.return_value = mock_sess
        mock_sess.run_structured.return_value = {"answer": "yes"}
        ga._run_filter_llm("Interview", "BookTV", "Long description.", "Margaret Atwood")
        prompt = mock_sess.run_structured.call_args[0][0]
        assert "Margaret Atwood" in prompt


def test_strip_guest_queue_prefix():
    assert ga.strip_guest_queue_prefix("Band Name: Feist") == "Feist"
    assert ga.strip_guest_queue_prefix("Comedian: Pat Smith") == "Pat Smith"


def test_video_metadata_features_guest_substring():
    assert ga.video_metadata_features_guest(
        "Iron & Wine",
        "Iron and Wine — Full Session",
        "Performed live at KCRW.",
    )


def test_video_metadata_features_guest_strips_queue_prefix():
    assert ga.video_metadata_features_guest(
        "Band Name: The Head and the Heart",
        "The Head and the Heart - Lost In My Mind (Live on KEXP)",
        "Live session",
    )


def test_video_metadata_features_guest_rejects_other_subject():
    assert not ga.video_metadata_features_guest(
        "Margaret Atwood",
        "Isabel Allende Answers Fan Questions",
        "The beloved author Isabel Allende joins us.",
    )


def test_get_guest_agent_cached_per_model():
    a1 = ga.get_guest_agent()
    a2 = ga.get_guest_agent()
    assert a1 is a2
    le.set_model_routing({"structured_model": "openrouter:openai/gpt-4o"})
    ga.clear_guest_agent_cache_for_tests()
    b1 = ga.get_guest_agent()
    assert b1 is not a1
