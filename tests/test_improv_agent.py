"""Unit tests for ImprovAgent and segment_type_map_variable."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from llm_from_here.plugins.improvAgent import ImprovAgent, _extract_bracket_cues, _strip_bracket_cues
from llm_from_here.plugins.segmentsToTimeline import SegmentsToTimeline
from llm_from_here.schemas.improv_outputs import CharacterSlotSetup, SceneSetup


class TestBracketHelpers(unittest.TestCase):
    def test_strip_and_extract(self):
        s = "Hello [door creak] there [BACKGROUND: x]!"
        self.assertIn("door creak", _extract_bracket_cues(s))
        self.assertNotIn("BACKGROUND", "".join(_extract_bracket_cues(s)))
        self.assertNotIn("[", _strip_bracket_cues(s))


@patch("llm_from_here.plugins.improvAgent.FreeSoundFetch")
class TestImprovAgentBuildMap(unittest.TestCase):
    def test_build_segment_type_map(self, mock_fs: MagicMock) -> None:
        mock_fs.return_value = MagicMock()
        params = {
            "character_slots": [
                {"model": "openai/gpt-4o-mini", "tts_voice": "nova"},
                {"model": "openai/gpt-4o-mini", "tts_voice": "echo"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")
            scene = SceneSetup(
                characters=[
                    CharacterSlotSetup(slot=1, name="A", description="want a"),
                    CharacterSlotSetup(slot=2, name="B", description="want b"),
                ],
                setting="A cafe",
                scenario="Spilled latte",
                background_sound="cafe ambience",
                sfx_palette=["cup", "steam", "chair"],
            )
            smap = agent._build_segment_type_map(scene)
            self.assertEqual(smap["character 1"]["segment_type"], "fast_TTS")
            self.assertEqual(smap["character 1"]["arguments"]["voice"], "nova")
            self.assertEqual(smap["character 2"]["arguments"]["voice"], "echo")
            self.assertEqual(smap["sound effect"]["segment_type"], "music_generator_freesound")


class TestSegmentTypeMapVariable(unittest.TestCase):
    @patch("llm_from_here.plugins.freesoundfetch.FreeSoundFetch")
    def test_resolves_from_global_results(self, _mock_fs: MagicMock) -> None:
        tmp = tempfile.mkdtemp()
        try:
            ext_map = {
                "character 1": {"segment_type": "fast_TTS", "arguments": {"voice": "onyx"}},
                "default": {"segment_type": "fast_TTS", "arguments": {}},
            }
            params = {
                "segments_object": "segs",
                "segment_type_map_variable": "improv_segment_type_map",
                "segment_type_key": "speaker",
                "segment_value_key": "dialog",
            }
            gr = {
                "output_folder": tmp,
                "segs": [{"speaker": "character 1", "dialog": "Hi"}],
                "improv_segment_type_map": ext_map,
            }
            stt = SegmentsToTimeline(params, gr, "test")
            self.assertEqual(stt._segment_type_map()["character 1"]["arguments"]["voice"], "onyx")
        finally:
            os.rmdir(tmp)
