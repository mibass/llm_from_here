import importlib
import logging

from llm_from_here.plugins.gpt import ChatApp
import re
import yaml
import fnmatch
from llm_from_here.common import get_nested_value
from llm_from_here.schemas.story_outputs import split_dialog_with_applause

logger = logging.getLogger(__name__)


def _import_output_model(spec: str) -> type:
    """Import ``module.path:ClassName`` for structured prompt outputs."""
    if ":" not in spec:
        raise ValueError(f"output_model must look like 'pkg.mod:ClassName', got {spec!r}")
    mod_name, _, attr = spec.partition(":")
    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)


def _import_callable(spec: str):
    """Import ``module.path:callable_name``."""
    if ":" not in spec:
        raise ValueError(f"segment_mapper must look like 'pkg.mod:func', got {spec!r}")
    mod_name, _, attr = spec.partition(":")
    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)


class PromptToSegment:
    def __init__(self, params, global_params, plugin_instance_name):
        chat_app_variable = params.get("chat_app_variable")
        if chat_app_variable:
            self.chat_app = global_params.get(chat_app_variable)
            if self.chat_app is None:
                raise Exception(
                    f"chat_app_variable {chat_app_variable!r} not found in global results."
                )
        else:
            self.chat_app = ChatApp(params.get("system_message", ""))
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
                if not self.segments:
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
        
    
    def convert_script_to_segments(self, filter_empty_dialog=True):
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
            if re.match(r'\[BACKGROUND MUSIC:\s*', line, flags=re.IGNORECASE):
                result = re.sub(
                    r'\[BACKGROUND MUSIC:\s*', '', line, flags=re.IGNORECASE
                )
                result = re.sub(r'\]', '', result)
                segment = {
                    'speaker': 'background',
                    'dialog': result.strip(),
                }
                self.segments.append(segment)
            elif re.match(r'\[background:\s*', line, flags=re.IGNORECASE):
                result = re.sub(r'\[background:\s*', '', line, flags=re.IGNORECASE)
                result = re.sub(r'\]', '', result)
                segment = {
                    'speaker': 'background',
                    'dialog': result.strip()
                }
                self.segments.append(segment)
            elif re.match(r'\[APPLAUSE', line, re.IGNORECASE):
                self.segments.append({
                    'speaker': 'audience',
                    'dialog': line.strip(),
                })
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

        if filter_empty_dialog:
            self.segments = [segment for segment in self.segments if segment['dialog'].strip() != ""]

        self._normalize_segments()

    def _normalize_segments(self) -> None:
        """Drop markdown titles and put background cues first for single_background timelines."""
        title_pattern = re.compile(r'^\*\*.+\*\*\s*$')
        self.segments = [
            segment
            for segment in self.segments
            if not (
                segment.get("character_name") == "narrator"
                and title_pattern.match(segment.get("dialog", "").strip())
            )
        ]
        backgrounds = [s for s in self.segments if s.get("speaker") == "background"]
        rest = [s for s in self.segments if s.get("speaker") != "background"]
        if backgrounds:
            self.segments = backgrounds[:1] + rest

    def split_dialog(self, dialog):
        """
        Split dialog into segments based on [APPLAUSE ...] cues
        """
        char_num = self.get_character_number('narrator')
        self.segments.extend(
            split_dialog_with_applause(
                dialog,
                character_number=char_num,
                character_name="narrator",
            )
        )

    def validate_required_params(self):
        required_params = []
        for required_param in required_params:
            if required_param not in self.params:
                logger.error(f"Required parameter {required_param} not found in params.")
                raise Exception(f"Required parameter {required_param} not found in params.")


    def process_prompts(self):

        for prompt in self.params.get('prompts', []):
            prompt_text = prompt.get('prompt', None)
            prompt_js = prompt.get("prompt_js", None)
            output_model = prompt.get("output_model")
            segment_mapper = prompt.get("segment_mapper")
            accumulate = prompt.get('accumulate', False)

            if output_model:
                model_cls = _import_output_model(output_model)
                response = self.chat_app.run_structured(
                    prompt_text, model_cls, log_prompt=True
                )
                self.script = yaml.dump(response)
                if segment_mapper:
                    mapper_fn = _import_callable(segment_mapper)
                    mapped = mapper_fn(response)
                    if accumulate:
                        self.segments += mapped
                    else:
                        self.segments = mapped
                elif accumulate:
                    if isinstance(response, list):
                        self.segments += response
                    else:
                        raise ValueError(
                            "accumulate with structured output requires segment_mapper "
                            "or a list response"
                        )
            elif prompt_js:
                raise ValueError(
                    "prompt_js JSON Schema is no longer supported here. "
                    "Use output_model: 'module.path:ClassName' pointing to a Pydantic model."
                )
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
