import logging
import unittest
from unittest.mock import patch, MagicMock
import os
import shutil
import yaml
import tempfile

from pydub import AudioSegment
from llm_from_here.plugins.segmentsToTimeline import SegmentsToTimeline
import llm_from_here.plugins.audioTimeline as audioTimeline

yaml_string = """
    params:
      segments_object: intro_intro
      segment_type_key: speaker
      segment_value_key: dialog
      segment_type_map:
        music:
          segment_type: youtube_playlist
          background_music: True
          arguments:
            playlist_id: PLE3cjj4L4BWgu8nQtMYbNrGdUA7mpbOKk
        dris thile:
          segment_type: fast_TTS
        audience:
          segment_type: applause_generator
        intro_name:
          segment_type: fast_TTS
        intro_applause:
          segment_type: applause_generator
      segment_transition_map:
        - audience:
            music:
              overlay_percentage: 25
        - music:
            audience:
              overlay_duration: 1
"""


class TestSegmentsToTimeline(unittest.TestCase):

    @patch("llm_from_here.plugins.showTTS.ShowTextToSpeech")
    @patch("llm_from_here.plugins.freesoundfetch.FreeSoundFetch")
    @patch("llm_from_here.plugins.ytfetch.YtFetch")
    def setUp(self, patch_showTTS, patch_freesoundfetch, patch_ytFetch):
        self.mock_params = yaml.safe_load(yaml_string)['params']
        self.mock_segment_transition_map = self.mock_params['segment_transition_map']

        self.mock_global_results = {
            "intro_intro": [{'speaker': 'audience', 'dialog': 'duration 10'},],
            "output_folder": tempfile.mkdtemp(),
            "timeline": MagicMock(spec=audioTimeline.AudioTimeline)}
        self.mock_plugin_instance_name = 'test_instance'
        self.stt = SegmentsToTimeline(
            self.mock_params, self.mock_global_results, self.mock_plugin_instance_name)

    @patch("llm_from_here.plugins.showTTS.ShowTextToSpeech")
    def test_init(self, mock_showTTS):
        self.assertIsNone(self.stt.show_tts)
        self.assertIsNotNone(self.stt.freesound_fetch)
        self.assertIsNone(self.stt.yt_fetch)
        # self.assertIsNotNone(self.stt.chat_app_object)
        self.assertIsNotNone(self.stt.global_results)
        self.assertIsNotNone(self.stt.params)
        self.assertIsNotNone(self.stt.plugin_instance_name)
        self.assertIsNotNone(self.stt.timeline)

    @patch("llm_from_here.plugins.segmentsToTimeline.generate_applause")
    def test_applause_generator(self, mock_generate_applause):
        test_text = "duration 10"
        with tempfile.TemporaryDirectory() as temp_dir:
            test_output_file = os.path.join(temp_dir, "test.wav")
            self.stt.applause_generator(test_text, test_output_file)
            mock_generate_applause.assert_called_once()

    @patch("llm_from_here.plugins.freesoundfetch.FreeSoundFetch.search_and_download_top_samples")
    @patch("llm_from_here.plugins.segmentsToTimeline.os.path.dirname")
    @patch("llm_from_here.plugins.segmentsToTimeline.shutil.move")
    def test_music_generator_freesound(self, mock_move, mock_dirname, mock_search_and_download_top_samples):
        test_text = "[MUSIC Rock]"
        with tempfile.TemporaryDirectory() as temp_dir:
            test_output_file = os.path.join(temp_dir, "test.wav")
            mock_search_and_download_top_samples(test_text, test_output_file)
            mock_search_and_download_top_samples.assert_called_once()

    def test_get_transition_map_entry(self):
        with patch.object(self.stt.timeline, 'get_last_type', return_value='music') as mock_get_last_type:
            result = self.stt.get_transition_map_entry(
                self.mock_segment_transition_map, 'audience')
            self.assertEqual(result, {'overlay_duration': 1})

    def test_generate_audio_segments(self):
        data = [
            {'speaker': 'music', 'dialog': 'music1'},
            {'speaker': 'dris thile', 'dialog': 'dialog1'},
            {'speaker': 'audience', 'dialog': 'dialog2'},
        ]
        self.mock_global_results['intro_intro'] = data
        output_folder = self.mock_global_results['output_folder']

        # Mock the necessary methods and attributes
        self.stt = SegmentsToTimeline(
            self.mock_params, self.mock_global_results, self.mock_plugin_instance_name)

        self.stt.applause_generator = MagicMock()
        self.stt.fast_TTS = MagicMock()
        self.stt.timeline = MagicMock()
        self.stt.applause_generator = MagicMock()
        self.stt.freesound_fetch = MagicMock()
        self.stt.chat_app_object = MagicMock()
        self.stt.show_tts = MagicMock()
        self.stt.youtube_playlist = MagicMock()

        # Call the method under test
        self.stt.generate_audio_segments()

        # Assert that the expected methods were called with the correct arguments
        self.stt.applause_generator.assert_called_once_with(
            'dialog2', os.path.join(output_folder, 'test_instance_002.wav'))
        self.stt.fast_TTS.assert_called_once_with(
            'dialog1', os.path.join(output_folder, 'test_instance_001.wav'))

    def test_generate_audio_segments_dris_thile(self):
        """Intro schema canonicalizes host as Dris Thile; YAML keys must be lowercase."""
        data = [
            {"speaker": "Music", "dialog": "[MUSIC folk intro bed]"},
            {"speaker": "Dris Thile", "dialog": "Welcome to the show."},
            {"speaker": "Audience", "dialog": "[APPLAUSE duration 5]"},
        ]
        params = {
            **self.mock_params,
            "segment_type_map": {
                "music": {
                    "segment_type": "youtube_playlist",
                    "background_music": True,
                    "arguments": {"playlist_id": "PL123"},
                },
                "dris thile": {"segment_type": "slow_TTS"},
                "audience": {"segment_type": "applause_generator"},
            },
        }
        self.mock_global_results["intro_intro"] = data
        output_folder = self.mock_global_results["output_folder"]
        stt = SegmentsToTimeline(
            params, self.mock_global_results, self.mock_plugin_instance_name
        )
        stt.slow_TTS = MagicMock(return_value={})
        stt.applause_generator = MagicMock(return_value=True)
        stt.youtube_playlist = MagicMock(return_value={"title": "bg"})
        stt.timeline = MagicMock()
        stt.generate_audio_segments()
        stt.youtube_playlist.assert_called_once()
        stt.slow_TTS.assert_called_once_with(
            "Welcome to the show.",
            os.path.join(output_folder, "test_instance_001.wav"),
        )
        shutil.rmtree(output_folder)

    def test_single_background_not_blocked_by_foreground_first(self):
        """Foreground segments before background must not mark background_seen early."""
        params = {
            "segments_object": "segments",
            "segment_type_key": "speaker",
            "segment_value_key": "dialog",
            "single_background": True,
            "segment_type_map": {
                "background": {
                    "segment_type": "youtube_search",
                    "background_music": True,
                    "arguments": {},
                },
                "default": {"segment_type": "slow_TTS"},
            },
        }
        output_folder = tempfile.mkdtemp()
        global_results = {
            "segments": [
                {"speaker": "character 1", "dialog": "Opening line"},
                {"speaker": "background", "dialog": "folk"},
            ],
            "output_folder": output_folder,
        }
        stt = SegmentsToTimeline(params, global_results, "story_audio")
        stt.slow_TTS = MagicMock()
        stt.youtube_search = MagicMock(return_value={"title": "bg track"})
        stt.timeline = MagicMock()

        try:
            stt.generate_audio_segments()
            stt.slow_TTS.assert_called_once()
            stt.youtube_search.assert_called_once_with(
                "folk",
                os.path.join(output_folder, "story_audio_001.wav"),
                **{},
            )
        finally:
            shutil.rmtree(output_folder)

    @patch('llm_from_here.plugins.audioTimeline.AudioTimeline')
    def test_execute(self, mock_audio_timeline):
        if shutil.which("ffprobe") is None:
            self.skipTest("ffprobe is required for this test")
        # Mock the audio timeline instance and its methods
        mock_timeline_instance = self.stt.timeline
        mock_audio_timeline.return_value = mock_timeline_instance

        # Call the method under test
        result = self.stt.execute()

        # Assert that the audio timeline instance is used and the correct result is returned
        self.assertEqual(result['timeline'], mock_timeline_instance)
        
    @patch("llm_from_here.plugins.showTTS.ShowTextToSpeech")
    def test_fast_TTS(self, mock_showTTS):
        test_text = "[Hello], world!"
        expected_filtered_text = ", world!"
        with tempfile.TemporaryDirectory() as temp_dir:
            test_output_file = os.path.join(temp_dir, "test.wav")
            self.stt.fast_TTS(test_text, test_output_file)
            mock_showTTS.assert_called_once_with()
            mock_showTTS.return_value.speak.assert_called_once_with(expected_filtered_text, test_output_file, fast=True)

    @patch("llm_from_here.plugins.segmentsToTimeline.is_lyria_enabled", return_value=True)
    @patch("llm_from_here.plugins.segmentsToTimeline.is_openrouter_free_mode", return_value=False)
    @patch("llm_from_here.plugins.segmentsToTimeline.generate_instrumental")
    def test_music_generator_openrouter_calls_lyria(self, mock_generate, mock_free, mock_lyria):
        with tempfile.TemporaryDirectory() as temp_dir:
            out = os.path.join(temp_dir, "bg.wav")
            cue = "[MUSIC Create an approximately 3 minute folk intro. Instrumental only, no vocals.]"
            mock_generate.return_value = {"source": "openrouter_lyria"}
            res = self.stt.music_generator_openrouter(
                cue,
                out,
                fallback_segment_type="youtube_playlist",
                playlist_id="PL123",
            )
            mock_generate.assert_called_once_with(cue, out)
            self.assertEqual(res["source"], "openrouter_lyria")

    @patch("llm_from_here.plugins.segmentsToTimeline.is_openrouter_free_mode", return_value=True)
    @patch("llm_from_here.plugins.segmentsToTimeline.generate_instrumental")
    def test_music_generator_openrouter_free_mode_uses_fallback(self, mock_generate, mock_free):
        self.stt.youtube_playlist = MagicMock(return_value={"title": "fallback"})
        with tempfile.TemporaryDirectory() as temp_dir:
            out = os.path.join(temp_dir, "bg.wav")
            cue = "[MUSIC Create an approximately 3 minute folk intro. Instrumental only, no vocals.]"
            res = self.stt.music_generator_openrouter(
                cue,
                out,
                fallback_segment_type="youtube_playlist",
                playlist_id="PL123",
            )
            mock_generate.assert_not_called()
            self.stt.youtube_playlist.assert_called_once()
            self.assertEqual(res["title"], "fallback")

    @patch("llm_from_here.plugins.segmentsToTimeline.is_lyria_enabled", return_value=False)
    @patch("llm_from_here.plugins.segmentsToTimeline.is_openrouter_free_mode", return_value=False)
    @patch("llm_from_here.plugins.segmentsToTimeline.generate_instrumental")
    def test_music_generator_openrouter_lyria_disabled_uses_fallback(self, mock_generate, mock_free, mock_lyria):
        self.stt.youtube_playlist = MagicMock(return_value={"title": "fallback"})
        with tempfile.TemporaryDirectory() as temp_dir:
            out = os.path.join(temp_dir, "bg.wav")
            cue = "[MUSIC Create a 180-second folk intro. Instrumental only, no vocals.]"
            res = self.stt.music_generator_openrouter(
                cue,
                out,
                fallback_segment_type="youtube_playlist",
                playlist_id="PL123",
            )
            mock_generate.assert_not_called()
            self.stt.youtube_playlist.assert_called_once()
            self.assertEqual(res["title"], "fallback")

    @patch("llm_from_here.plugins.segmentsToTimeline.is_lyria_enabled", return_value=True)
    @patch("llm_from_here.plugins.segmentsToTimeline.is_openrouter_free_mode", return_value=False)
    @patch("llm_from_here.plugins.segmentsToTimeline.generate_instrumental", side_effect=RuntimeError("api down"))
    def test_music_generator_openrouter_failure_falls_back_to_youtube_search(self, mock_generate, mock_free, mock_lyria):
        self.stt.youtube_search = MagicMock(return_value={"title": "yt"})
        with tempfile.TemporaryDirectory() as temp_dir:
            out = os.path.join(temp_dir, "bg.wav")
            cue = (
                "[background: Create an approximately 3 minute acoustic folk underscore. "
                "Fingerpicked guitar, ~88 BPM. Instrumental only, no vocals.]"
            )
            res = self.stt.music_generator_openrouter(
                cue,
                out,
                fallback_segment_type="youtube_search",
                additional_query_text="instrumental live",
                use_music_search=True,
            )
            self.stt.youtube_search.assert_called_once()
            search_args = self.stt.youtube_search.call_args[0]
            self.assertLessEqual(len(search_args[0]), 80)
            self.assertEqual(res["title"], "yt")

    def test_use_agent_dispatches_to_agent_search(self):
        yaml_agent = """
    params:
      use_agent: True
      segments_object: intro_guests
      segment_type_key: guest_category
      segment_value_key: guest_name
      segment_type_map:
        default:
          segment_type: youtube_search
          intro_name: False
          intro_applause: False
          arguments:
            duration_min_sec: 300
            duration_max_sec: 600
      segment_transition_map: []
"""
        mock_global_results = {
            "intro_guests": [{"guest_category": "music", "guest_name": "Pat"}],
            "output_folder": tempfile.mkdtemp(),
        }
        params = yaml.safe_load(yaml_agent)["params"]
        stt = SegmentsToTimeline(params, mock_global_results, "agent_test")

        def _fake_agent(guest_name, output_file, *, guest_category="", **kwargs):
            AudioSegment.silent(duration=3000).export(output_file, format="wav")
            return {"title": "Video Title", "video_url": "http://x", "duration_sec": 3.0}

        stt.agent_search = MagicMock(side_effect=_fake_agent)
        stt.timeline = MagicMock()
        stt.generate_audio_segments()
        stt.agent_search.assert_called_once()
        call_kw = stt.agent_search.call_args.kwargs
        self.assertEqual(call_kw.get("guest_category"), "music")
        shutil.rmtree(mock_global_results["output_folder"])

    def test_segment_type_default_fallback_emits_debug_not_warning(self):
        yaml_agent = """
    params:
      use_agent: True
      segments_object: intro_guests
      segment_type_key: guest_category
      segment_value_key: guest_name
      segment_type_map:
        default:
          segment_type: youtube_search
          intro_name: False
          intro_applause: False
          arguments:
            duration_min_sec: 300
            duration_max_sec: 600
      segment_transition_map: []
"""
        mock_global_results = {
            "intro_guests": [{"guest_category": "music", "guest_name": "Pat"}],
            "output_folder": tempfile.mkdtemp(),
        }
        params = yaml.safe_load(yaml_agent)["params"]
        stt = SegmentsToTimeline(params, mock_global_results, "fallback_test")

        def _fake_agent(guest_name, output_file, *, guest_category="", **kwargs):
            AudioSegment.silent(duration=3000).export(output_file, format="wav")
            return {"title": "Video Title", "video_url": "http://x", "duration_sec": 3.0}

        stt.agent_search = MagicMock(side_effect=_fake_agent)
        stt.timeline = MagicMock()
        log_name = "llm_from_here.plugins.segmentsToTimeline"
        try:
            with self.assertLogs(log_name, level="DEBUG") as cm:
                stt.generate_audio_segments()
            found_debug_fallback = any(
                "No segment_type_map entry" in r.getMessage() for r in cm.records
            )
            self.assertTrue(found_debug_fallback)
            bad_warnings = [
                r
                for r in cm.records
                if r.levelno >= logging.WARNING
                and "No function found for segment type" in r.getMessage()
            ]
            self.assertEqual(bad_warnings, [])
        finally:
            shutil.rmtree(mock_global_results["output_folder"])

    def test_use_agent_false_uses_youtube_dispatch(self):
        """Regression: default path still calls segment_type handler."""
        data = [
            {"speaker": "music", "dialog": "music1"},
        ]
        self.mock_global_results["intro_intro"] = data
        output_folder = self.mock_global_results["output_folder"]
        try:
            self.stt = SegmentsToTimeline(
                self.mock_params, self.mock_global_results, self.mock_plugin_instance_name
            )
            self.assertFalse(self.stt.params.get("use_agent", False))
            self.stt.youtube_playlist = MagicMock(return_value={"title": "t", "video_url": "u"})
            self.stt.timeline = MagicMock()
            self.stt.chat_app_object = MagicMock()
            self.stt.generate_audio_segments()
            self.stt.youtube_playlist.assert_called_once()
        finally:
            shutil.rmtree(output_folder, ignore_errors=True)

    @patch("llm_from_here.plugins.segmentsToTimeline.AudioSegment")
    def test_silence_generator_writes_silent_wav(self, mock_audio_segment):
        silence = mock_audio_segment.silent.return_value
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = os.path.join(temp_dir, "pause.wav")
            self.stt.silence_generator("[SILENCE duration 800]", output_file)
        mock_audio_segment.silent.assert_called_once_with(duration=800)
        silence.export.assert_called_once()


if __name__ == '__main__':
    unittest.main()
