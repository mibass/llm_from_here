import unittest
from unittest.mock import patch, MagicMock
from llm_from_here.plugins.podbeanManager import PodbeanManager

class TestPodbeanManager(unittest.TestCase):
    @patch('os.getenv')
    @patch('requests.post')
    @patch('requests.get')
    def setUp(self, mock_get, mock_post, mock_getenv):
        # Mock the environment variables
        mock_getenv.return_value = 'test'
        
        # Set up a successful response for getting access token
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'access_token': 'test_token'}
        
        # Set up a successful response for getting episodes
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'episodes': []}
        
        params = {'description_variable': 'desc', 'title_variable': 'title', 
                  'file_path_variable': 'path', 'episode_number_variable': '1'}
        global_results = {'desc': 'Test description', 'title': 'Test title', 'path': 'test_path', '1': '1'}
        
        self.pbm = PodbeanManager(params, global_results, 'plugin_instance_name')
        
    @patch('requests.post')
    def test_get_access_token(self, mock_post):
        # Mock the post request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'access_token': 'fake_token'}

        self.pbm.get_access_token()
        self.assertEqual(self.pbm.access_token, 'fake_token')


    @patch('requests.get')
    def test_get_episodes(self, mock_get):
        # Mock the get request
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'episodes': ['Episode 1', 'Episode 2', 'Episode 3']}

        self.pbm.get_episodes()
        self.assertEqual(len(self.pbm.episodes), 3)


    @patch('requests.put')
    @patch('builtins.open', new_callable=MagicMock)
    @patch('os.path.getsize')
    @patch('mimetypes.guess_type')
    @patch('requests.get')
    def test_upload_episode(self, mock_get, mock_mimetype, mock_getsize, mock_open, mock_put):
        # Assume that the number of episodes is less than the maximum number of episodes
        # Mock the guess_type to return a valid mimetype
        mock_mimetype.return_value = ('text/plain', 'utf-8')
        # Mock getsize to return a valid size
        mock_getsize.return_value = 10
        # Mock put request for file upload
        mock_put.return_value.status_code = 200
        # Mock open function
        mock_open.return_value.__enter__.return_value = 'file_object'
        # Mock get request for upload authorization
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'presigned_url': 'presigned_url_test', 'expire_at': 'expire_at_test', 'file_key': 'file_key_test'}

        self.pbm.upload_episode()
        self.assertTrue(mock_put.called)


    @patch('requests.post')
    def test_publish_episode(self, mock_post):
        # Set up a successful response for publishing episode
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'result': 'success'}

        result = self.pbm.publish_episode('title', 'content', 'status', 'episode_type')
        self.assertEqual(result, {'result': 'success'})

if __name__ == "__main__":
    unittest.main()