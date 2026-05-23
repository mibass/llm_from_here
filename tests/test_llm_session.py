import unittest
from unittest.mock import MagicMock, patch

from pydantic import BaseModel
from pydantic_ai.output import NativeOutput

from llm_from_here.llm_session import LlmSession


class _Mini(BaseModel):
    x: int


class TestLlmSession(unittest.TestCase):
    @patch("llm_from_here.llm_session._openrouter_model")
    @patch("llm_from_here.llm_session.Agent")
    def setUp(self, mock_agent_cls, _mock_or_model):
        self.mock_agent_cls = mock_agent_cls
        self.mock_agent = MagicMock()
        mock_agent_cls.return_value = self.mock_agent
        self.session = LlmSession("Welcome")

    def test_chat_returns_output(self):
        mock_result = MagicMock()
        mock_result.output = "Test response"
        mock_result.new_messages.return_value = []
        self.mock_agent.run_sync.return_value = mock_result

        response = self.session.chat("Test message")

        self.assertEqual(response, "Test response")
        self.mock_agent.run_sync.assert_called_once()
        call_kw = self.mock_agent.run_sync.call_args.kwargs
        self.assertEqual(call_kw.get("output_type"), str)

    def test_run_structured_uses_native_when_configured(self):
        mock_result = MagicMock()
        mock_result.output = _Mini(x=1)
        mock_result.new_messages.return_value = []
        self.mock_agent.run_sync.return_value = mock_result

        with patch("llm_from_here.llm_session.get_structured_output_mode", return_value="native"):
            out = self.session.run_structured("p", _Mini, log_prompt=False)

        self.assertEqual(out, {"x": 1})
        spec = self.mock_agent.run_sync.call_args.kwargs["output_type"]
        self.assertIsInstance(spec, NativeOutput)

    def test_run_structured_free_mode_falls_back_to_tool(self):
        mock_ok = MagicMock()
        mock_ok.output = _Mini(x=2)
        mock_ok.new_messages.return_value = []
        self.mock_agent.run_sync.side_effect = [RuntimeError("Tool choice must be auto"), mock_ok]

        with patch("llm_from_here.llm_session.is_openrouter_free_mode", return_value=True):
            with patch("llm_from_here.llm_session.get_structured_output_mode", return_value="native"):
                out = self.session.run_structured("p", _Mini, log_prompt=False)

        self.assertEqual(out, {"x": 2})
        self.assertEqual(self.mock_agent.run_sync.call_count, 2)
        first_spec = self.mock_agent.run_sync.call_args_list[0].kwargs["output_type"]
        second_spec = self.mock_agent.run_sync.call_args_list[1].kwargs["output_type"]
        self.assertIsInstance(first_spec, NativeOutput)
        self.assertIs(second_spec, _Mini)

    @patch("llm_from_here.llm_session.OpenRouterModel")
    @patch("llm_from_here.llm_session.is_openrouter_free_mode", return_value=True)
    def test_openrouter_model_free_mode_disables_required_tool_choice(self, mock_free, mock_or_model):
        from llm_from_here.llm_session import _openrouter_model

        _openrouter_model("openrouter/free")
        mock_or_model.assert_called_once()
        kwargs = mock_or_model.call_args.kwargs
        self.assertFalse(kwargs["profile"].openai_supports_tool_choice_required)

    @patch("llm_from_here.llm_session._openrouter_model")
    @patch("llm_from_here.llm_session.Agent")
    def test_model_slug_override(self, mock_agent_cls, mock_or_model):
        mock_agent = MagicMock()
        mock_agent_cls.return_value = mock_agent
        s = LlmSession("Hi", model_slug="openai/gpt-4o-mini")
        self.assertEqual(s.chat_model_slug, "openai/gpt-4o-mini")
        mock_or_model.assert_called_once_with("openai/gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
