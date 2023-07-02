
import logging
from llm_from_here.plugins.gpt import ChatApp
import re
import yaml
import fnmatch
from llm_from_here.common import get_nested_value

logger = logging.getLogger(__name__)

class PromptToSegment:
    def __init__(self, params, global_params, plugin_instance_name):
        self.chat_app =  ChatApp(params.get('system_message', ''))
        self.params = params
        self.global_params = global_params
        self.plugin_instance_name = plugin_instance_name
        
        self.filter_character_names = params.get('filter_character_names', [])

        self.script = ""
        self.segments = []
        self.character_numbers = {}

        self.validate_required_params()
        self.process_prompts()
        
        if self.params.get('script_variable', None):
            self.script = get_nested_value(self.global_params, self.params['script_variable'])
            
        self.is_dialog = self.params.get('is_dialog', False)
        
        if self.params.get('convert_script_to_segments', True):
            if self.script == "":
                raise Exception("Script is empty. Cannot convert to segments.")
            else:
                self.convert_script_to_segments()
            
        logger.info(f"Segments: {yaml.dump(self.segments)}")
            
    
    def get_character_number(self, character_name):
        """
        Get the character number for a character name.
        """
        if character_name not in self.character_numbers:
            self.character_numbers[character_name] = len(self.character_numbers.keys()) + 1
        return self.character_numbers[character_name]
    
    def filter_character_name(self, name):
        if any(fnmatch.fnmatch(name.lower(), match_string) for match_string in self.filter_character_names):
            return True
        else:
            return False
    
    def get_sound_effect(self, line):
        starts = ['[sound of', '[sound effect', '[sound', '[the sound of', '[the sound', '[sound of a', 
                  '[sound of an', '[sound of the', '[sound of the', '[the sound of a', '[the sound of an', 
                  '[the sound of the', '[the sound of the']
        
        for start in starts:
            if line.lower().startswith(start):
                result = line.lower().replace(start, '').replace(']', '')
                return result
        return None
        
    
    def convert_script_to_segments(self):
        """
        Convert script to segments.
        Take audio cues from the script and convert them to "audio" speaker segments.
        Take Background sound cue and convert them to "background" segments.
        """
        self.segments = []
        char_line_pattern = r'^([A-Za-z0-9\s]+):\s*(.*)$'
        
        for line in self.script.splitlines():
            if line.strip() == "":
                continue
            if line.lower().startswith('[background'):
                result = re.sub(r'\[background:', '', line, flags=re.IGNORECASE)
                result = re.sub(r'\]', '', result)
                segment = {
                    'speaker': 'background',
                    'dialog': result
                }
                self.segments.append(segment)
            elif start:= self.get_sound_effect(line):
                segment = {
                    'speaker': 'sound effect',
                    'dialog': start
                }
                self.segments.append(segment)
            elif match := re.match(char_line_pattern, line, flags=re.IGNORECASE):
                character_name = match.group(1)
                dialog = match.group(2)
                if self.filter_character_name(character_name):
                    logger.info(f"Filtering character name: {character_name}")
                    continue
                segment = {
                    'speaker': 'character ' + str(self.get_character_number(character_name)),
                    'dialog': dialog,
                    'character_name': character_name,
                }
                self.segments.append(segment)
            elif self.is_dialog:
                segment = {
                    'speaker': 'character ' + str(self.get_character_number('narrator')),
                    'dialog': line,
                    'character_name': 'narrator',
                }
                self.segments.append(segment)
            else:
                logger.warning(f"Ignoring line; Could not parse line: {line}")
                
    def split_dialog(self, dialog):
        """
        Split dialog into segments based on [APPLAUSE ...] cues
        """
        applause_pattern = r'\[APPLAUSE.*?\]'
        split = re.split(applause_pattern, dialog, flags=re.IGNORECASE)
        for i, s in enumerate(split):
            if s.strip() != "":
                segment = {
                    'speaker': 'character ' + str(self.get_character_number('narrator')),
                    'dialog': s,
                    'character_name': 'narrator',
                }
                self.segments.append(segment)
            if i < len(split) - 1 and re.search(applause_pattern, split[i+1], flags=re.IGNORECASE):
                applause_dialog = re.search(applause_pattern, split[i+1], flags=re.IGNORECASE).group(0)
                segment = {
                    'speaker': 'audience',
                    'dialog': applause_dialog,
                }
                self.segments.append(segment)

    def validate_required_params(self):
        required_params = []
        for required_param in required_params:
            if required_param not in self.params:
                logger.error(f"Required parameter {required_param} not found in params.")
                raise Exception(f"Required parameter {required_param} not found in params.")


    def process_prompts(self):

        for prompt in self.params.get('prompts', []):
            prompt_text = prompt.get('prompt', None)
            prompt_js = prompt.get('prompt_js', None)
            accumulate = prompt.get('accumulate', False)
            
            if prompt_js:
                response = self.chat_app.enforce_json_response(
                    prompt_text,
                    prompt_js,
                    log_prompt=True)
                if accumulate:
                    self.segments += response
            else:
                logger.info(f"Running prompt: {prompt_text}")
                response=self.chat_app.chat(prompt_text)
                if accumulate:
                    self.script += "\n" + response
                
            logger.info(f"Prompt response: {response}")

        
    def execute(self):
        return {
            "chat_app": self.chat_app,
            "segments": self.segments,
            "script": self.script
        }
