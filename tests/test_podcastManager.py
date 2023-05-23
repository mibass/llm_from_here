import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import sys


sys.path.append('../src')  # Add plugins directory to the sys path
sys.path.append('../src/plugins')
from podcastManager import PodcastManager


class TestPodcastManager(unittest.TestCase):
    def setUp(self):
        params = {}
        global_results = {}
        plugin_instance_name = 'test_plugin'
        self.podcast_manager = PodcastManager(params, global_results, plugin_instance_name)

    @patch('podcastManager.Template') 
    def test_generate_description(self, mock_template):
        mock_template.return_value.render.return_value = 'Test Description'
        self.podcast_manager.podcast_description_template = 'test_template'
        result = self.podcast_manager.generate_description([],'')
        self.assertEqual(result, 'Test Description')

    @patch('podcastManager.Template')
    def test_generate_podcast_title(self, mock_template):
        mock_template.return_value.render.return_value = 'Test Title'
        self.podcast_manager.podcast_title_template = 'test_template'
        result = self.podcast_manager.generate_podcast_title(1)
        self.assertEqual(result, 'Test Title')

    @patch('podcastManager.Template')
    def test_generate_file_name(self, mock_template):
        mock_template.return_value.render.return_value = 'Test File Name'
        self.podcast_manager.podcast_file_name_final_template = 'test_template'
        self.podcast_manager.get_latest_episode_number = MagicMock(return_value=1)
        result = self.podcast_manager.generate_file_name(datetime.today())
        self.assertEqual(result, 'Test File Name')

    @patch('podcastManager.feedparser.parse')
    def test_get_latest_episode_number(self, mock_parse):
        class MockEntry:
            def __init__(self, title):
                self.title = title

        mock_parse.return_value.entries = [MockEntry('Episode 1'), MockEntry('Episode 2')]
        self.podcast_manager.podcast_feed_url = 'test_feed_url'
        result = self.podcast_manager.get_latest_episode_number()
        self.assertEqual(result, 2)

    @patch('podcastManager.shutil.copy')
    @patch('podcastManager.os.path.dirname')
    @patch('podcastManager.os.path.join')
    def test_copy_file_to_final_destination(self, mock_join, mock_dirname, mock_copy):
        self.podcast_manager.generate_file_name = MagicMock(return_value='test_final_file_name')
        mock_dirname.return_value = 'test_directory'
        mock_join.return_value = 'test_final_file_path'
        self.podcast_manager.file_name = 'test_file_name'
        result = self.podcast_manager.copy_file_to_final_destination(datetime.today())
        self.assertEqual(result, 'test_final_file_path')


if __name__ == '__main__':
    unittest.main()
