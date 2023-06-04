import unittest
from unittest.mock import Mock
from llm_from_here.plugins.intro import Intro, validate_json_response, filter_guests_count, match_categories

class TestIntro(unittest.TestCase):

    def setUp(self):
        self.params = {
            'system_message': 'Hello',
            'script_prompt': 'Intro script',
            'json_script_prompt': 'Json intro',
            'json_guest_prompt': 'Json guests',
            'extra_prompts': [{'name': 'test_name', 'prompt': 'test_prompt'}]  # add this line
        }
        self.global_params = {}
        self.plugin_instance_name = 'test_plugin'
        self.chat_app = Mock()
        # Different return values for different chat_app.chat calls.
        self.chat_app.chat.side_effect = [
            'script_response',
            '[{"speaker": "test_speaker", "dialog": "test_dialog"}]',
            '[{"guest_category": "test_category", "guest_name": "test_name"}]',
            'extra_prompt_response',
            'extra_prompt_response'
        ]

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
