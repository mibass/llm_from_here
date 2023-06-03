import unittest
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4
import sys
sys.path.append('../src')  # Add plugins directory to the sys path
from supaSet import SupaSet
import supaSet

class TestSupaSet(unittest.TestCase):
    
    @classmethod
    @patch('supaSet.create_client')
    def setUpClass(cls, mock_create_client):
        mock_create_client.return_value = MagicMock()  # Return a mock client instead of a real one
        cls.set_name = 'test_set'
        cls.supaset = SupaSet(cls.set_name)

    def test_add(self):
        self.supaset._table().insert().execute = MagicMock()  # Mock the chained methods
        self.supaset.add('test_value')
        self.supaset._table().insert().execute.assert_called_once()  # Check if the mock method was called

    def test_remove(self):
        self.supaset._table().delete().eq().eq().eq().execute = MagicMock()  # Mock the chained methods
        self.supaset.remove('test_value')
        self.supaset._table().delete().eq().eq().eq().execute.assert_called_once()  # Check if the mock method was called

    def test_complete_session(self):
        self.supaset._table().update().eq().eq().execute = MagicMock()  # Mock the chained methods
        self.supaset.complete_session()
        self.supaset._table().update().eq().eq().execute.assert_called_once()  # Check if the mock method was called

    def test_cleanup_incomplete_sessions(self):
        self.supaset._table().delete().eq().eq().execute = MagicMock()  # Mock the chained methods
        self.supaset._cleanup_incomplete_sessions()
        self.supaset._table().delete().eq().eq().execute.assert_called_once()  # Check if the mock method was called

    def test_elements(self):
        self.supaset._table().select().eq().execute = MagicMock(return_value=MagicMock(data=[{'value': 'test_value'}]))  # Mock the chained methods and their return value
        elements = self.supaset.elements()
        self.assertEqual(elements, ['test_value'])  # Check if the method returns the expected result

    def test_contains(self):
        self.supaset._table().select().eq().eq().execute = MagicMock(return_value=MagicMock(data=[{'value': 'test_value'}]))  # Mock the chained methods and their return value
        contains = self.supaset.__contains__('test_value')
        self.assertTrue(contains)  # Check if the method returns the expected result

if __name__ == '__main__':
    unittest.main()
    # from dotenv import load_dotenv
    # load_dotenv(dotenv_path='../.env')
    # s1 = SupaSet('test_set')
    # print(s1.add('test_value2'))
    # s1.complete_session()