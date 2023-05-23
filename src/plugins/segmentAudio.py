import hashlib
import showTTS
import os
import re
import shutil

from applause import generate_applause
import freesoundfetch
import ytfetch

import logging
logger = logging.getLogger(__name__)


class SegmentAudio():
    def __init__(self, params, global_results, plugin_instance_name):
        self.show_tts = showTTS.ShowTextToSpeech()
        self.freesound_fetch = freesoundfetch.FreeSoundFetch()
        self.yt_fetch = ytfetch.YtFetch()
        self.chat_app_object = global_results.get(params.get('chat_app_object', 'intro_chat_app'), None)
        self.global_results = global_results
        self.params = params
        self.plugin_instance_name = plugin_instance_name

    def applause_generator(self, text, output_file):
        # extract the duration from the text
        match = re.search(r'duration (\d+)', text)
        if match:
            duration = int(match.group(1))*1000
        else:
            duration = 3000
        logger.info(f"Generating applause of duration: {duration}")
        applause_segement = generate_applause(duration, 2000, 4000, 500)

        # Export to a new file
        applause_segement.export(output_file, format="wav")

    def music_generator_freesound(self, text, output_file,
                                  additional_query_text="",
                                  duration_min_sec=20,
                                  duration_max_sec=600):
        # extract the music type from the text
        match = re.search(r'\[MUSIC (.*?)\]', text)
        if match:
            music_type = match.group(1)
        else:
            music_type = text

        # extract the dir from output_file
        output_dir = os.path.dirname(output_file)
        self.freesound_fetch.out_dir = output_dir
        query = f"{music_type} {additional_query_text}"
        logger.info(f"Retreiving freesound music with query: {query}")
        self.freesound_fetch.search_and_download_top_samples(query,
                                                             1,
                                                             {'filter': f'duration:[{duration_min_sec} TO {duration_max_sec}]'})
        shutil.move(self.freesound_fetch.temp_files[-1], output_file)

    def fast_TTS(self, text, output_file):
        self.show_tts.speak(text, output_file, fast=True)
        
    def slow_TTS(self, text, output_file):
        self.show_tts.speak(text, output_file, fast=False)

    def youtube_search(self, text, output_file,
                       additional_query_text="",
                       duration_min_sec=180,
                       duration_max_sec=480,
                       duration_search_filter = None,
                       description_filters=None):
        query = f"{text} {additional_query_text}"
        logger.info(f"Retreiving youtube audio with query: {query}")
        
        res = self.yt_fetch.search_and_download_audio_with_duration(query,
                                                              output_file,
                                                              duration_min_sec,
                                                              duration_max_sec,
                                                              duration_search_filter,
                                                              description_filters)
        logger.info(f"Retreived youtube audio result with title: {res.get('title','')} {res.get('video_url','')}")
        return res
    
    def youtube_playlist(self, text, output_file, playlist_id=None):
        logger.info(f"Retreiving youtube playlist item with id: {playlist_id}")
        
        res = self.yt_fetch.download_random_video_from_playlist(playlist_id,output_file)
        logger.info(f"Retreived youtube audio result with title: {res.get('title','')} {res.get('video_url','')}")
        return res
        

    def generate_audio_segments(self, data, output_folder, params, plugin_instance_name, chat_app=None ):
        type_key = params['segment_type_key']
        value_key = params['segment_value_key']
        segment_type_map = params['segment_type_map']

        new_data = []
        i=0
        for entry in data:
            i+=1
            # Generate a hash of the speech text
            # hash_object = hashlib.md5(entry[value_key].encode())
            # filename = hash_object.hexdigest() + ".wav"
            filename_prefix = f"{plugin_instance_name}_{i:03d}"
            filename = filename_prefix + ".wav"
            file_path = os.path.join(output_folder, filename)

            # choose which function to execute based on segment_type_map
            segment_type = entry[type_key].lower()
            if segment_type not in segment_type_map:
                if 'default' not in segment_type_map:
                    logger.error(
                        f"No function found for segment type: {segment_type} and no default set")
                    raise Exception(
                        f"No function found for segment type: {segment_type} and no default set")
                logger.warning(
                    f"No function found for segment type: {segment_type}. Using default function.")
                segment_type = 'default'
                
            function_name = segment_type_map[segment_type].get('segment_type')
            function_arguments = segment_type_map[segment_type].get(
                'arguments', {})

            # Call the specified function
            logger.info(
                f"Generating audio for type: {entry[type_key]} using function {function_name} with value: {entry[value_key]} and arguments {function_arguments}")
            res = getattr(self, function_name)(
                entry[value_key], file_path, **function_arguments)


            # generate applause, if enabled for this segment
            if segment_type_map[segment_type].get('intro_name', False) and res is not None:
                if res.get('title', None) is not None:
                    intro_file_name = filename_prefix + "_intro_name.wav"
                    intro_file_path = os.path.join(output_folder, intro_file_name)
                    prompt = segment_type_map[segment_type].get('intro_prompt', None)
                    if prompt and chat_app:
                        intro_prompt = prompt + entry[value_key] + ":::" + res['title']
                        logger.info(f"Prompting chat app with: {intro_prompt}")
                        intro_text = chat_app.chat(intro_prompt, strip_quotes=True)
                    else:
                        intro_text = 'Ladies and gentlemen... {intro_text}' 
                    self.fast_TTS(intro_text, intro_file_path)
                    
                    new_data.append({type_key: 'applause',
                                 'filename': intro_file_path})
                    logger.info(f"Generated intro name for: {intro_text}")
                    
            if segment_type_map[segment_type].get('intro', False):
                intro_file_name = filename_prefix + "_intro.wav"
                intro_file_path = os.path.join(output_folder, intro_file_name)
                self.fast_TTS(f'Ladies and gentlemen... {entry[value_key]}', intro_file_path)
                new_data.append({type_key: 'applause',
                                'filename': intro_file_path})
                logger.info(f"Generated intro name for: {entry[value_key]}")
            
            # generate applause, if enabled for this segment
            if segment_type_map[segment_type].get('intro_applause', False):
                applause_file_name = filename_prefix + "_intro_applause.wav"
                applause_file_path = os.path.join(output_folder, applause_file_name)
                self.applause_generator('duration 3', applause_file_path)
                new_data.append({type_key: 'applause',
                                 'filename': applause_file_path})
                logger.info(f"Generated applause")
                

            # Update the entry with the filename, if it exists
            if os.path.isfile(file_path):
                entry['filename'] = file_path
                
            # if the res exists, store in on the entry
            if res is not None:
                entry['result'] = res
                
            new_data.append(entry)

        return new_data

    def execute(self):
        data = self.generate_audio_segments(self.global_results[self.params['segments_object']],
                                            self.global_results['output_folder'],
                                            self.params,
                                            self.plugin_instance_name,
                                            chat_app=self.chat_app_object)

        return {'segments': data}
