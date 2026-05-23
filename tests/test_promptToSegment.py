import unittest
from unittest.mock import MagicMock, patch

from llm_from_here.plugins.promptToSegment import PromptToSegment


class TestPromptToSegment(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
