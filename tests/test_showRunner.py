
import os
import unittest
import yaml
import sys
import types
from unittest.mock import patch, mock_open, call, MagicMock
import unittest.mock as mock


sys.path.append('../src')  # Add plugins directory to the sys path
sys.path.append('../src/plugins')
import showRunner

class TestShowRunner(unittest.TestCase):

    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_get_last_run_count(self, mock_listdir, mock_isdir):
        mock_listdir.return_value = ['TestShow_run1', 'TestShow_run2', 'TestShow_run3']
        mock_isdir.return_value = True
        self.assertEqual(showRunner.get_last_run_count('TestShow'), 3)

    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_get_last_run_count_no_previous_runs(self, mock_listdir, mock_isdir):
        mock_listdir.return_value = []
        mock_isdir.return_value = True
        self.assertEqual(showRunner.get_last_run_count('TestShow'), 0)

    @patch("builtins.open", new_callable=mock_open)
    def test_execute_plugins(self, mock_open):
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

        # Mock the yaml.load function to return the mocked data
        with patch("yaml.load") as mock_load:
            mock_load.return_value = mocked_data
            
            # Mock import_module to return a dummy module
            with patch('importlib.import_module') as mock_import_module:
                mock_import_module.return_value = MagicMock()

                # Mock the get_last_run_count function to always return 2
                with patch('showRunner.get_last_run_count', return_value=2):
                    # Just call the function and assert that no exception is raised
                    try:
                        showRunner.execute_plugins(self.yaml_file)
                    except Exception as e:
                        self.fail(f'execute_plugins raised an exception: {e}')


if __name__ == '__main__':
    unittest.main()

