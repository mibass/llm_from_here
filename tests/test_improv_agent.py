"""Unit tests for ImprovAgent and segment_type_map_variable."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from llm_from_here.plugins.improvAgent import (
    ImprovAgent,
    _clean_dialog,
    _ESCALATOR_MOVES,
    _extract_bracket_cues,
    _normalize_sfx_query,
    _rotating_moves,
    _STRAIGHT_MAN_MOVES,
    _strip_bracket_cues,
)
from llm_from_here.plugins.segmentsToTimeline import SegmentsToTimeline
from llm_from_here.schemas.improv_outputs import CharacterSlotSetup, ImprovTurn, SceneSetup


class TestBracketHelpers(unittest.TestCase):
    def test_extract_only_explicit_sfx_cues(self):
        s = "Hi there [Alice leans closer] [SFX: door creak] [SOUND: rain] [BACKGROUND: x]"
        cues = _extract_bracket_cues(s)
        self.assertIn("door creak", cues)
        self.assertIn("rain", cues)
        # Arbitrary stage directions must NOT become SFX queries.
        self.assertNotIn("Alice leans closer", cues)
        self.assertFalse(any("BACKGROUND" in c for c in cues))

    def test_strip_bracket_cues_removes_all_brackets(self):
        s = "Hello [door creak] there [SFX: bell]!"
        stripped = _strip_bracket_cues(s)
        self.assertNotIn("[", stripped)
        self.assertNotIn("door creak", stripped)

    def test_normalize_sfx_query_trims_and_caps(self):
        self.assertEqual(_normalize_sfx_query("  Coffee machine steam.  "), "Coffee machine steam")
        self.assertLessEqual(len(_normalize_sfx_query("x" * 300)), 120)

    def test_clean_dialog_strips_leaked_speaker_prefix(self):
        self.assertEqual(_clean_dialog("Alice: Alice: Hello there", "Alice"), "Hello there")
        self.assertEqual(_clean_dialog('"Just a line"', "Bob"), "Just a line")
        self.assertEqual(_clean_dialog("[waves] Hi", "Bob"), "Hi")


class TestRotatingMoves(unittest.TestCase):
    def test_rotation_cycles_by_turn_index(self) -> None:
        esc0, sm0 = _rotating_moves(0)
        self.assertEqual(esc0, _ESCALATOR_MOVES[0])
        self.assertEqual(sm0, _STRAIGHT_MAN_MOVES[0])
        # Wraps around at the menu length so every move recurs.
        n = len(_ESCALATOR_MOVES)
        self.assertEqual(_rotating_moves(n)[0], _ESCALATOR_MOVES[0])
        self.assertEqual(_rotating_moves(n)[1], _STRAIGHT_MAN_MOVES[0])
        # Different index -> different move (menus have no duplicates).
        self.assertEqual(len(set(_ESCALATOR_MOVES)), n)
        self.assertEqual(len(set(_STRAIGHT_MAN_MOVES)), n)

    def test_turn_prompt_injects_rotating_move_and_sfx_cap(self) -> None:
        with patch("llm_from_here.plugins.improvAgent.LlmSession") as mock_llm, patch(
            "llm_from_here.plugins.improvAgent.FreeSoundFetch"
        ) as mock_fs, tempfile.TemporaryDirectory() as tmp:
            mock_llm.return_value = MagicMock()
            mock_fs.return_value = MagicMock()
            params = {
                "setup_model": "openrouter:deepseek/deepseek-v4-flash",
                "character_slots": [
                    {"model": "openrouter:deepseek/deepseek-v4-flash"},
                    {"model": "openrouter:deepseek/deepseek-v4-flash"},
                ],
            }
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")
            esc_move, sm_move = _rotating_moves(1)
            prompt = agent._turn_prompt(_make_scene(), "A", ["A: hi"], turn_index=1)

            self.assertIn("exactly ONE move", prompt)
            self.assertIn(esc_move, prompt)
            self.assertIn(sm_move, prompt)
            self.assertIn("at most ONE concrete", prompt)


def _make_scene() -> SceneSetup:
    return SceneSetup(
        characters=[
            CharacterSlotSetup(slot=1, name="A", description="want a"),
            CharacterSlotSetup(slot=2, name="B", description="want b"),
        ],
        setting="A cafe",
        scenario="Spilled latte",
        background_sound="cafe ambience",
        sfx_palette=["cup", "steam", "chair"],
    )


@patch("llm_from_here.plugins.improvAgent.LlmSession")
@patch("llm_from_here.plugins.improvAgent.FreeSoundFetch")
class TestImprovAgentBuildMap(unittest.TestCase):
    def _params(self) -> dict:
        return {
            "setup_model": "openrouter:openai/gpt-4o-mini",
            "character_slots": [
                {"model": "openrouter:openai/gpt-4o-mini", "tts_voice": "Puck"},
                {
                    "model": "openrouter:openai/gpt-4o-mini",
                    "tts_voice": "Fenrir",
                    "tts_model": "google/gemini-3.1-flash-tts-preview",
                },
            ],
        }

    def test_build_segment_type_map_uses_slow_tts_and_voices(
        self, mock_fs: MagicMock, mock_llm: MagicMock
    ) -> None:
        mock_fs.return_value = MagicMock()
        mock_llm.return_value = MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            agent = ImprovAgent(self._params(), {"output_folder": tmp}, "improv")
            smap = agent._build_segment_type_map(_make_scene())
            # Characters route to the Gemini TTS path (slow_TTS), not gTTS fast_TTS.
            self.assertEqual(smap["character 1"]["segment_type"], "slow_TTS")
            self.assertEqual(smap["character 2"]["segment_type"], "slow_TTS")
            self.assertEqual(smap["character 1"]["arguments"]["voice"], "Puck")
            self.assertEqual(smap["character 2"]["arguments"]["voice"], "Fenrir")
            self.assertEqual(
                smap["character 2"]["arguments"]["tts_model"],
                "google/gemini-3.1-flash-tts-preview",
            )
            self.assertEqual(
                smap["sound effect"]["segment_type"], "music_generator_foley_agent"
            )

    def test_generation_loop_uses_structured_turns_without_judging(
        self, mock_fs: MagicMock, mock_llm: MagicMock
    ) -> None:
        mock_fs.return_value = MagicMock()
        # Each LlmSession(...) call (setup + 2 slots) must be a distinct object.
        mock_llm.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        with tempfile.TemporaryDirectory() as tmp:
            params = {**self._params(), "target_turn_count": 2}
            agent = ImprovAgent(params, {"output_folder": tmp}, "improv")

            turns = [
                ImprovTurn(dialog="A: Hello!", stage_direction="smiles", sfx_cues=["cup clink"]),
                ImprovTurn(dialog="Right back at you", sfx_cues=[]),
            ]
            for sess, turn in zip(agent.slot_sessions, turns):
                sess.run_structured = MagicMock(return_value=turn)

            segments, script = agent._generation_loop(_make_scene())

            speakers = [s["speaker"] for s in segments]
            self.assertEqual(speakers[0], "background")
            self.assertIn("character 1", speakers)
            self.assertIn("character 2", speakers)
            self.assertIn("sound effect", speakers)

            # Leaked "A:" prefix stripped from character 1 dialog.
            char1 = next(s for s in segments if s["speaker"] == "character 1")
            self.assertEqual(char1["dialog"], "Hello!")

            sfx = next(s for s in segments if s["speaker"] == "sound effect")
            self.assertEqual(sfx["sfx_search_query"], "cup clink")

            # No judgement records in the audit log.
            self.assertTrue(all("judgement" not in row for row in agent.audit_log))
            turn_rows = [r for r in agent.audit_log if r.get("phase") == "turn"]
            self.assertEqual(len(turn_rows), 2)
            self.assertIn("Hello", script)


class TestSegmentTypeMapVariable(unittest.TestCase):
    @patch("llm_from_here.plugins.freesoundfetch.FreeSoundFetch")
    def test_resolves_from_global_results(self, _mock_fs: MagicMock) -> None:
        tmp = tempfile.mkdtemp()
        try:
            ext_map = {
                "character 1": {"segment_type": "slow_TTS", "arguments": {"voice": "Puck"}},
                "default": {"segment_type": "slow_TTS", "arguments": {}},
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
            self.assertEqual(
                stt._segment_type_map()["character 1"]["arguments"]["voice"], "Puck"
            )
        finally:
            os.rmdir(tmp)


class TestSlowTtsReceivesVoiceArgs(unittest.TestCase):
    @patch("llm_from_here.plugins.freesoundfetch.FreeSoundFetch")
    def test_slow_tts_passes_voice_and_model(self, _mock_fs: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            params = {
                "segments_object": "segs",
                "segment_type_key": "speaker",
                "segment_value_key": "dialog",
                "segment_type_map": {},
                "segment_transition_map": [],
            }
            stt = SegmentsToTimeline(params, {"output_folder": tmp}, "test")
            stt.show_tts = MagicMock()
            out = os.path.join(tmp, "line.wav")
            stt.slow_TTS("Hello world", out, voice="Puck", tts_model="google/gemini-3.1-flash-tts-preview")
            stt.show_tts.speak.assert_called_once_with(
                "Hello world",
                out,
                fast=False,
                voice="Puck",
                model="google/gemini-3.1-flash-tts-preview",
            )


if __name__ == "__main__":
    unittest.main()
