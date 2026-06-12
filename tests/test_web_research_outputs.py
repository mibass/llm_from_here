import unittest

from pydantic import ValidationError

from llm_from_here.schemas.web_research_outputs import (
    ResearchedClipScript,
    WebResearchContext,
    researched_clip_to_segments,
)


class TestWebResearchContext(unittest.TestCase):
    def test_accepts_structured_research(self):
        ctx = WebResearchContext(
            subject="Paranoid Android",
            summaries=["Written during OK Computer sessions."],
            notes="Inspired by a noisy bar conversation.",
            proper_nouns=["Radiohead", "Thom Yorke"],
            places=["Oxford"],
            sources=[{"url": "https://example.com", "title": "Example", "snippet": "Fact"}],
        )
        self.assertEqual(ctx.subject, "Paranoid Android")

    def test_rejects_empty_context(self):
        with self.assertRaises(ValidationError):
            WebResearchContext()


class TestResearchedClipScript(unittest.TestCase):
    def test_mapper_builds_clip_and_applause(self):
        script = ResearchedClipScript(
            subject="Paranoid Android",
            intro_dialog="Welcome to This Week in Radiohead.",
            story_dialog="They wrote it in a noisy bar.",
            transition_dialog="Here is a live version.",
            youtube_search_query="Radiohead Paranoid Android live",
            applause_duration_sec=4,
        )
        segments = researched_clip_to_segments(script)
        self.assertEqual(segments[0]["speaker"], "character 1")
        self.assertEqual(segments[-2]["speaker"], "audience")
        self.assertEqual(segments[-2]["dialog"], "[APPLAUSE duration 4]")
        self.assertEqual(segments[-1]["speaker"], "clip")
        self.assertEqual(segments[-1]["dialog"], "Radiohead Paranoid Android live")

    def test_rejects_missing_query(self):
        with self.assertRaises(ValidationError):
            ResearchedClipScript(
                subject="Creep",
                intro_dialog="Intro",
                story_dialog="Story",
                youtube_search_query="",
            )


if __name__ == "__main__":
    unittest.main()
