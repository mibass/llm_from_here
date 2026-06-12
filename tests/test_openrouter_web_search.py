import unittest
from unittest.mock import MagicMock, patch

from llm_from_here.openrouter_web_search import (
    UrlCitation,
    WebSearchResult,
    build_web_search_tool,
    run_web_search,
)


class TestOpenRouterWebSearch(unittest.TestCase):
    def test_build_web_search_tool_defaults(self):
        tool = build_web_search_tool()
        self.assertEqual(tool["type"], "openrouter:web_search")
        self.assertEqual(tool["parameters"]["engine"], "exa")
        self.assertEqual(tool["parameters"]["max_results"], 5)
        self.assertEqual(tool["parameters"]["max_total_results"], 10)

    def test_url_citation_from_annotation(self):
        cite = UrlCitation.from_annotation(
            {
                "type": "url_citation",
                "url_citation": {
                    "url": "https://example.com/page",
                    "title": "Example",
                    "content": "Snippet text",
                },
            }
        )
        self.assertIsNotNone(cite)
        assert cite is not None
        self.assertEqual(cite.url, "https://example.com/page")
        self.assertEqual(cite.title, "Example")

    def test_format_sources(self):
        result = WebSearchResult(
            content="Answer text",
            citations=[
                UrlCitation(url="https://a.com", title="A", content="alpha"),
                UrlCitation(url="https://b.com", title="B", content="beta"),
            ],
        )
        rendered = result.format_sources()
        self.assertIn("[A](https://a.com)", rendered)
        self.assertIn("alpha", rendered)

    @patch("llm_from_here.openrouter_web_search.build_openrouter_client")
    def test_run_web_search_parses_citations(self, mock_build_client):
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        mock_message = MagicMock()
        mock_message.content = "Radiohead wrote Paranoid Android in 1997."
        mock_message.annotations = [
            {
                "type": "url_citation",
                "url_citation": {
                    "url": "https://radiohead.com/facts",
                    "title": "Radiohead Facts",
                    "content": "Studio notes",
                },
            }
        ]
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.server_tool_use.web_search_requests = 2
        mock_client.chat.completions.create.return_value = mock_response

        result = run_web_search("Research Radiohead Paranoid Android")
        self.assertIn("Paranoid Android", result.content)
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.web_search_requests, 2)
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["tools"][0]["type"], "openrouter:web_search")


if __name__ == "__main__":
    unittest.main()
