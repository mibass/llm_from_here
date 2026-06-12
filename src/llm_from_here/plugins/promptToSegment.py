import importlib
import logging
import random

from llm_from_here.plugins.gpt import ChatApp
import re
import yaml
import fnmatch
from llm_from_here.common import get_nested_value, is_production_prefix
from llm_from_here.openrouter_web_search import run_web_search
from llm_from_here.schemas.story_outputs import split_dialog_with_applause
from llm_from_here.supaSet import SupaSet

logger = logging.getLogger(__name__)


def _normalize_subject(value: str) -> str:
    return value.strip().lower()


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
        self.included = True
        self.research_context: dict | str | None = None
        self.web_search_result = None
        self._used_subjects: SupaSet | None = None
        self._recorded_subject: str | None = None
        self._subject_retries = 1

        self.validate_required_params()
        if not self._roll_include():
            self.included = False
            logger.info(
                "include_probability=%s: skipping segment generation for %s",
                self.params.get("include_probability"),
                plugin_instance_name,
            )
        else:
            self._init_used_subjects_supaset()
            if self._used_subjects is not None:
                self._run_research_and_prompts_with_retries()
            else:
                self._run_web_research()
                self.process_prompts()
            self._recorded_subject = self._resolve_subject_to_record()
        
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

    def _roll_include(self) -> bool:
        prob = self.params.get("include_probability")
        if prob is None:
            return True
        try:
            threshold = float(prob)
        except (TypeError, ValueError) as err:
            raise ValueError(f"include_probability must be a number, got {prob!r}") from err
        if threshold < 0 or threshold > 1:
            raise ValueError(f"include_probability must be between 0 and 1, got {threshold}")
        return random.random() < threshold

    def _web_research_config(self) -> dict | None:
        wr = self.params.get("web_research")
        return wr if isinstance(wr, dict) else None

    def _init_used_subjects_supaset(self) -> None:
        wr = self._web_research_config()
        if not wr or not wr.get("track_used_subjects"):
            return
        set_name = wr.get("used_subjects_supaset_name") or (
            f"{is_production_prefix()}{self.plugin_instance_name}_subjects"
        )
        autoexpire = wr.get("used_subjects_autoexpire_days")
        self._used_subjects = SupaSet(set_name, autoexpire=autoexpire)
        self._subject_retries = max(1, int(wr.get("max_subject_retries", 3)))
        logger.info(
            "Tracking used subjects for %s in supaset %r (retries=%s)",
            self.plugin_instance_name,
            set_name,
            self._subject_retries,
        )

    def _format_used_subjects_block(self, extra_exclusions: list[str] | None = None) -> str:
        seen: set[str] = set()
        lines: list[str] = []
        if self._used_subjects is not None:
            for subject in self._used_subjects.elements() or []:
                key = _normalize_subject(subject)
                if key and key not in seen:
                    seen.add(key)
                    lines.append(f"- {subject}")
        for subject in extra_exclusions or []:
            key = _normalize_subject(subject)
            if key and key not in seen:
                seen.add(key)
                lines.append(f"- {subject}")
        if not lines:
            return "(none)"
        return "\n".join(lines)

    def _extract_subject_from_research(self) -> str:
        if isinstance(self.research_context, dict):
            return str(self.research_context.get("subject") or "").strip()
        return ""

    def _extract_subject_from_script(self) -> str:
        if not self.script:
            return ""
        try:
            loaded = yaml.safe_load(self.script)
        except yaml.YAMLError:
            return ""
        if isinstance(loaded, dict):
            return str(loaded.get("subject") or "").strip()
        return ""

    def _extract_subject_from_segments(self) -> str:
        for segment in self.segments:
            if segment.get("subject"):
                return str(segment["subject"]).strip()
        return ""

    def _resolve_subject_to_record(self) -> str:
        for extractor in (
            self._extract_subject_from_script,
            self._extract_subject_from_research,
            self._extract_subject_from_segments,
        ):
            subject = extractor()
            if subject:
                return subject
        return ""

    def _subject_is_used(self, subject: str) -> bool:
        if not subject or self._used_subjects is None:
            return False
        return _normalize_subject(subject) in self._used_subjects

    def _augment_search_prompt(self, base_prompt: str, extra_exclusions: list[str]) -> str:
        used_block = self._format_used_subjects_block(extra_exclusions)
        if used_block == "(none)":
            return base_prompt
        return (
            f"{base_prompt.rstrip()}\n\n"
            "Do NOT choose any of these already-covered subjects:\n"
            f"{used_block}"
        )

    def _run_research_and_prompts_with_retries(self) -> None:
        extra_exclusions: list[str] = []
        for attempt in range(1, self._subject_retries + 1):
            self.research_context = None
            self.web_search_result = None
            self.segments = []
            self.script = ""
            self._run_web_research(extra_exclusions=extra_exclusions)
            subject = self._extract_subject_from_research()
            if subject and self._subject_is_used(subject):
                logger.warning(
                    "Research subject %r already used (attempt %s/%s)",
                    subject,
                    attempt,
                    self._subject_retries,
                )
                extra_exclusions.append(subject)
                continue
            self.process_prompts()
            subject = self._resolve_subject_to_record()
            if subject and self._subject_is_used(subject):
                logger.warning(
                    "Final subject %r already used (attempt %s/%s)",
                    subject,
                    attempt,
                    self._subject_retries,
                )
                extra_exclusions.append(subject)
                continue
            logger.info("Selected unused subject %r on attempt %s", subject, attempt)
            return

        logger.warning(
            "Exhausted subject retries for %s; skipping segment",
            self.plugin_instance_name,
        )
        self.included = False
        self.segments = []
        self.script = ""
        self.research_context = None
        self.web_search_result = None

    def _format_prompt(self, prompt_text: str) -> str:
        if not prompt_text:
            return prompt_text
        if "{{used_subjects}}" in prompt_text:
            prompt_text = prompt_text.replace(
                "{{used_subjects}}",
                self._format_used_subjects_block(),
            )
        if "{{research_context}}" in prompt_text:
            rendered = yaml.dump(self.research_context, default_flow_style=False)
            prompt_text = prompt_text.replace("{{research_context}}", rendered)
        if "{{script}}" in prompt_text:
            prompt_text = prompt_text.replace("{{script}}", self.script or "")
        if self.web_search_result is not None:
            prompt_text = prompt_text.replace(
                "{{web_search_content}}",
                self.web_search_result.content,
            )
            prompt_text = prompt_text.replace(
                "{{web_search_sources}}",
                self.web_search_result.format_sources(),
            )
        return prompt_text

    def _run_web_research(self, *, extra_exclusions: list[str] | None = None) -> None:
        wr = self._web_research_config()
        if not wr:
            return

        search_prompt = wr.get("search_prompt") or wr.get("prompt")
        if not search_prompt:
            raise ValueError("web_research requires search_prompt or prompt")
        search_prompt = self._format_prompt(search_prompt)
        if self._used_subjects is not None:
            search_prompt = self._augment_search_prompt(
                search_prompt, extra_exclusions or []
            )

        search_cfg = wr.get("search") or {}
        model = wr.get("model") or search_cfg.get("model")
        self.web_search_result = run_web_search(
            search_prompt,
            model=model,
            engine=search_cfg.get("engine"),
            max_results=search_cfg.get("max_results"),
            max_total_results=search_cfg.get("max_total_results"),
            search_context_size=search_cfg.get("search_context_size", "medium"),
            allowed_domains=search_cfg.get("allowed_domains"),
            excluded_domains=search_cfg.get("excluded_domains"),
        )

        extraction_model = wr.get("extraction_model")
        if extraction_model:
            model_cls = _import_output_model(extraction_model)
            extraction_prompt = wr.get("extraction_prompt") or (
                "Extract structured research notes from the web search results below. "
                "Include source-backed facts only.\n\n"
                "{{web_search_content}}\n\nSources:\n{{web_search_sources}}"
            )
            extraction_prompt = self._format_prompt(extraction_prompt)
            self.research_context = self.chat_app.run_structured(
                extraction_prompt,
                model_cls,
                log_prompt=True,
            )
        else:
            self.research_context = {
                "content": self.web_search_result.content,
                "sources": [
                    {
                        "url": cite.url,
                        "title": cite.title,
                        "snippet": cite.content,
                    }
                    for cite in self.web_search_result.citations
                ],
            }

    def process_prompts(self):

        for prompt in self.params.get('prompts', []):
            prompt_text = prompt.get('prompt', None)
            if prompt_text:
                prompt_text = self._format_prompt(prompt_text)
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
            "script": self.script,
            "included": self.included,
            "research_context": self.research_context,
            "recorded_subject": self._recorded_subject,
        }

    def finalize(self) -> None:
        if not self.included or self._used_subjects is None:
            return
        subject = self._recorded_subject or self._resolve_subject_to_record()
        if not subject:
            logger.warning(
                "No subject to record for %s; skipping used-subjects finalize",
                self.plugin_instance_name,
            )
            return
        if not self._used_subjects.add(subject):
            logger.info("Subject %r was already present in %r", subject, self._used_subjects.set_name)
        self._used_subjects.complete_session()
        logger.info(
            "Recorded subject %r in supaset %r for %s",
            subject,
            self._used_subjects.set_name,
            self.plugin_instance_name,
        )
