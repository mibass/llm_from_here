import json
import llm_from_here.plugins.gpt as gpt
from jsonschema import validate
from jsonschema.exceptions import ValidationError
import logging
import fnmatch
from fuzzywuzzy import process

from llm_from_here.common import log_exception, is_production_prefix
from llm_from_here.supaSet import SupaSet

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

def filter_guests_count(guests, guest_count_filters):
    count_per_category = {}
    filtered_guests = []
    
    for guest in guests:
        category = guest['guest_category'].lower()
        if category not in guest_count_filters:
            filtered_guests.append(guest)
        elif category not in count_per_category or count_per_category[category] < guest_count_filters[category]:
            count_per_category.setdefault(category, 0)
            count_per_category[category] += 1
            filtered_guests.append(guest)
        else:
            logger.info(f"Guest {guest['guest_category']}:{guest['guest_name']} filtered out due to guest count filter.")
            
    return filtered_guests


def match_categories(guest_list, standard_categories):
    """
    Matches the 'guest_category' of each guest in the provided guest list to the closest matching category
    from a list of standard categories.
    """
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

def set_guests(guests, guest_set):
    guests=list(set(guests))
    for guest in guests:
        if not guest_set.add(guest):
            logger.warning(f"Guest {guest} already exists in supaset. Maybe retrying...")
            raise ValidationError(f"Guest {guest} already exists in supaset. Maybe retrying...")
        
def add_guests_to_prompt(prompt, guest_set):
    guest_names = guest_set.elements()
    guest_names = ', '.join(guest_names)
    if guest_names != '':
        prompt += f'\n Do not use these guests because they have been on recently: {guest_names}'
    return prompt



class Intro:
    def __init__(self, params, global_params, plugin_instance_name, chat_app=None):
        self.chat_app = chat_app or gpt.ChatApp(params['system_message'])
        self.params = params
        self.global_params = global_params
        self.plugin_instance_name = plugin_instance_name
        supaset_name = f'{is_production_prefix()}guests_set'
        self.guests_set = SupaSet(supaset_name,
                                          autoexpire = params.get('guests_supaset_autoexpire_days', 90))
        

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
        #script
        script_prompt = params['script_prompt']
        script_prompt = add_guests_to_prompt(script_prompt, self.guests_set)
        if script_prompt != params['script_prompt']:
            logger.info(f"Script prompt updated: {script_prompt}")
        self.script = self.chat_app.chat(script_prompt)
        logger.info(f"Script: {self.script}")
        
        #json script
        self.intro = json.loads(self.chat_app.chat(params['json_script_prompt']))
        logger.info(f"Intro json: {self.intro}")
        
        #json guests
        self.guests = json.loads(self.chat_app.chat(params['json_guest_prompt']))
        logger.info(f"Guests json: {self.guests}")

        self.extra_prompt_responses = self.get_extra_prompt_responses()
        self.validate_json_responses()
        self.normalize_guest_categories()
        self.apply_guest_list_filter()
        self.update_guest_categories()
        self.apply_guest_count_filter()
        
        #finalize guests
        set_guests([x['guest_name'] for x in self.guests], self.guests_set)
        self.guests_set.complete_session()
        

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

    def validate_json_responses(self):
        validate_json_response(self.intro, self.intro_schema)
        validate_json_response(self.guests, self.guests_schema)

    def normalize_guest_categories(self):
        """
        Normalizes the 'guest_category' values of the guests based on a list of standard categories.
        """
        guest_categories = self.params.get('guest_categories', [])
        if guest_categories != []:
            logger.info("Normalizing guest categories")
            updates = match_categories(self.guests, guest_categories)
            if updates != {}:
                logger.warning(f"Guest categories replacements made: {updates}")

    def apply_guest_list_filter(self):
        """
        Applies a guest name filter to the list of guests, removing guests whose names
        match the specified filter patterns.
        """

        guest_filter = self.params.get('guest_name_filters', [])
        if guest_filter:
            logger.info(f"Found guests filter: {guest_filter}")
            removed_guests = []
            filtered_guests = []
            for guest in self.guests:
                if not any(fnmatch.fnmatch(guest['guest_name'].lower(), pattern.lower()) for pattern in guest_filter):
                    filtered_guests.append(guest)
                else:
                    removed_guests.append(guest)

            self.guests = filtered_guests

            if removed_guests:
                logger.info(f"Guests list filter applied. Guests removed: {removed_guests}")

    def update_guest_categories(self):
        """
        Updates the 'guest_category' for each 'guest_name' in a list of dictionaries,
        ensuring that all 'guest_categories' are the same per 'guest_name'.
        """
        guest_dict = {}

        for guest in self.guests:
            guest_category = guest['guest_category']
            guest_name = guest['guest_name']
            if guest_name in guest_dict:
                guest['guest_category'] = guest_dict[guest_name]
            else:
                guest_dict[guest_name] = guest_category


    def apply_guest_count_filter(self):
        """    
        Applies a guest count filter to the list of guests, removing guests based on the specified count criteria.
        """
        guest_count_filter = self.params.get('guest_count_filters', {})
        if guest_count_filter != {}:
            self.guests = filter_guests_count(self.guests, guest_count_filter)
            logger.info(f"Guests is now: {self.guests}")
    
    @log_exception(logger.error)
    def check_guests(self):
        """
        Checks that the number of guests is greater than zero and less than a maximum (default 10).
        """
        assert len(self.guests) > 0, "Number of guests must be greater than zero."
        assert len(self.guests) < self.params.get("max_guests", 10), "Number of guests must be less than 10."

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

