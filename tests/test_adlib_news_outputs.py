import unittest

from pydantic import ValidationError

from llm_from_here.schemas.adlib_news_outputs import (
    AdlibNewsBundle,
    AdlibNewsScript,
    NewsReadoutItem,
    NewsResearchContext,
    NewsStoryItem,
    adlib_news_to_segments,
    format_news_readout,
)


def _story_item(category: str, headline: str, summary: str) -> NewsStoryItem:
    return NewsStoryItem(
        category=category,
        headline=headline,
        summary=summary,
        proper_nouns=["WidgetCo"],
        people=["Alex Rivera"],
        places=["Portland"],
        adjectives=["unexpected"],
        organizations=["WidgetCo"],
    )


def _five_stories() -> list[NewsStoryItem]:
    return [
        _story_item("world", "City opens new library wing", "Residents celebrated the opening on Tuesday."),
        _story_item("us", "Scientists study butterfly migration", "Researchers tagged monarchs near the coast."),
        _story_item("science", "Local bakery wins pie contest", "The shop took first place with a blueberry entry."),
        _story_item("business", "Town hosts outdoor chess tournament", "Players competed under string lights downtown."),
        _story_item("sports", "Museum unveils vintage radio exhibit", "Curators restored dozens of tabletop radios."),
    ]


def _long_body(topic: str) -> str:
    return (
        f"Officials in {topic} described the development as genuinely surprising while residents "
        "gathered nearby to compare notes, trade theories, and wonder aloud how the details would "
        "look once the full picture settled into place over the next few days. By evening, the "
        "conversation had sprawled across porches, diners, and late-night radio call-ins as people "
        "tried to explain what had happened using whatever nouns happened to be lying around."
    )


def _readout_item(category: str, headline: str) -> NewsReadoutItem:
    return NewsReadoutItem(
        category=category,
        transition_line=f"In {category} news...",
        headline=headline,
        body=_long_body(headline),
        emotion_tag="[neutral]",
        reaction_line="",
    )


class TestNewsResearchContext(unittest.TestCase):
    def test_accepts_five_distinct_categories(self):
        ctx = NewsResearchContext(
            subject=" | ".join(story.headline for story in _five_stories()),
            stories=_five_stories(),
        )
        self.assertEqual(len(ctx.stories), 5)

    def test_rejects_duplicate_categories(self):
        stories = _five_stories()
        stories[1] = _story_item("world", "Duplicate category story", "Another summary here.")
        with self.assertRaises(ValidationError):
            NewsResearchContext(subject="duplicate categories", stories=stories)

    def test_rejects_grim_story(self):
        with self.assertRaises(ValidationError):
            NewsStoryItem(
                category="us",
                headline="Mass shooting investigation continues",
                summary="Police are still gathering evidence downtown.",
            )


class TestAdlibNewsScript(unittest.TestCase):
    def test_format_news_readout_is_plain_prose(self):
        readout = format_news_readout(
            _readout_item("sports", "Museum unveils vintage radio exhibit")
        )
        self.assertIn("In sports news...", readout)
        self.assertIn("Museum unveils vintage radio exhibit.", readout)
        self.assertNotIn("adlib_headline", readout)

    def test_mapper_emits_pause_gaps_and_outro_applause_only(self):
        script = AdlibNewsScript(
            music_prompt=(
                "Create a 270-second understated public-radio newswire instrumental bed. "
                "Muted piano, soft marimba, brushed snare, 80 BPM. Instrumental only, no vocals."
            ),
            intro_dialog=(
                "It is time for Adlib the News, where the headlines stay real but a few nouns "
                "have been on a field trip."
            ),
            stories=[
                _readout_item(story.category, story.headline) for story in _five_stories()
            ],
            outro_dialog="That is Adlib the News for tonight.",
            applause_duration_sec=4,
        )
        segments = adlib_news_to_segments(script)
        self.assertEqual(segments[0]["speaker"], "background")
        self.assertEqual(segments[1]["speaker"], "character 1")
        self.assertEqual(segments[-1]["speaker"], "audience")
        self.assertEqual(segments[-1]["dialog"], "[APPLAUSE duration 4]")
        self.assertEqual(sum(1 for segment in segments if segment["speaker"] == "pause"), 4)
        self.assertEqual(
            sum(1 for segment in segments if segment["speaker"] == "audience"),
            1,
        )

    def test_rejects_dict_like_readout_body(self):
        with self.assertRaises(ValidationError):
            NewsReadoutItem(
                category="odd",
                transition_line="In odd news...",
                headline="Florida man takes pear moped cross-country",
                body="{'adlib_summary': 'This should not be spoken aloud.'}" + " " * 280,
            )


if __name__ == "__main__":
    unittest.main()
