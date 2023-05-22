import unittest
from unittest.mock import patch, Mock
import json
import sys

sys.path.append('../src/plugins')
import intro

class TestIntro(unittest.TestCase):

    def setUp(self):
        self.intro = intro.Intro()
        self.params = {
            'system_message': 'Welcome',
            'script_prompt': 'Script',
            'json_script_prompt': 'JSON Script',
            'json_guest_prompt': 'JSON Guests',
            'extra_prompts': [{'name': 'Extra', 'prompt': 'Extra Prompt'}],
            'guest_categories': ['Standard'],
            'guest_name_filters': ['Filter'],
            'guest_count_filters': {'Standard': 2}
        }
        self.global_params = {}
        self.plugin_instance_name = "Test Instance"

    @patch('intro.gpt.ChatApp')
    @patch('intro.validate_json_response')
    @patch('intro.match_categories')
    @patch('intro.filter_guests_count')
    def test_execute(self, mock_filter_guests_count, mock_match_categories, mock_validate_json_response, mock_chat_app):
        mock_chat = Mock()
        mock_chat_app.return_value = mock_chat
        # Add another element to side_effect to account for the extra call
        mock_chat.chat.side_effect = ['Chat Response', 
                                    json.dumps([{'speaker': 'Speaker', 'dialog': 'Dialog'}]), 
                                    json.dumps([{'guest_category': 'Standard', 'guest_name': 'Guest'}]),
                                    'Extra Chat Response']
        mock_validate_json_response.return_value = True
        mock_match_categories.return_value = {}
        mock_filter_guests_count.return_value = [{'guest_category': 'Standard', 'guest_name': 'Guest'}]

        result = self.intro.execute(self.params, self.global_params, self.plugin_instance_name)

        self.assertEqual(result['script'], 'Chat Response')
        self.assertEqual(result['intro'], [{'speaker': 'Speaker', 'dialog': 'Dialog'}])
        self.assertEqual(result['guests'], [{'guest_category': 'Standard', 'guest_name': 'Guest'}])
        self.assertEqual(result['extra_prompt_responses'], {'Extra': 'Extra Chat Response'})
        self.assertEqual(result['chat_app'], mock_chat)

    def test_validate_json_response(self):
        response = [{'speaker': 'Speaker', 'dialog': 'Dialog'}]
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

        self.assertTrue(intro.validate_json_response(response, schema))

    def test_filter_guests_count(self):
        guests = [
            {'guest_category': 'Standard', 'guest_name': 'Guest1'},
            {'guest_category': 'Standard', 'guest_name': 'Guest1'},
            {'guest_category': 'VIP', 'guest_name': 'Guest3'}
        ]
        max_occurrences_dict = {'Standard': 1}

        filtered_guests = intro.filter_guests_count(guests, max_occurrences_dict)
        self.assertEqual(len(filtered_guests), 2)

    def test_match_categories(self):
        guest_list = [{'guest_category': 'standard', 'guest_name': 'Guest'}]
        standard_categories = ['standard']

        replacement_map = intro.match_categories(guest_list, standard_categories)

        self.assertEqual(replacement_map, {})
        self.assertEqual(guest_list[0]['guest_category'], 'standard')


if __name__ == '__main__':
    unittest.main()
