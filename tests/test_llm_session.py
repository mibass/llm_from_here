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


if __name__ == "__main__":
    unittest.main()
