import unittest
from unittest.mock import Mock, MagicMock, patch
from llm_from_here.plugins.intro import Intro, validate_json_response, filter_guests_count, match_categories
import json

class TestIntro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_supaset_patcher = patch('llm_from_here.plugins.intro.SupaSet')
        cls.mock_supaset = cls.mock_supaset_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.mock_supaset_patcher.stop()
        
    def setUp(self):
        self.params = {
            'system_message': 'Hello',
            'script_prompt': 'Intro script',
            'json_script_prompt': 'Json intro',
            'json_script_prompt_js': {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string"},
                        "dialog": {"type": "string"}
                    },
                    "required": ["speaker", "dialog"]
                }
            },
            'guests_supaset_autoexpire_days': 90,
            'json_guest_prompt': 'Json guests',
            'json_guest_prompt_js': {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "guest_category": {"type": "string"},
                        "guest_name": {"type": "string"}
                    },
                    "required": ["guest_category", "guest_name"]
                }
            },
            'extra_prompts': [{'name': 'test_name', 'prompt': 'test_prompt'}]  # add this line
        }
        self.global_params = {}
        self.plugin_instance_name = 'test_plugin'
        self.chat_app = Mock()
        # Different return values for different chat_app.chat calls.
        self.chat_app.chat.side_effect = [
            'script_response',
            'extra_prompt_response',
            'extra_prompt_response'
        ]
        self.chat_app.enforce_json_response.side_effect = [
            json.loads('[{"speaker": "test_speaker", "dialog": "test_dialog"}]'),
            json.loads('[{"guest_category": "test_category", "guest_name": "test_name"}]')
        ]
        # Get the mock instance of the SupaSet class
        # Get the mock instance of the SupaSet class
        supaset_mock = self.mock_supaset.return_value
        
        # Mock the behavior of the SupaSet methods as needed
        supaset_mock.add.return_value = True
        supaset_mock.elements.return_value = ['Guest1', 'Guest2']
        

    def test_init(self):
        intro = Intro(self.params, self.global_params, self.plugin_instance_name, self.chat_app)
        self.assertEqual(intro.chat_app, self.chat_app)
        self.assertEqual(intro.params, self.params)
        self.assertEqual(intro.global_params, self.global_params)
        self.assertEqual(intro.plugin_instance_name, self.plugin_instance_name)
        
    def test_validate_required_params_missing(self):
        with self.assertRaises(Exception):
            Intro({}, self.global_params, self.plugin_instance_name, self.chat_app)

    def test_validate_required_params(self):
        intro = Intro(self.params, self.global_params, self.plugin_instance_name, self.chat_app)
        intro.validate_required_params()

    def test_get_extra_prompt_responses(self):
        intro = Intro(self.params, self.global_params, self.plugin_instance_name, self.chat_app)
        responses = intro.get_extra_prompt_responses()
        self.assertEqual(responses, {'test_name': 'extra_prompt_response'})

    def test_execute(self):
        intro = Intro(self.params, self.global_params, self.plugin_instance_name, self.chat_app)
        result = intro.execute()
        self.assertEqual(result["chat_app"], self.chat_app)
        self.assertIsInstance(result["script"], str)
        self.assertIsInstance(result["intro"], list)
        self.assertIsInstance(result["guests"], list)
        self.assertIsInstance(result["extra_prompt_responses"], dict)

class TestFunctions(unittest.TestCase):

    def test_validate_json_response(self):
        response = [{"speaker": "speaker1", "dialog": "hello"}]
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "dialog": {"type": "string"}
                },
                "required": ["speaker", "dialog"]
            }
        }
        self.assertTrue(validate_json_response(response, schema))

    def test_filter_guests_count_single(self):
        guests = [{"guest_category": "cat1", "guest_name": "guest1"}, {"guest_category": "cat1", "guest_name": "guest2"}]
        max_occurrences_dict = {"cat1": 1}
        filtered_guests = filter_guests_count(guests, max_occurrences_dict)
        self.assertEqual(filtered_guests, [guests[0]])

    def test_filter_guests_count_multiple(self):
        guests = [{"guest_category": "cat1", "guest_name": "guest1"}, {"guest_category": "cat2", "guest_name": "guest2"}]
        max_occurrences_dict = {"cat1": 2}
        filtered_guests = filter_guests_count(guests, max_occurrences_dict)
        self.assertEqual(filtered_guests, guests)

    def test_match_categories_no_replacement(self):
        guest_list = [{"guest_category": "cat1", "guest_name": "guest1"}, {"guest_category": "cat2", "guest_name": "guest2"}]
        standard_categories = ["cat1", "cat2", "cat3"]
        replacement_map = match_categories(guest_list, standard_categories)
        self.assertEqual(replacement_map, {})

    def test_match_categories_with_replacement(self):
        guest_list = [{"guest_category": "cat10", "guest_name": "guest1"}, {"guest_category": "cat20", "guest_name": "guest2"}]
        standard_categories = ["cat1", "cat2", "cat3"]
        replacement_map = match_categories(guest_list, standard_categories)
        self.assertEqual(replacement_map, {"cat10": ["cat1"], "cat20": ["cat2"]})

if __name__ == "__main__":
    unittest.main()
