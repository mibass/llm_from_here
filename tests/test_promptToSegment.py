import unittest
from unittest.mock import MagicMock, patch

from llm_from_here.plugins.promptToSegment import PromptToSegment


class TestPromptToSegment(unittest.TestCase):
    def setUp(self):
        self._or_patch = patch(
            "llm_from_here.llm_session.OpenRouterModel", return_value=MagicMock()
        )
        self._agent_patch = patch(
            "llm_from_here.llm_session.Agent", return_value=MagicMock()
        )
        self._or_patch.start()
        self._agent_patch.start()

    def tearDown(self):
        self._agent_patch.stop()
        self._or_patch.stop()

    def test_normalize_segments_puts_background_first_and_drops_title(self):
        pts = PromptToSegment({"convert_script_to_segments": False}, {}, "story")
        pts.segments = [
            {
                "speaker": "character 1",
                "dialog": "**The Time I Bought a Goldfish**",
                "character_name": "narrator",
            },
            {"speaker": "background", "dialog": "folk"},
            {
                "speaker": "character 1",
                "dialog": "So there I was...",
                "character_name": "narrator",
            },
        ]
        pts._normalize_segments()
        self.assertEqual(pts.segments[0]["speaker"], "background")
        self.assertEqual(len(pts.segments), 2)
        self.assertEqual(pts.segments[1]["dialog"], "So there I was...")

    def test_background_music_markdown_parses_as_background(self):
        pts = PromptToSegment({"convert_script_to_segments": False}, {}, "story")
        pts.is_dialog = True
        pts.script = "[BACKGROUND MUSIC: folk]\nFirst paragraph."
        pts.convert_script_to_segments()
        self.assertEqual(pts.segments[0]["speaker"], "background")
        self.assertEqual(pts.segments[0]["dialog"], "folk")
        self.assertEqual(pts.segments[1]["dialog"], "First paragraph.")

    def test_standalone_applause_line_parses_as_audience(self):
        pts = PromptToSegment({"convert_script_to_segments": False}, {}, "story")
        pts.is_dialog = True
        pts.script = "[background: folk]\nLast line of the story.\n[APPLAUSE duration 5]"
        pts.convert_script_to_segments()
        self.assertEqual(pts.segments[-1]["speaker"], "audience")
        self.assertEqual(pts.segments[-1]["dialog"], "[APPLAUSE duration 5]")

    def test_full_prompt_background_cue_parses_as_background(self):
        pts = PromptToSegment({"convert_script_to_segments": False}, {}, "story")
        pts.is_dialog = True
        cue = (
            "[background: Create an approximately 3 minute acoustic folk instrumental "
            "underscore. Fingerpicked guitar, light mandolin, ~88 BPM. Instrumental only, no vocals.]"
        )
        pts.script = cue + "\nSo there I was on the corner."
        pts.convert_script_to_segments()
        self.assertEqual(pts.segments[0]["speaker"], "background")
        self.assertIn("approximately 3 minute", pts.segments[0]["dialog"])
        self.assertEqual(pts.segments[1]["dialog"], "So there I was on the corner.")

    @patch("llm_from_here.plugins.promptToSegment.ChatApp")
    def test_structured_prompt_uses_mapper(self, mock_chat_app_cls):
        mock_chat = MagicMock()
        mock_chat_app_cls.return_value = mock_chat
        story_payload = {
            "music_prompt": (
                "Create an approximately 3 minute acoustic folk instrumental underscore. "
                "Fingerpicked guitar, ~88 BPM. Instrumental only, no vocals."
            ),
            "paragraphs": [f"Paragraph {i}." for i in range(5)],
            "applause_duration_sec": 5,
        }
        mock_chat.run_structured.return_value = story_payload

        pts = PromptToSegment(
            {
                "convert_script_to_segments": False,
                "prompts": [
                    {
                        "prompt": "Generate story",
                        "output_model": "llm_from_here.schemas.story_outputs:StoryScript",
                        "segment_mapper": "llm_from_here.schemas.story_outputs:story_to_segments",
                    }
                ],
            },
            {},
            "story",
        )
        self.assertEqual(pts.segments[0]["speaker"], "background")
        self.assertEqual(len(pts.segments), 7)
        mock_chat.run_structured.assert_called_once()

    @patch("llm_from_here.plugins.promptToSegment.ChatApp")
    def test_chat_app_variable_reuses_session(self, mock_chat_app_cls):
        existing_chat = MagicMock()
        existing_chat.run_structured.return_value = {
            "music_prompt": (
                "Create an approximately 3 minute acoustic folk instrumental underscore. "
                "Fingerpicked guitar, ~88 BPM. Instrumental only, no vocals."
            ),
            "paragraphs": [f"Paragraph {i}." for i in range(5)],
            "applause_duration_sec": 5,
        }
        PromptToSegment(
            {
                "chat_app_variable": "intro_chat_app",
                "convert_script_to_segments": False,
                "prompts": [
                    {
                        "prompt": "Generate story",
                        "output_model": "llm_from_here.schemas.story_outputs:StoryScript",
                        "segment_mapper": "llm_from_here.schemas.story_outputs:story_to_segments",
                    }
                ],
            },
            {"intro_chat_app": existing_chat},
            "story",
        )
        mock_chat_app_cls.assert_not_called()
        existing_chat.run_structured.assert_called_once()

    @patch("llm_from_here.plugins.promptToSegment.random.random", return_value=0.99)
    @patch("llm_from_here.plugins.promptToSegment.ChatApp")
    def test_include_probability_skip_does_not_run_prompts(self, mock_chat_app_cls, _mock_rand):
        mock_chat = MagicMock()
        mock_chat_app_cls.return_value = mock_chat
        pts = PromptToSegment(
            {
                "include_probability": 0.25,
                "convert_script_to_segments": False,
                "prompts": [{"prompt": "Generate story"}],
            },
            {},
            "radiohead",
        )
        self.assertFalse(pts.included)
        self.assertEqual(pts.segments, [])
        mock_chat.chat.assert_not_called()
        mock_chat.run_structured.assert_not_called()

    @patch("llm_from_here.plugins.promptToSegment.random.random", return_value=0.01)
    @patch("llm_from_here.plugins.promptToSegment.run_web_search")
    @patch("llm_from_here.plugins.promptToSegment.ChatApp")
    def test_web_research_feeds_dialog_generator(
        self, mock_chat_app_cls, mock_run_web_search, _mock_rand
    ):
        from llm_from_here.openrouter_web_search import UrlCitation, WebSearchResult

        mock_chat = MagicMock()
        mock_chat_app_cls.return_value = mock_chat
        mock_run_web_search.return_value = WebSearchResult(
            content="Paranoid Android was written in 1997.",
            citations=[
                UrlCitation(
                    url="https://example.com",
                    title="Example",
                    content="Studio notes",
                )
            ],
            web_search_requests=1,
        )
        research_payload = {
            "subject": "Paranoid Android",
            "summaries": ["Written during OK Computer sessions."],
            "notes": "Inspired by a noisy bar.",
            "entities": [],
            "proper_nouns": ["Radiohead"],
            "places": ["Oxford"],
            "adjectives": [],
            "organizations": [],
            "sources": [{"url": "https://example.com", "title": "Example", "snippet": "Fact"}],
        }
        dialog_payload = {
            "subject": "Paranoid Android",
            "intro_dialog": "This week in Radiohead.",
            "story_dialog": "They wrote it in a bar.",
            "transition_dialog": "Enjoy this live take.",
            "youtube_search_query": "Radiohead Paranoid Android live",
            "applause_duration_sec": 4,
        }
        mock_chat.run_structured.side_effect = [research_payload, dialog_payload]

        pts = PromptToSegment(
            {
                "include_probability": 1.0,
                "convert_script_to_segments": False,
                "web_research": {
                    "search_prompt": "Research a Radiohead song",
                    "search": {"engine": "exa", "max_results": 3},
                    "extraction_model": (
                        "llm_from_here.schemas.web_research_outputs:WebResearchContext"
                    ),
                },
                "prompts": [
                    {
                        "prompt": "Using this research context:\n{{research_context}}\nWrite dialog.",
                        "output_model": (
                            "llm_from_here.schemas.web_research_outputs:ResearchedClipScript"
                        ),
                        "segment_mapper": (
                            "llm_from_here.schemas.web_research_outputs:researched_clip_to_segments"
                        ),
                    }
                ],
            },
            {},
            "radiohead",
        )
        self.assertTrue(pts.included)
        self.assertEqual(mock_chat.run_structured.call_count, 2)
        dialog_prompt = mock_chat.run_structured.call_args_list[1].args[0]
        self.assertIn("Paranoid Android", dialog_prompt)
        self.assertEqual(pts.segments[-1]["speaker"], "clip")
        self.assertEqual(pts.segments[-2]["speaker"], "audience")

    @patch("llm_from_here.plugins.promptToSegment.SupaSet")
    @patch("llm_from_here.plugins.promptToSegment.random.random", return_value=0.01)
    @patch("llm_from_here.plugins.promptToSegment.run_web_search")
    @patch("llm_from_here.plugins.promptToSegment.ChatApp")
    def test_used_subjects_retries_when_song_already_covered(
        self, mock_chat_app_cls, mock_run_web_search, _mock_rand, mock_supaset_cls
    ):
        from llm_from_here.openrouter_web_search import WebSearchResult

        mock_supaset = MagicMock()
        mock_supaset.elements.return_value = ["creep"]
        mock_supaset.__contains__ = lambda _self, value: value == "creep"
        mock_supaset_cls.return_value = mock_supaset

        mock_chat = MagicMock()
        mock_chat_app_cls.return_value = mock_chat
        mock_run_web_search.return_value = WebSearchResult(content="facts", citations=[])

        research_creep = {
            "subject": "Creep",
            "summaries": ["Already done."],
            "notes": "n",
            "entities": [],
            "proper_nouns": [],
            "places": [],
            "adjectives": [],
            "organizations": [],
            "sources": [],
        }
        research_karma = {
            "subject": "Karma Police",
            "summaries": ["Fresh song."],
            "notes": "n",
            "entities": [],
            "proper_nouns": [],
            "places": [],
            "adjectives": [],
            "organizations": [],
            "sources": [],
        }
        dialog_payload = {
            "subject": "Karma Police",
            "intro_dialog": "This week in Radiohead.",
            "story_dialog": "A new story.",
            "transition_dialog": "Enjoy this live take.",
            "youtube_search_query": "Radiohead Karma Police live",
            "applause_duration_sec": 4,
        }
        mock_chat.run_structured.side_effect = [research_creep, research_karma, dialog_payload]

        pts = PromptToSegment(
            {
                "convert_script_to_segments": False,
                "web_research": {
                    "track_used_subjects": True,
                    "used_subjects_supaset_name": "radiohead_songs",
                    "max_subject_retries": 2,
                    "search_prompt": "Research a Radiohead song",
                    "extraction_model": (
                        "llm_from_here.schemas.web_research_outputs:WebResearchContext"
                    ),
                },
                "prompts": [
                    {
                        "prompt": "Write dialog for {{research_context}}",
                        "output_model": (
                            "llm_from_here.schemas.web_research_outputs:ResearchedClipScript"
                        ),
                        "segment_mapper": (
                            "llm_from_here.schemas.web_research_outputs:researched_clip_to_segments"
                        ),
                    }
                ],
            },
            {},
            "radiohead",
        )
        self.assertTrue(pts.included)
        self.assertEqual(pts._recorded_subject, "Karma Police")
        self.assertEqual(mock_run_web_search.call_count, 2)
        mock_supaset.add.assert_not_called()

        pts.finalize()
        mock_supaset.add.assert_called_once_with("Karma Police")
        mock_supaset.complete_session.assert_called_once()

    @patch("llm_from_here.plugins.promptToSegment.random.random", return_value=0.01)
    @patch("llm_from_here.plugins.promptToSegment.run_web_search")
    @patch("llm_from_here.plugins.promptToSegment.ChatApp")
    def test_multi_prompt_passes_script_to_second_prompt(
        self, mock_chat_app_cls, mock_run_web_search, _mock_rand
    ):
        from llm_from_here.openrouter_web_search import WebSearchResult

        mock_chat = MagicMock()
        mock_chat_app_cls.return_value = mock_chat
        mock_run_web_search.return_value = WebSearchResult(content="news", citations=[])

        categories = ["world", "us", "science", "business", "sports"]
        headlines = [
            "City opens new library wing",
            "Scientists study butterfly migration",
            "Local bakery wins pie contest",
            "Town hosts outdoor chess tournament",
            "Museum unveils vintage radio exhibit",
        ]
        long_body = (
            "Officials described the development as genuinely surprising while residents "
            "gathered nearby to compare notes, trade theories, and wonder aloud how the "
            "details would look once the full picture settled into place over the next few "
            "days. By evening, the conversation had sprawled across porches, diners, and "
            "late-night radio call-ins as people tried to explain what had happened. "
            "City leaders said they would revisit the plan after the weekend, though no one "
            "could quite agree on which part of the story had been the strangest detail."
        )
        research_payload = {
            "subject": " | ".join(headlines),
            "stories": [
                {
                    "category": category,
                    "headline": headline,
                    "summary": "Residents celebrated on Tuesday.",
                    "proper_nouns": ["Library"],
                    "people": ["Mayor Lee"],
                    "places": ["Springfield"],
                    "adjectives": ["new"],
                    "organizations": ["City Hall"],
                }
                for category, headline in zip(categories, headlines)
            ],
        }
        adlib_payload = {
            "stories": [
                {
                    "headline": headline,
                    "adlib_body": long_body,
                    "swapped_tokens": ["Springfield", "Mayor Lee"],
                }
                for headline in headlines
            ],
        }
        script_payload = {
            "music_prompt": (
                "Create a 270-second understated public-radio newswire instrumental bed. "
                "Muted piano, soft marimba, brushed snare, 80 BPM. Instrumental only, no vocals."
            ),
            "intro_dialog": "Welcome to Adlib the News on Live From There tonight.",
            "stories": [
                {
                    "category": category,
                    "transition_line": f"In {category} news...",
                    "headline": headline,
                    "body": long_body,
                    "emotion_tag": "[neutral]",
                    "reaction_line": "",
                }
                for category, headline in zip(categories, headlines)
            ],
            "outro_dialog": "That is Adlib the News for tonight.",
            "applause_duration_sec": 5,
        }
        mock_chat.run_structured.side_effect = [
            research_payload,
            adlib_payload,
            script_payload,
        ]

        pts = PromptToSegment(
            {
                "include_probability": 1.0,
                "convert_script_to_segments": False,
                "web_research": {
                    "search_prompt": "Find five light news stories",
                    "search": {"engine": "exa", "max_results": 5},
                    "extraction_model": (
                        "llm_from_here.schemas.adlib_news_outputs:NewsResearchContext"
                    ),
                },
                "prompts": [
                    {
                        "prompt": "Adlib these stories:\n{{research_context}}",
                        "output_model": (
                            "llm_from_here.schemas.adlib_news_outputs:AdlibNewsBundle"
                        ),
                    },
                    {
                        "prompt": "Perform these scrambled stories:\n{{script}}",
                        "output_model": (
                            "llm_from_here.schemas.adlib_news_outputs:AdlibNewsScript"
                        ),
                        "segment_mapper": (
                            "llm_from_here.schemas.adlib_news_outputs:adlib_news_to_segments"
                        ),
                    },
                ],
            },
            {},
            "adlib_news",
        )

        self.assertTrue(pts.included)
        self.assertEqual(mock_chat.run_structured.call_count, 3)
        performance_prompt = mock_chat.run_structured.call_args_list[2].args[0]
        self.assertIn("City opens new library wing", performance_prompt)
        self.assertEqual(pts.segments[0]["speaker"], "background")
        self.assertEqual(pts.segments[-1]["speaker"], "audience")
        self.assertIn("In world news...", pts.segments[2]["dialog"])
        self.assertEqual(pts.segments[3]["speaker"], "pause")


if __name__ == "__main__":
    unittest.main()
