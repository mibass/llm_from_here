import unittest
import os
import tempfile
from llm_from_here.pickleDict import PickleDict

class PickleDictTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.file_path = os.path.join(self.temp_dir.name, 'test_dict.pickle')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_set_get_item(self):
        test_dict = PickleDict(self.file_path)
        test_dict['key1'] = 'value1'
        self.assertEqual(test_dict['key1'], 'value1')

    def test_del_item(self):
        test_dict = PickleDict(self.file_path)
        test_dict['key1'] = 'value1'
        del test_dict['key1']
        with self.assertRaises(KeyError):
            value = test_dict['key1']

    def test_len(self):
        test_dict = PickleDict(self.file_path)
        self.assertEqual(len(test_dict), 0)
        test_dict['key1'] = 'value1'
        self.assertEqual(len(test_dict), 1)

    def test_iter(self):
        test_dict = PickleDict(self.file_path)
        test_dict['key1'] = 'value1'
        test_dict['key2'] = 'value2'
        keys = ['key1', 'key2']
        for key in test_dict:
            self.assertIn(key, keys)

    def test_keys(self):
        test_dict = PickleDict(self.file_path)
        test_dict['key1'] = 'value1'
        test_dict['key2'] = 'value2'
        self.assertEqual(set(test_dict.keys()), {'key1', 'key2'})

    def test_values(self):
        test_dict = PickleDict(self.file_path)
        test_dict['key1'] = 'value1'
        test_dict['key2'] = 'value2'
        self.assertEqual(set(test_dict.values()), {'value1', 'value2'})

    def test_items(self):
        test_dict = PickleDict(self.file_path)
        test_dict['key1'] = 'value1'
        test_dict['key2'] = 'value2'
        expected_items = {('key1', 'value1'), ('key2', 'value2')}
        self.assertEqual(set(test_dict.items()), expected_items)

    def test_always_autocommit(self):
        test_dict = PickleDict(self.file_path, autocommit=True)
        test_dict['key1'] = 'value1'
        test_dict['key2'] = 'value2'
        self.assertEqual(test_dict['key1'], 'value1')

        test_dict['key1'] = 'new_value'
        test_dict['key3'] = 'value3'

        # Create a new instance to reload from disk
        new_dict = PickleDict(self.file_path)
        self.assertEqual(new_dict['key1'], 'new_value')
        self.assertEqual(new_dict['key2'], 'value2')
        self.assertEqual(new_dict['key3'], 'value3')
        
    def test_clear(self):
        test_dict = PickleDict(self.file_path, autocommit=True)
        test_dict['key1'] = 'value1'
        test_dict['key2'] = 'value2'
        test_dict.clear()
        self.assertEqual(len(test_dict), 0)
        new_dict = PickleDict(self.file_path)
        self.assertEqual(len(new_dict), 0)

if __name__ == '__main__':
    unittest.main()
