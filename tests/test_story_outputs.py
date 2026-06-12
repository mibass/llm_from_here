import unittest

from pydantic import ValidationError

from llm_from_here.schemas.story_outputs import (
    LongformStoryScript,
    OutroScript,
    StoryScript,
    longform_story_to_segments,
    outro_to_segments,
    split_dialog_with_applause,
    story_to_segments,
)

_VALID_MUSIC = (
    "Create an approximately 3 minute acoustic folk instrumental underscore. "
    "Fingerpicked guitar, light mandolin, ~88 BPM, warm and nostalgic. "
    "Instrumental only, no vocals."
)


class TestStoryScriptValidation(unittest.TestCase):
    def test_accepts_valid_story(self):
        story = StoryScript(
            music_prompt=_VALID_MUSIC,
            paragraphs=[f"Paragraph {i} with enough text." for i in range(5)],
            applause_duration_sec=5,
        )
        self.assertEqual(len(story.paragraphs), 5)

    def test_rejects_short_music_prompt(self):
        with self.assertRaises(ValidationError):
            StoryScript(
                music_prompt="folk",
                paragraphs=[f"Paragraph {i}." for i in range(5)],
            )

    def test_rejects_too_few_paragraphs(self):
        with self.assertRaises(ValidationError):
            StoryScript(
                music_prompt=_VALID_MUSIC,
                paragraphs=["One", "Two"],
            )


class TestStoryToSegments(unittest.TestCase):
    def test_segment_order(self):
        story = StoryScript(
            music_prompt=_VALID_MUSIC,
            paragraphs=[f"Paragraph {i}." for i in range(5)],
            applause_duration_sec=4,
        )
        segments = story_to_segments(story)
        self.assertEqual(segments[0]["speaker"], "background")
        self.assertEqual(segments[0]["dialog"], _VALID_MUSIC)
        self.assertEqual(segments[1]["speaker"], "character 1")
        self.assertEqual(segments[-1]["speaker"], "audience")
        self.assertEqual(segments[-1]["dialog"], "[APPLAUSE duration 4]")
        self.assertEqual(len(segments), 7)


_VALID_TRANSCRIPT = (
    "[positive] I was walking down Flatbush when this guy stopped me. "
    "He said, hey, you play mandolin, right? I laughed and said maybe on Tuesdays. "
    "We talked for twenty minutes about nothing and everything. "
    "The bus hissed by and the rain started, and I realized I'd been smiling the whole time. "
    "That's the thing about New York — you can have a whole life in one corner. "
    "I still think about him when I tune up before a show."
)


class TestLongformStoryScriptValidation(unittest.TestCase):
    def test_accepts_valid_longform_story(self):
        story = LongformStoryScript(
            music_prompt=_VALID_MUSIC,
            transcript=_VALID_TRANSCRIPT,
            applause_duration_sec=4,
        )
        self.assertIn("Flatbush", story.transcript)

    def test_rejects_short_transcript(self):
        with self.assertRaises(ValidationError):
            LongformStoryScript(
                music_prompt=_VALID_MUSIC,
                transcript="Too short.",
            )

    def test_rejects_inline_applause_in_transcript(self):
        with self.assertRaises(ValidationError):
            LongformStoryScript(
                music_prompt=_VALID_MUSIC,
                transcript=_VALID_TRANSCRIPT + " [APPLAUSE duration 5]",
            )


class TestLongformStoryToSegments(unittest.TestCase):
    def test_single_narrator_block(self):
        story = LongformStoryScript(
            music_prompt=_VALID_MUSIC,
            transcript=_VALID_TRANSCRIPT,
            applause_duration_sec=5,
        )
        segments = longform_story_to_segments(story)
        self.assertEqual(segments[0]["speaker"], "background")
        self.assertEqual(segments[1]["speaker"], "character 1")
        self.assertEqual(segments[1]["dialog"], _VALID_TRANSCRIPT)
        self.assertEqual(segments[-1]["speaker"], "audience")
        self.assertEqual(len(segments), 3)


class TestOutroToSegments(unittest.TestCase):
    def test_splits_inline_applause(self):
        outro = OutroScript(
            music_prompt=_VALID_MUSIC,
            dialog="Thanks everyone. [APPLAUSE duration 5] Goodnight!",
        )
        segments = outro_to_segments(outro)
        self.assertEqual(segments[0]["speaker"], "background")
        speakers = [s["speaker"] for s in segments]
        self.assertIn("audience", speakers)
        self.assertIn("character 1", speakers)


class TestSplitDialogWithApplause(unittest.TestCase):
    def test_interleaves_narrator_and_audience(self):
        segments = split_dialog_with_applause(
            "Hello. [APPLAUSE duration 4] Goodbye.",
            character_number=1,
        )
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0]["dialog"], "Hello.")
        self.assertEqual(segments[1]["speaker"], "audience")
        self.assertEqual(segments[2]["dialog"], "Goodbye.")


if __name__ == "__main__":
    unittest.main()
