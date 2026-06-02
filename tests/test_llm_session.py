import unittest
from unittest.mock import MagicMock, patch

from pydantic import BaseModel
from pydantic_ai.output import NativeOutput

from llm_from_here.llm_session import LlmSession


class _Mini(BaseModel):
    x: int


class TestLlmSession(unittest.TestCase):
    @patch("llm_from_here.llm_session.OpenRouterModel")
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
    def test_resolve_agent_backend_free_mode_disables_required_tool_choice(
        self, _mock_free, mock_or_model
    ):
        LlmSession._resolve_agent_backend(None)
        mock_or_model.assert_called_once()
        kwargs = mock_or_model.call_args.kwargs
        self.assertFalse(kwargs["profile"].openai_supports_tool_choice_required)


class TestLlmSessionModelSlug(unittest.TestCase):
    @patch("llm_from_here.llm_session.OpenRouterModel")
    @patch("llm_from_here.llm_session.Agent")
    def test_model_slug_passes_string_to_agent_for_ollama(self, mock_agent_cls, mock_or_model):
        mock_agent_cls.return_value = MagicMock()
        LlmSession("Hello", model_slug="ollama:qwen3:8b")
        mock_or_model.assert_not_called()
        first_arg = mock_agent_cls.call_args[0][0]
        self.assertEqual(first_arg, "ollama:qwen3:8b")

    @patch("llm_from_here.llm_session.log_free_mode_startup")
    @patch("llm_from_here.llm_session.get_openrouter_chat_model", return_value="deepseek/deepseek-chat")
    @patch("llm_from_here.llm_session.OpenRouterModel")
    @patch("llm_from_here.llm_session.Agent")
    def test_openrouter_prefix_uses_openrouter_model(
        self, mock_agent_cls, mock_or_model, _mock_get_slug, _mock_log_free
    ):
        mock_agent_cls.return_value = MagicMock()
        fake_or = MagicMock(name="ORM")
        mock_or_model.return_value = fake_or
        LlmSession("", model_slug="openrouter:anthropic/claude-3.5-haiku")
        mock_or_model.assert_called_once_with("anthropic/claude-3.5-haiku")
        self.assertIs(mock_agent_cls.call_args[0][0], fake_or)


if __name__ == "__main__":
    unittest.main()
