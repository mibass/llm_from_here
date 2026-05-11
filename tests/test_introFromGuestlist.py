from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from llm_from_here.plugins.introFromGuestlist import IntroFromGuestlist


def test_execute_returns_script_and_intro():
    params = {
        "system_message": "sys",
        "script_prompt": "Guests: {{ guests }}",
        "json_script_prompt": "structure",
        "guests_parameter": "guest_selection_guests",
        "extra_prompts": [],
    }
    global_params = {
        "guest_selection_guests": [
            {"guest_name": "Pat Smith", "guest_category": "music"},
        ]
    }
    with patch("llm_from_here.plugins.introFromGuestlist.gpt.ChatApp") as MockChat:
        mock_inst = MagicMock()
        MockChat.return_value = mock_inst
        mock_inst.chat.return_value = "prose script"
        mock_inst.run_structured.return_value = {
            "lines": [
                {"speaker": "Music", "dialog": "[MUSIC jazz]"},
                {"speaker": "Chris Thile", "dialog": "Hello."},
            ]
        }
        intro = IntroFromGuestlist(params, global_params, "intro_unit_test")
        out = intro.execute()
        assert out["script"] == "prose script"
        assert len(out["intro"]) == 2
        assert out["guests"] == intro.guests
        mock_inst.chat.assert_called()
        mock_inst.run_structured.assert_called_once()


def test_missing_guests_raises():
    params = {
        "system_message": "sys",
        "script_prompt": "x",
        "json_script_prompt": "y",
        "guests_parameter": "missing_key",
    }
    with patch("llm_from_here.plugins.introFromGuestlist.gpt.ChatApp"):
        with pytest.raises(Exception, match="missing_key"):
            IntroFromGuestlist(params, {}, "intro_fail")


def test_guest_list_passed_to_template_contains_unique_names():
    params = {
        "system_message": "sys",
        "script_prompt": "Guests: {{ guests }}",
        "json_script_prompt": "json",
        "guests_parameter": "guest_selection_guests",
        "extra_prompts": [],
    }
    global_params = {
        "guest_selection_guests": [
            {"guest_name": "Ann", "guest_category": "music"},
            {"guest_name": "Ann", "guest_category": "music"},
            {"guest_name": "Bob", "guest_category": "comedy"},
        ]
    }
    rendered_captured: list[str] = []

    def capture_chat(msg):
        rendered_captured.append(msg)
        return "ok"

    def capture_struct(*a, **k):
        return {"lines": []}

    with patch("llm_from_here.plugins.introFromGuestlist.gpt.ChatApp") as MockChat:
        mock_inst = MagicMock()
        MockChat.return_value = mock_inst
        mock_inst.chat.side_effect = capture_chat
        mock_inst.run_structured.side_effect = capture_struct
        IntroFromGuestlist(params, global_params, "intro_dedupe")
        prompt_used = rendered_captured[0]
        assert "Ann" in prompt_used
        assert "Bob" in prompt_used
