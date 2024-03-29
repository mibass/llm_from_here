import llm_from_here.plugins.showTTS as showTTS
import os
import re
import shutil

from llm_from_here.plugins.applause import generate_applause
import llm_from_here.plugins.freesoundfetch as freesoundfetch
import llm_from_here.plugins.ytfetch as ytfetch
import llm_from_here.plugins.audioTimeline as audioTimeline

import logging

logger = logging.getLogger(__name__)


class SegmentsToTimeline:
    def __init__(self, params, global_results, plugin_instance_name):
        self.show_tts = None
        self.freesound_fetch = freesoundfetch.FreeSoundFetch(
            params, global_results, plugin_instance_name
        )
        self.yt_fetch = None
        self.chat_app_object = global_results.get(
            params.get("chat_app_object", "intro_chat_app"), None
        )
        self.global_results = global_results
        self.params = params
        self.plugin_instance_name = plugin_instance_name

        # check if a timeline already exists
        timeline_variable = params.get("timeline_variable", None)
        self.timeline = global_results.get(
            timeline_variable, audioTimeline.AudioTimeline()
        )
        if timeline_variable:
            logger.info(
                f"Using existing timeline in {timeline_variable}. Timeline length: {self.timeline.get_last_end_time()}"
            )
        else:
            logger.info(f"No timeline found. Creating new timeline.")

    def applause_generator(self, text, output_file):
        # extract the duration from the text
        match = re.search(r"duration (\d+)", text)
        if match:
            duration = int(match.group(1)) * 1000
        else:
            duration = 3000
        logger.info(f"Generating applause of duration: {duration}")
        applause_segment = generate_applause(duration, 2000, 4000, 500)

        # Export to a new file
        with open(output_file, "wb") as f:
            applause_segment.export(f, format="wav")
            return True

    def music_generator_freesound(
        self,
        text,
        output_file,
        additional_query_text="",
        duration_min_sec=20,
        duration_max_sec=600,
    ):
        # extract the music type from the text
        match = re.search(r"\[MUSIC (.*?)\]", text)
        if match:
            music_type = match.group(1)
        else:
            music_type = text

        # extract the dir from output_file
        output_dir = os.path.dirname(output_file)
        self.freesound_fetch.out_dir = output_dir
        query = f"{music_type} {additional_query_text}"
        logger.info(
            f"Retreiving freesound music with query: {query}, duration: {duration_min_sec} to {duration_max_sec}"
        )
        self.freesound_fetch.search_and_download_top_samples(
            query, 1, {"filter": f"duration:[{duration_min_sec} TO {duration_max_sec}]"}
        )
        shutil.move(self.freesound_fetch.temp_files[-1], output_file)
        return True

    def tts(self, text, output_file, fast_tts=True):
        if self.show_tts is None:
            self.show_tts = showTTS.ShowTextToSpeech()
        # filter out any text in brackets, parantheses
        text_filtered = re.sub(r"\[.*?\]", "", text)
        text_filtered = re.sub(r"\(.*?\)", "", text_filtered)
        # remove any quotes (single or double)
        text_filtered = text_filtered.replace('"', "")

        if text != text_filtered:
            logger.info(
                f"Filtered out text. Original: {text}. Filtered: {text_filtered}"
            )
        if len(text_filtered.strip()) == 0:
            logger.info(f"Text is empty after filtering. Skipping TTS.")
            return None
        else:
            self.show_tts.speak(text_filtered, output_file, fast=fast_tts)

        return {}

    def fast_TTS(self, text, output_file):
        return self.tts(text, output_file, fast_tts=True)

    def slow_TTS(self, text, output_file):
        return self.tts(text, output_file, fast_tts=False)
        
    def init_ytfetch(self, **kwargs):
        if self.yt_fetch is None:
            self.yt_fetch = ytfetch.YtFetch(**kwargs)

    def youtube_search(self, text, output_file, **kwargs):
        self.init_ytfetch(**kwargs)
        additional_query_text = kwargs.get("additional_query_text", "")

        query = f"{text} {additional_query_text}"
        logger.info(f"Retreiving youtube audio with query: {query}")
        kwargs["chat_app"] = self.chat_app_object

        res = self.yt_fetch.search_and_download_audio_with_duration(
            query, output_file, **kwargs
        )

        if res is None:
            logger.warning(f"No youtube audio result found for query: {query}")
            return None
        else:
            logger.info(
                f"Retreived youtube audio result with title: {res.get('title','')} {res.get('video_url','')}"
            )
            return res

    def youtube_playlist(self, text, output_file, **kwargs):
        playlist_id = kwargs.get("playlist_id")
        logger.info(f"Retreiving youtube playlist item with id: {playlist_id}")

        self.init_ytfetch(**kwargs)

        res = self.yt_fetch.download_random_video_from_playlist(
            playlist_id, output_file
        )
        logger.info(
            f"Retreived youtube audio result with title: {res.get('title','')} {res.get('video_url','')}"
        )
        return res

    def get_transition_map_entry(self, segment_transition_map, to_type):
        if segment_transition_map is not None and len(segment_transition_map) > 0:
            to_type = to_type.lower()
            logger.info(
                f"Getting transition map entry for map {segment_transition_map} and type {to_type}"
            )
            from_type = self.timeline.get_last_type()
            if from_type:
                from_type = from_type.lower()
            if to_type:
                to_type = to_type.lower()
            logger.info(f"Last type was {from_type}")

            # segment_transition_map is a list of dicts, each dict is a transition map
            # find the from_type in the transition map, if it exists
            f = [
                d.get(from_type if from_type in d else "any")
                for d in segment_transition_map
                if from_type in d or "any" in d
            ]
            if len(f) > 0:
                logger.info(
                    f"Found from_type {from_type} in transition map, with entries {f}"
                )
                # find the to_type in the transition map, if it exists
                t = [
                    d.get(to_type if to_type in d else "any")
                    for d in f
                    if to_type in d or "any" in d
                ]
                if len(t) > 0:
                    logger.info(
                        f"Found to_type {to_type} in transition map, with entries {t}"
                    )
                    if len(t) > 1:
                        logger.warning(
                            f"Found multiple to_type entries in transition map. Using first."
                        )
                    return t[0]
        return {}

    def get_data(self, type_key, value_key):
        data = self.global_results.get(self.params.get("segments_object"))
        if not data:
            logger.info(f"No data found. Using segment_type_map instead.")
            # if no data, assume segment_type_map is the list
            data = []
            for k, _ in self.params.get("segment_type_map", {}).items():
                data.append({type_key: k, value_key: ""})
            logger.info(f"Data is now: {data}")
        return data

    def generate_audio_segments(self):
        output_folder = self.global_results["output_folder"]
        type_key = self.params.get("segment_type_key", "speaker")
        value_key = self.params.get("segment_value_key", "dialog")
        single_background = self.params.get("single_background", False)
        segment_type_map = self.params.get("segment_type_map", {})
        segment_transition_map = self.params.get("segment_transition_map", {})

        background_seen = False
        for i, entry in enumerate(self.get_data(type_key, value_key)):
            filename_prefix = f"{self.plugin_instance_name}_{i:03d}"
            filename = filename_prefix + ".wav"
            file_path = os.path.join(output_folder, filename)

            # choose which function to execute based on segment_type_map
            segment_type = entry[type_key].lower()
            if segment_type not in segment_type_map:
                if "default" not in segment_type_map:
                    logger.warning(
                        f"No function found for segment type: {segment_type} and no default set. Skipping segment."
                    )
                    continue
                logger.warning(
                    f"No function found for segment type: {segment_type}. Using default function."
                )
                segment_type = "default"

            function_name = segment_type_map[segment_type].get("segment_type")
            function_arguments = segment_type_map[segment_type].get("arguments", {})

            # only allow one background music segment, if enabled
            background_music = segment_type_map[segment_type].get(
                "background_music", False
            )
            if background_music and single_background and background_seen:
                logger.info(
                    f"Skipping background music segment because single_background is enabled and background_seen is True."
                )
                continue
            else:
                background_seen = True

            # Call the specified function
            logger.info(
                f"Generating audio for type: {entry[type_key]} using function {function_name} with value: {entry[value_key]} and arguments {function_arguments}"
            )
            res = getattr(self, function_name)(
                entry[value_key], file_path, **function_arguments
            )

            if res is None:
                logger.info(f"No audio generated for type: {entry[type_key]}")
                continue  # None indicates no audio was generated

            title = (
                res.get("title", None)
                if res is not None and type(res) == dict
                else None
            )

            # generate applause, if enabled for this segment
            if (
                segment_type_map[segment_type].get("intro_name", False)
                and res is not None
            ):
                if title:
                    intro_file_name = filename_prefix + "_intro_name.wav"
                    intro_file_path = os.path.join(output_folder, intro_file_name)
                    prompt = segment_type_map[segment_type].get("intro_prompt", None)
                    if prompt and self.chat_app_object:
                        intro_prompt = prompt + entry[value_key] + ":::" + title
                        logger.info(f"Prompting chat app with: {intro_prompt}")
                        intro_text = self.chat_app_object.chat(
                            intro_prompt, strip_quotes=True
                        )
                    else:
                        intro_text = "Ladies and gentlemen... {intro_text}"
                    
                    fast_tts = segment_type_map[segment_type].get("fast_tts", True)
                    self.tts(intro_text, intro_file_path, fast_tts=fast_tts)

                    # get transition map entry, if it exists
                    afp_kwargs = self.get_transition_map_entry(
                        segment_transition_map, "intro_name"
                    )
                    self.timeline.add_after_previous(
                        intro_file_path,
                        label=audioTimeline.SegmentLabel.FOREGROUND,
                        name=f"intro_name_{i}",
                        type="intro_name",
                        **afp_kwargs,
                    )
                    logger.info(f"Generated intro name for: {intro_text}")

            # generate applause, if enabled for this segment
            if segment_type_map[segment_type].get("intro_applause", False):
                applause_file_name = filename_prefix + "_intro_applause.wav"
                applause_file_path = os.path.join(output_folder, applause_file_name)
                self.applause_generator("duration 3", applause_file_path)

                afp_kwargs = self.get_transition_map_entry(
                    segment_transition_map, "intro_applause"
                )
                self.timeline.add_after_previous(
                    applause_file_path,
                    label=audioTimeline.SegmentLabel.FOREGROUND,
                    name=f"intro_applause_{i}",
                    type="intro_applause",
                    **afp_kwargs,
                )
                logger.info(f"Generated applause")

            # append the entry to the timeline
            afp_kwargs = self.get_transition_map_entry(
                segment_transition_map, entry[type_key]
            )
            logger.info(
                f"Adding {entry[type_key]} to timeline as label {audioTimeline.SegmentLabel.BACKGROUND if background_music else audioTimeline.SegmentLabel.FOREGROUND} and args {afp_kwargs}"
            )
            self.timeline.add_after_previous(
                file_path,
                label=audioTimeline.SegmentLabel.BACKGROUND
                if background_music
                else audioTimeline.SegmentLabel.FOREGROUND,
                #  name=f'{entry[type_key]}_{i}',
                name=title if title else f"{entry[type_key]}_{i}",
                type=entry[type_key],
                **afp_kwargs,
            )

    def execute(self):
        data = self.global_results.get(self.params.get("segments_object"))
        self.generate_audio_segments()

        # set the end times for all background segments
        self.timeline.set_end_times()

        return {"timeline": self.timeline}

    def finalize(self):
        logger.info(f"Finalizing {self.__class__.__name__}")
        if self.yt_fetch is not None:
            self.yt_fetch.finalize()
