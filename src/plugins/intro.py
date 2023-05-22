import json
import gpt
from jsonschema import validate
from jsonschema.exceptions import ValidationError
import logging
import sys
import fnmatch
from collections import Counter
from fuzzywuzzy import process

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
    def __init__(self):
        # Initialize any necessary attributes
        self.chat_app = None
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

    def execute(self, params, global_params, plugin_instance_name):

        #check that required params are present
        required_params = ['system_message', 'script_prompt', 'json_script_prompt', 'json_guest_prompt']
        for required_param in required_params:
            if required_param not in params:
                raise Exception(f"Required parameter {required_param} not found in params.")

        #system message
        self.chat_app = gpt.ChatApp(params['system_message'])

        #script
        script = self.chat_app.chat(params['script_prompt'])
        
        #script json
        json_script = self.chat_app.chat(params['json_script_prompt'])
        intro = json.loads(json_script)

        #guests json
        json_guests = self.chat_app.chat(params['json_guest_prompt'])
        guests = json.loads(json_guests)

        #log results
        logger.info(f"System message: {params['system_message']}")
        logger.info(f"script_prompt: {params['script_prompt']}")
        logger.info(f"script: {script}")
        logger.info(f"json_script_prompt: {params['json_script_prompt']}")
        logger.info(f"intro: {intro}")
        logger.info(f"guest_list_prompt: {params['json_guest_prompt']}")
        logger.info(f"guests: {guests}")

        #extra prompts
        extra_prompts = params.get('extra_prompts', [{}])
        extra_prompt_responses = {}
        for prompt in extra_prompts:
            logger.info(f"Running extra_prompt: {prompt}")
            extra_prompt_responses[prompt['name']
                                   ] = self.chat_app.chat(prompt['prompt'])
            logger.info(
                f"Extra prompt response: {extra_prompt_responses[prompt['name']]}")

        # validate json
        validate_json_response(intro, self.intro_schema)
        validate_json_response(guests, self.guests_schema)
        
        #normalize guest categories
        guest_categories = params.get('guest_categories', [])
        if guest_categories != []:
            logger.info("Normalizing guest categories")
            updates = match_categories(guests, guest_categories)
            if updates != {}:
                logger.warning(f"Guest categories replacements made: {updates}")

        # apply guest list filter
        guest_filter = params.get('guest_name_filters', [])
        if guest_filter != []:
            logger.info(f"Found guests filter: {guest_filter}")
            guests_new = [guest for guest in guests if not any(fnmatch.fnmatch(
                guest['guest_name'].lower(), pattern.lower()) for pattern in params.get('guest_name_filters', []))]
            if len(guests_new) != len(guests):
                removed = list(set(set({tuple(guest.items()) for guest in guests}))
                               - set({tuple(guest.items())
                                      for guest in guests_new})
                               )
                print(f"Guest list filter applied. Guests removed:{removed}")
            guests = guests_new
            
        #apply guest count filter
        guest_count_filter = params.get('guest_count_filters', {})
        if guest_count_filter != {}:
            guests = filter_guests_count(guests, guest_count_filter)

        #log guests
        logger.info(f"Guests is now: {guests}")

        # raise an error if there are no guests
        if len(guests) == 0:
            logger.error("No guests found in intro.")
            raise Exception("No guests found in intro.")

        #raise an assertion error to trigger a retry
        try:
            assert len(guests) > 0, "Number of guests must be greater than zero."
        except AssertionError as e:
            logger.error(str(e))
            raise e

        result = {
            "script": script,
            "intro": intro,
            "guests": guests,
            "extra_prompt_responses": extra_prompt_responses,
            "chat_app": self.chat_app
        }

        return result
