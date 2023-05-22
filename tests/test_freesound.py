import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from freesound import Sound

# Add the source directory to the system path
sys.path.append('../src/plugins')
from freesoundfetch import FreeSoundFetch  # Assuming the class is in the freesound module

class TestFreeSound(unittest.TestCase):
    def setUp(self):
        # Mock the Freesound API key
        os.environ['FREESOUND_API_KEY'] = 'mock_key'
        self.free_sound = FreeSoundFetch()

    @patch.object(FreeSoundFetch, 'search_samples')
    def test_search_and_download_top_samples(self, mock_search_samples):
        # Mock the sound object returned by the Freesound API
        mock_sound = MagicMock(spec=Sound)
        mock_sound.name = "mock_sound"
        mock_sound.avg_rating = 5.0
        mock_search_samples.return_value = [mock_sound]

        # Test the method
        self.free_sound.search_and_download_top_samples('query', num_samples=1)
        self.assertEqual(self.free_sound.get_temp_file_names(), ['./mock_sound.wav'])

    @patch.object(FreeSoundFetch, 'search_samples')
    def test_execute(self, mock_search_samples):
        # Mock the sound object returned by the Freesound API
        mock_sound = MagicMock(spec=Sound)
        mock_sound.name = "mock_sound"
        mock_sound.avg_rating = 5.0
        mock_search_samples.return_value = [mock_sound]

        # Test the method
        params = {'query': 'query', 'num_samples': 1}
        global_params = {}
        result = self.free_sound.execute(params, global_params, 'test')
        self.assertEqual(result, {'temp_files': ['./mock_sound.wav']})


if __name__ == '__main__':
    unittest.main()
