import json
import gpt
from jsonschema import validate
from jsonschema.exceptions import ValidationError
import logging
import sys
import fnmatch
from collections import Counter
from fuzzywuzzy import process

from common import log_exception

logger = logging.getLogger(__name__)

def validate_json_response(response, schema):
    try:
        validate(instance=response, schema=schema)
        return True
    except ValidationError as e:
        logger.error(f"Validation Error: {e.message}")
        logger.error(f"Actual response: {response}")
        logger.error(f"Expected schema: {schema}")
        raise e


def filter_guests_count(guests, max_occurrences_dict):
    # Count the occurrences of each guest category
    category_counter = Counter()

    # Filter the list based on the maximum occurrences
    filtered_guests = []
    for guest in guests:
        category = guest['guest_category']
        max_occurrences = max_occurrences_dict.get(category)
        if max_occurrences is None or category_counter[category] < max_occurrences:
            filtered_guests.append(guest)
            category_counter[category] += 1

    return filtered_guests


def match_categories(guest_list, standard_categories):
    replacement_map = {}

    for guest in guest_list:
        original_category = guest['guest_category']
        matched_category = process.extractOne(guest['guest_category'].lower(), standard_categories)[0]
        guest['guest_category'] = matched_category

        if original_category.lower() != matched_category:
            if original_category in replacement_map:
                if matched_category not in replacement_map[original_category]:
                    replacement_map[original_category].append(matched_category)
            else:
                replacement_map[original_category] = [matched_category]

    return replacement_map


class Intro:
    def __init__(self, params, global_params, plugin_instance_name, chat_app=None):
        self.chat_app = chat_app or gpt.ChatApp(params['system_message'])
        self.params = params
        self.global_params = global_params
        self.plugin_instance_name = plugin_instance_name

        self.intro_schema = {
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
        self.guests_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "guest_category": {"type": "string"},
                    "guest_name": {"type": "string"}
                },
                "required": ["guest_category", "guest_name"]
            }
        }

        self.validate_required_params()
        self.script = self.chat_app.chat(params['script_prompt'])
        self.intro = json.loads(self.chat_app.chat(params['json_script_prompt']))
        self.guests = json.loads(self.chat_app.chat(params['json_guest_prompt']))

        self.extra_prompt_responses = self.get_extra_prompt_responses()
        self.validate_json_response()
        self.normalize_guest_categories()
        self.apply_guest_list_filter()
        self.apply_guest_count_filter()

    def validate_required_params(self):
        required_params = ['system_message', 'script_prompt', 'json_script_prompt', 'json_guest_prompt']
        for required_param in required_params:
            if required_param not in self.params:
                logger.error(f"Required parameter {required_param} not found in params.")
                raise Exception(f"Required parameter {required_param} not found in params.")

    def get_extra_prompt_responses(self):
        extra_prompts = self.params.get('extra_prompts', [{}])
        extra_prompt_responses = {}
        for prompt in extra_prompts:
            logger.info(f"Running extra_prompt: {prompt}")
            extra_prompt_responses[prompt['name']] = self.chat_app.chat(prompt['prompt'])
            logger.info(f"Extra prompt response: {extra_prompt_responses[prompt['name']]}")
        return extra_prompt_responses

    def validate_json_response(self):
        validate_json_response(self.intro, self.intro_schema)
        validate_json_response(self.guests, self.guests_schema)

    def normalize_guest_categories(self):
        guest_categories = self.params.get('guest_categories', [])
        if guest_categories != []:
            logger.info("Normalizing guest categories")
            updates = match_categories(self.guests, guest_categories)
            if updates != {}:
                logger.warning(f"Guest categories replacements made: {updates}")

    def apply_guest_list_filter(self):
        guest_filter = self.params.get('guest_name_filters', [])
        if guest_filter != []:
            logger.info(f"Found guests filter: {guest_filter}")
            original_guests = self.guests
            self.guests = [
                guest for guest in self.guests if not any(
                    fnmatch.fnmatch(guest['guest_name'].lower(), pattern.lower())
                    for pattern in guest_filter
                )
            ]
            if len(original_guests) != len(self.guests):
                removed_guests = list(set(original_guests) - set(self.guests))
                logger.info(f"Guests list filter applied. Guests removed: {removed_guests}")

    def apply_guest_count_filter(self):
        guest_count_filter = self.params.get('guest_count_filters', {})
        if guest_count_filter != {}:
            self.guests = filter_guests_count(self.guests, guest_count_filter)
            logger.info(f"Guests is now: {self.guests}")
    
    @log_exception(logger.error)
    def check_guests(self):
        assert len(self.guests) > 0, "Number of guests must be greater than zero."

    def execute(self):
        self.check_guests()

        result = {
            "script": self.script,
            "intro": self.intro,
            "guests": self.guests,
            "extra_prompt_responses": self.extra_prompt_responses,
            "chat_app": self.chat_app
        }

        return result

