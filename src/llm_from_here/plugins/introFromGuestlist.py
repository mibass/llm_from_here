import json
import llm_from_here.plugins.gpt as gpt
from jsonschema import validate
from jsonschema.exceptions import ValidationError
import logging
import fnmatch
from fuzzywuzzy import process
from jinja2 import Template
import random

from llm_from_here.common import log_exception

logger = logging.getLogger(__name__)

def render_template(template_string, **kwargs):
    template = Template(template_string)
    return template.render(**kwargs)

class IntroFromGuestlist:
    def __init__(self, params, global_params, plugin_instance_name, chat_app=None):
        self.chat_app = chat_app or gpt.ChatApp(params['system_message'])
        self.params = params
        self.global_params = global_params
        self.plugin_instance_name = plugin_instance_name

        self.validate_required_params()
        
        #get guests and shuffle them
        self.guests = self.get_guests()
        self.guests = random.sample(self.guests, len(self.guests))
        logger.info(f"Found guests: {self.guests}")
        guest_list = [x['guest_name'] for x in self.guests]
        
        #dedupe this list
        guest_list = list(set(guest_list))
        
        #script
        script_prompt = params['script_prompt']
        script_prompt = Template(script_prompt).render(guests=', '.join(guest_list))

        if script_prompt != params['script_prompt']:
            logger.info(f"Script prompt updated: {script_prompt}")
            
        self.script = self.chat_app.chat(script_prompt)
        logger.info(f"Script: {self.script}")
        
        #json script with enforced json
        self.intro = self.chat_app.enforce_json_response(params['json_script_prompt'], params['json_script_prompt_js'], log_prompt=True)
        logger.info(f"Intro json: {self.intro}")
        
        self.extra_prompt_responses = self.get_extra_prompt_responses()
        
    # @log_exception
    def get_guests(self):
        guests_parameter = self.params['guests_parameter']
        guests = self.global_params.get(guests_parameter, None)
        if not guests:
            raise Exception(f"Guests parameter {guests_parameter} not found in global params.")
        if len(guests) == 0:
            raise Exception(f"Guests parameter {guests_parameter} is empty.")
        return guests

    # @log_exception
    def validate_required_params(self):
        required_params = ['system_message', 'script_prompt', 'json_script_prompt', 'guests_parameter']
        for required_param in required_params:
            if required_param not in self.params:
                raise Exception(f"Required parameter {required_param} not found in params.")
            
    def get_extra_prompt_responses(self):
        extra_prompts = self.params.get('extra_prompts', [{}])
        extra_prompt_responses = {}
        for prompt in extra_prompts:
            logger.info(f"Running extra_prompt: {prompt}")
            extra_prompt_responses[prompt['name']] = self.chat_app.chat(prompt['prompt'])
            logger.info(f"Extra prompt response: {extra_prompt_responses[prompt['name']]}")
        return extra_prompt_responses

    def execute(self):

        result = {
            "script": self.script,
            "intro": self.intro,
            "guests": self.guests,
            "extra_prompt_responses": self.extra_prompt_responses,
            "chat_app": self.chat_app
        }

        return result

