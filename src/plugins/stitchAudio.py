from pydub import AudioSegment
import os

import logging
logger = logging.getLogger(__name__)

TARGET_AMPLITUDE = -20.0


def match_target_amplitude(sound, target_dBFS=TARGET_AMPLITUDE):
    change_in_dBFS = target_dBFS - sound.dBFS
    return sound.apply_gain(change_in_dBFS)


class StitchAudio():

    def __init__(self, params, global_results, plugin_instance_name):
        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name

    def execute(self):

        segments_object = self.params.get('segments_object', None)
        data = self.global_results.get(segments_object, None)
        output_folder = self.global_results['output_folder']
        output_format = self.params.get('output_format', 'wav')
        if segments_object:
            file_path = os.path.join(
                output_folder, segments_object + "_merged."+output_format)
        else:
            file_path = os.path.join(output_folder, self.params.get(
                'name', '')+"_merged."+output_format)
        applause_crossfade_duration = 300
        segment_type_key = self.params.get('segment_type_key', 'guest_category')
        segment_filename_key = self.params.get('segment_filename_key', 'filename')
        segment_type_map = self.params.get('segment_type_map', {})

        merged_audio = AudioSegment.silent(duration=1000)
        if data is None:
            # pull data from segments_list
            segments_list = self.params.get('segments_list', None)
            if segments_list is None:
                logger.error(
                    "No segments list or segments_object found in settings/global parameters.")
                raise Exception(
                    "No segments list or segments_object found in settings/global parameters.")
            data = []
            for segment in segments_list:
                data.append({'speaker': 'spoken',
                            'filename': self.global_results[segment]})
            logger.info(f"Using segments_list to generate audio: {data}")

        background_music_filename = None
        for audio_dict in data:
            speaker = audio_dict.get(segment_type_key, '').lower()
            filename = audio_dict.get(segment_filename_key)
            if speaker not in segment_type_map:
                if 'default' not in segment_type_map:
                    logger.warning(
                        f"No function found for segment type: {speaker} using spoken function.")
                else:
                    logger.warning(
                        f"No function found for segment type: {speaker}. Using default function.")
                speaker = 'default'
                
            segment_type_mapped = segment_type_map.get(speaker, 'spoken')

            if filename and segment_type_mapped != 'background music':
                audio = AudioSegment.from_file(filename)
                if len(audio) > 0:
                    audio = match_target_amplitude(audio)
                if len(merged_audio) == 0:
                    merged_audio = audio
                else:
                    if len(audio) >= applause_crossfade_duration:
                        merged_audio = merged_audio.append(audio.fade_in(
                            applause_crossfade_duration), crossfade=applause_crossfade_duration)
                    else:
                        merged_audio = merged_audio.append(audio)

            if segment_type_mapped == 'background music' and background_music_filename is None:
                background_music_filename = filename

        merged_audio = match_target_amplitude(merged_audio)

        # Add music
        if background_music_filename:
            logger.info(
                f"Found background music file '{background_music_filename}'; removing silence.")
            music = AudioSegment.from_file(background_music_filename)
            music = music.strip_silence(
                silence_thresh=-50, silence_len=50, padding=0)
            music_volume_before = music.dBFS
            music = match_target_amplitude(music)
            music = music.apply_gain(self.params.get('background_music_gain', -5))
            logger.info(
                f" Changed music volume from {music_volume_before} to { music.dBFS}.")

            # Loop the music to match the duration of merged audio
            music = music * (len(merged_audio) // len(music) + 1)
            # Trim the music to match the duration of merged audio
            music = music[:len(merged_audio)]

            output_audio = merged_audio.overlay(music)
            #output_audio = music.overlay(merged_audio)
        else:
            output_audio = merged_audio

        output_audio.export(file_path, format=output_format)

        logger.info(f"Audio files merged and saved as '{file_path}'.")

        return {'stitched_audio_file': file_path}
