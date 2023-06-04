import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
from llm_from_here.plugins.podcastManager import PodcastManager


class TestPodcastManager(unittest.TestCase):
    def setUp(self):
        params = {}
        global_results = {}
        plugin_instance_name = 'test_plugin'
        self.podcast_manager = PodcastManager(params, global_results, plugin_instance_name)

    @patch('llm_from_here.plugins.podcastManager.Template')
    def test_generate_description(self, mock_template):
        description_text = 'Test Description'
        mock_template.return_value.render.return_value = description_text
        self.podcast_manager.podcast_description_template = 'test_template'
        self.podcast_manager.podcast_description_character_limit = 4  # Limiting the characters to 4
        result = self.podcast_manager.generate_description([], '')
        self.assertEqual(result, description_text[0:self.podcast_manager.podcast_description_character_limit])  # Will check for 'Test'
        
    @patch('llm_from_here.plugins.podcastManager.Template')
    def test_generate_description_no_limit(self, mock_template):
        description_text = 'Test Description'
        mock_template.return_value.render.return_value = description_text
        self.podcast_manager.podcast_description_template = 'test_template'
        self.podcast_manager.podcast_description_character_limit = None  # No limit
        result = self.podcast_manager.generate_description([], '')
        self.assertEqual(result, description_text)  # The entire string should be returned

    @patch('llm_from_here.plugins.podcastManager.Template')
    def test_generate_podcast_title(self, mock_template):
        mock_template.return_value.render.return_value = 'Test Title'
        self.podcast_manager.podcast_title_template = 'test_template'
        result = self.podcast_manager.generate_podcast_title(1)
        self.assertEqual(result, 'Test Title')

    @patch('llm_from_here.plugins.podcastManager.Template')
    def test_generate_file_name(self, mock_template):
        mock_template.return_value.render.return_value = 'Test File Name'
        self.podcast_manager.podcast_file_name_final_template = 'test_template'
        self.podcast_manager.get_latest_episode_number = MagicMock(return_value=1)
        result = self.podcast_manager.generate_file_name(datetime.today())
        self.assertEqual(result, 'Test File Name')

    @patch('llm_from_here.plugins.podcastManager.shutil.copy')
    @patch('llm_from_here.plugins.podcastManager.os.path.dirname')
    @patch('llm_from_here.plugins.podcastManager.os.path.join')
    def test_copy_file_to_final_destination(self, mock_join, mock_dirname, mock_copy):
        self.podcast_manager.generate_file_name = MagicMock(return_value='test_final_file_name')
        mock_dirname.return_value = 'test_directory'
        mock_join.return_value = 'test_final_file_path'
        self.podcast_manager.file_name = 'test_file_name'
        result = self.podcast_manager.copy_file_to_final_destination(datetime.today())
        self.assertEqual(result, 'test_final_file_path')
        
    @patch('llm_from_here.plugins.podcastManager.feedparser.parse')
    def test_get_latest_episode_number_no_feed(self, mock_parse):
        mock_parse.return_value.entries = []
        self.podcast_manager.podcast_feed_url = 'test_feed_url'
        result = self.podcast_manager.get_latest_episode_number()
        self.assertEqual(result, 0)

    @patch('llm_from_here.plugins.podcastManager.feedparser.parse')
    def test_get_latest_episode_number(self, mock_parse):
        class MockEntry:
            def __init__(self, title):
                self.title = title

        class MockFeed:
            def __init__(self, entries, status=200):
                self.entries = entries
                self.status = status

        mock_parse.return_value = MockFeed([MockEntry('Episode 1'), MockEntry('Episode 2')])
        self.podcast_manager.podcast_feed_url = 'test_feed_url'
        result = self.podcast_manager.get_latest_episode_number()
        self.assertEqual(result, 2)

    @patch('llm_from_here.plugins.podcastManager.logger.warning')
    @patch('llm_from_here.plugins.podcastManager.feedparser.parse')
    def test_get_latest_episode_number_no_feed(self, mock_parse, mock_warning):
        class MockFeed:
            def __init__(self, entries=[], status=200):
                self.entries = entries
                self.status = status

        mock_parse.return_value = MockFeed()
        self.podcast_manager.podcast_feed_url = 'test_feed_url'
        result = self.podcast_manager.get_latest_episode_number()
        self.assertEqual(result, 0)
        mock_warning.assert_called_once_with('Feed is empty')

    @patch('llm_from_here.plugins.podcastManager.feedparser.parse')
    def test_get_latest_episode_number_unresponsive_url(self, mock_parse):
        class MockFeed:
            def __init__(self, entries=[], status=404):
                self.entries = entries
                self.status = status

        mock_parse.return_value = MockFeed()
        self.podcast_manager.podcast_feed_url = 'test_feed_url'
        with self.assertRaises(Exception) as context:
            self.podcast_manager.get_latest_episode_number()
        self.assertEqual(str(context.exception), 'Failed to retrieve feed, HTTP status: 404')



if __name__ == '__main__':
    unittest.main()
