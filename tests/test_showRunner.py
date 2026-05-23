import hashlib
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import unittest.mock as mock
import llm_from_here.showRunner as showRunner

class TestShowRunner(unittest.TestCase):

    def test_plugin_cache_entry_hash_stable_without_guests_parameter(self):
        entry = {"plugin": "p", "class": "C", "cache": True, "params": {}}
        gr = {"guest_selection_guests": [{"guest_name": "A"}]}
        h1 = showRunner.plugin_cache_entry_hash(entry, gr)
        h2 = showRunner.plugin_cache_entry_hash(entry, gr)
        self.assertEqual(h1, h2)
        self.assertEqual(h1, hashlib.md5(str(entry).encode()).hexdigest())

    def test_plugin_cache_entry_hash_changes_with_guest_list(self):
        entry = {
            "plugin": "introFromGuestlist",
            "class": "IntroFromGuestlist",
            "cache": True,
            "params": {"guests_parameter": "guest_selection_guests"},
        }
        gr_a = {"guest_selection_guests": [{"guest_name": "Pat", "guest_category": "music"}]}
        gr_b = {"guest_selection_guests": [{"guest_name": "Sam", "guest_category": "music"}]}
        self.assertNotEqual(
            showRunner.plugin_cache_entry_hash(entry, gr_a),
            showRunner.plugin_cache_entry_hash(entry, gr_b),
        )

    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_get_last_run_count(self, mock_listdir, mock_isdir):
        mock_listdir.return_value = ['TestShow_run1', 'TestShow_run2', 'TestShow_run3']
        mock_isdir.return_value = True
        self.assertEqual(showRunner.get_last_run_count('TestShow', '.'), 3)

    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_get_last_run_count_no_previous_runs(self, mock_listdir, mock_isdir):
        mock_listdir.return_value = []
        mock_isdir.return_value = True
        self.assertEqual(showRunner.get_last_run_count('TestShow', '.'), 0)

    def test_execute_plugins(self):
        self.yaml_file = "test_config.yaml"
        
        # Mocked data read from YAML file
        mocked_data = {
            'show_name': 'TestShow',
            'global_parameters': {},
            'plugins': [
                {
                    'plugin': 'test_plugin',
                    'class': 'TestClass',
                    'params': {},
                    'name': '',
                    'cache': False,
                    'retries': 1
                },
                # Add more plugins as needed
            ]
        }
        
        # get a temporary directory to use as the output directory
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(showRunner, "load_yaml", return_value=mocked_data):
                # Mock import_module to return a dummy module
                with patch('importlib.import_module') as mock_import_module:
                    mock_import_module.return_value = MagicMock()

                    # Mock the get_last_run_count function to always return 2
                    with patch('llm_from_here.showRunner.get_last_run_count', return_value=2):
                        # Just call the function and assert that no exception is raised
                        try:
                            showRunner.execute_plugins(self.yaml_file, outputs_dir=temp_dir)
                        except Exception as e:
                            self.fail(f'execute_plugins raised an exception: {e}')
                        logs = list(Path(temp_dir).rglob("showRunner.log"))
                        self.assertEqual(len(logs), 1, msg="run log should live under output_dir")
                        self.assertGreater(logs[0].stat().st_size, 0)


if __name__ == '__main__':
    unittest.main()

