import unittest
from unittest.mock import patch, MagicMock, Mock, call
import os
import shutil
import yaml
import tempfile
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
        chris thile:
          segment_type: fast_TTS
        audience:
          segment_type: applause_generator
        intro_name:
          segment_type: fast_TTS
        intro_applause:
          segment_type: applause_generator
      segment_transition_map:
        audience:
          music:
            overlay_percentage: 25
        music:
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
        self.assertIsNotNone(self.stt.show_tts)
        self.assertIsNotNone(self.stt.freesound_fetch)
        self.assertIsNotNone(self.stt.yt_fetch)
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
            {'speaker': 'chris thile', 'dialog': 'dialog1'},
            {'speaker': 'audience', 'dialog': 'dialog2'},
        ]
        output_folder = tempfile.mkdtemp()

        # Mock the necessary methods and attributes
        self.stt.applause_generator = MagicMock()
        self.stt.fast_TTS = MagicMock()
        self.stt.timeline = MagicMock()
        self.stt.applause_generator = MagicMock()
        self.stt.freesound_fetch = MagicMock()
        self.stt.chat_app_object = MagicMock()
        self.stt.show_tts = MagicMock()
        self.stt.youtube_playlist = MagicMock()

        # Call the method under test
        self.stt.generate_audio_segments(
            data, output_folder, self.mock_params, self.mock_plugin_instance_name)

        # Assert that the expected methods were called with the correct arguments
        self.stt.applause_generator.assert_called_once_with(
            'dialog2', os.path.join(output_folder, 'test_instance_002.wav'))
        self.stt.fast_TTS.assert_called_once_with(
            'dialog1', os.path.join(output_folder, 'test_instance_001.wav'))
        self.stt.youtube_playlist.assert_called_once()

        # Clean up the temporary directory
        shutil.rmtree(output_folder)

    @patch('llm_from_here.plugins.audioTimeline.AudioTimeline')
    def test_execute(self, mock_audio_timeline):
        # Mock the audio timeline instance and its methods
        mock_timeline_instance = self.stt.timeline
        mock_audio_timeline.return_value = mock_timeline_instance

        # Call the method under test
        result = self.stt.execute()

        # Assert that the audio timeline instance is used and the correct result is returned
        self.assertEqual(result['timeline'], mock_timeline_instance)


if __name__ == '__main__':
    unittest.main()
