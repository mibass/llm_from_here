from pydub import AudioSegment
import os

from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SegmentLabel(Enum):
    FOREGROUND = 'foreground'
    BACKGROUND = 'background'

def match_target_amplitude(sound, target_dBFS=-20.0):
    change_in_dBFS = target_dBFS - sound.dBFS
    return sound.apply_gain(change_in_dBFS)

class AudioTimeline:
    def __init__(self, params=None, global_results=None, plugin_instance_name=None):
        # check if a timeline already exists
        if params and global_results and plugin_instance_name:
            time_variable = params.get('timeline_variable', None)
            if time_variable:
                try:
                    self.timeline = global_results.get(time_variable).timeline

                except Exception as e:
                    logger.error(
                        f"Unable to retrieve timeline from global results for {plugin_instance_name} and time variable {time_variable}: {e}")
                    raise e
        else:
            self.timeline = []

        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name

    def _validate_audio(self, audio):
        """Validate the audio input to ensure it's an instance of AudioSegment, if not,
        and it's a valid file, assume it's to be imported and return AudioSegment."""
        if isinstance(audio, AudioSegment):
            return audio
        elif isinstance(audio, str):
            if os.path.isfile(audio):
                with open(audio, 'rb') as file:
                    return AudioSegment.from_file(file)
                #return AudioSegment.from_file(audio)
            else:
                raise ValueError(f"Audio file {audio} does not exist.")

    def _apply_effects(self, audio, fade_in, fade_out, gain=None):
        """Apply fade-in and fade-out effects to a given audio segment."""
        ret = audio
        if fade_in > 0:
            ret = audio.fade_in(fade_in)
        if fade_out > 0:
            ret = audio.fade_out(fade_out)
        
        if gain and gain != 0:
            ret = ret.apply_gain(gain)
            
        return ret

    def _add_to_timeline(self, audio, start_time, label=SegmentLabel.FOREGROUND, name=None, type=None, end_time=None):
        """Add the audio segment to the timeline."""
        self.timeline.append({'audio': audio,
                              'start_time': start_time,
                              'label': label,
                              'end_time': end_time,
                              'name': name,
                              'type': type})

    def get_last_type(self):
        """Return the last type in the timeline."""
        if self.timeline:
            return self.timeline[-1]['type']
        else:
            return None
        
    def get_last_end_time(self, label=SegmentLabel.FOREGROUND):
        """Return the last end time for a FOREGROUND entry in the timeline."""
        if self.timeline:
            for entry in reversed(self.timeline):
                if entry['label'] == label:
                    return entry['end_time']
        return 0
    
    def get_last_entry(self, label=SegmentLabel.FOREGROUND):
        """Return the last entry in the timeline."""
        if self.timeline:
            for entry in reversed(self.timeline):
                if entry['label'] == label:
                    return entry
        return None

    def _apply_gain(self, audio, gain):
        """Apply gain to the audio segment."""
        if gain:
            logger.info(f"Applying gain of {gain} to audio segment.")
            return audio.apply_gain(gain)
        else:
            return audio
    
    def _strip_silence(self, audio):
        """Strip silence from the audio segment."""
        return audio.strip_silence(
            silence_thresh=-50, silence_len=50, padding=0)

    def _process_background_audio(self, audio, match_audio):
        bg = audio
        bg_volume_before = bg.dBFS
        #match the background audio to the foreground audio volume
        bg = match_target_amplitude(bg, match_audio.dBFS)
        if bg.dBFS != bg_volume_before:
            logger.info(
                f" Changed background volume from {bg_volume_before} to { bg.dBFS} while matching target.")
        
        #apply an overall gain to the background audio
        bg_volume_before = bg.dBFS
        bg = self._apply_gain(bg, self.params.get('background_music_gain', -5))
        if bg.dBFS != bg_volume_before:
            logger.info(
                f" Changed background volume from {bg_volume_before} to { bg.dBFS}.")
        return bg

    def add_to_timeline(self, audio, start_time, label=SegmentLabel.FOREGROUND, name=None, type=None,
                        duration=None, overlay_percentage=None, overlay_duration=None, 
                        fade_in=0, fade_out=0, gain=None, gain_match=False):
        """
        Add an audio segment to the timeline at a specific start time.
        Optionally specify duration, overlay percentage, and fade-in and fade-out effects.

        Args:
        audio (AudioSegment): The audio segment to add.
        start_time (int): The start time in milliseconds.
        label (SegmentLabel): The label for the audio segment.
        name (str, optional): The name of the audio segment.
        type (str, optional): The type of the audio segment.
        duration (int, optional): The duration in milliseconds. If specified, the audio is either truncated or looped to fit this duration.
        overlay_percentage (int, optional): The percentage of the audio segment to overlay with the previous one.
        overlay_duration (int, optional): The duration in milliseconds of the audio segment to overlay with the previous one.
        fade_in (int, optional): The duration in milliseconds of the fade-in effect.
        fade_out (int, optional): The duration in milliseconds of the fade-out effect.
        """
        audio = self._validate_audio(audio)
        last_entry = self.get_last_entry()
        #extend audio to meet end time, and trim, if necessary
        logging.debug(f"Audio duration: {len(audio)} before looping")
        self.loop_audio(audio, duration=duration)
        logging.debug(f"Audio duration: {len(audio)} after looping")

        #process audio
        audio = self._strip_silence(audio)
        if last_entry and gain_match:
            audio = match_target_amplitude(audio, target_dBFS=last_entry['audio'].dBFS)
        logger.info(f"Gain is {gain}")
        audio = self._apply_gain(audio, gain)
        audio = self._apply_effects(audio, fade_in, fade_out)
        
        logger.info(f" Overlay percentage is {overlay_percentage} and overlay duration is {overlay_duration}")
        overlay_duration = 0
        if overlay_duration:
            overlay_duration = overlay_duration
        elif overlay_percentage:
            previous_len = last_entry['audio']
            overlay_duration = int(len(previous_len) * (overlay_percentage / 100))

        overlay_start_time = start_time - overlay_duration
        logging.debug(f"Overlay start time is {overlay_start_time}, overlay duration is {overlay_duration} and start time is {start_time}")
        logging.debug(f"Audio length is {len(audio)}")
        self._add_to_timeline(audio, overlay_start_time, label,
                              name=name, type=type, end_time=len(audio)+overlay_start_time)


    def add_after_previous(self, audio, label=SegmentLabel.FOREGROUND, name=None, type=None,
                           duration=None,
                           overlay_percentage=None, overlay_duration=None, fade_in=0, fade_out=0, 
                           gain=None, gain_match=False):
        """
        Add an audio segment to the timeline after the previous one.
        Optionally specify duration, overlay percentage, and fade-in and fade-out effects.

        Args:
        audio (AudioSegment): The audio segment to add.
        label (SegmentLabel): The label for the audio segment.
        name (str, optional): The name of the audio segment.
        type (str, optional): The type of the audio segment.
        duration (int, optional): The duration in milliseconds. If specified, the audio is either truncated or looped to fit this duration.
        overlay_percentage (int, optional): The percentage of the audio segment to overlay with the previous one.
        overlay_duration (int, optional): The duration in milliseconds of the audio segment to overlay with the previous one.
        fade_in (int, optional): The duration in milliseconds of the fade-in effect.
        fade_out (int, optional): The duration in milliseconds of the fade-out effect.
        """
        if label == SegmentLabel.FOREGROUND:
            self.add_to_timeline(audio, start_time=self.get_last_end_time(label=label), label=label, name=name, type=type,
                                 duration=duration,
                                 overlay_percentage=overlay_percentage, overlay_duration=overlay_duration,
                                 fade_in=fade_in, fade_out=fade_out, gain=gain, gain_match=gain_match)
        elif label == SegmentLabel.BACKGROUND:
            self.add_background(audio, start_time=self.get_last_end_time(label=label), name=name, type=type,
                                fade_in=fade_in, fade_out=fade_out, gain=gain, gain_match=gain_match)

    def add_background(self, audio, start_time=0, end_time=None, fade_in=0, fade_out=0, name=None, type=None, 
                       gain=None, gain_match=False):
        """
        Add an audio segment to the background of the timeline.

        Args:
        audio (AudioSegment): The audio segment to add.
        start_time (int, optional): The start time in milliseconds.
        end_time (int, optional): The end time in milliseconds. If None, it extends to the end of the timeline.
        fade_in (int, optional): The duration in milliseconds of the fade-in effect.
        fade_out (int, optional): The duration in milliseconds of the fade-out effect.
        name (str, optional): The name of the audio segment.
        type (str, optional): The type of the audio segment.
        """
        last_entry = self.get_last_entry(label=SegmentLabel.BACKGROUND)
        
        audio = self._validate_audio(audio)
        audio = self._strip_silence(audio)
        if last_entry and gain_match:
            audio = match_target_amplitude(audio, target_dBFS=last_entry['audio'].dBFS)
        audio = self._apply_gain(audio, gain)
        audio = self._apply_effects(audio, fade_in, fade_out)
        self._add_to_timeline(
            audio, start_time, SegmentLabel.BACKGROUND, name=name, type=type, end_time=end_time)

    def set_end_times(self):
        """
        Set the end times for all entries in the timeline.
        """
        # pre-scan and set end times for all background audio
        bg_ends = {}
        bg_i = None
        for i, entry in enumerate(self.timeline):
            logger.info(
                f"Scanning entry {i} of {len(self.timeline)} with entry name {entry['name']} and label {entry['label']}")
            if entry['label'] == SegmentLabel.BACKGROUND and entry['end_time'] is None:
                bg_i = i
                bg_ends[bg_i] = 0
            elif entry['label'] == SegmentLabel.FOREGROUND:
                if bg_i is not None:
                    bg_ends[bg_i] = entry['end_time']

        #now set the end times if they aren't already set
        for k, v in bg_ends.items():
            if self.timeline[k]['end_time'] is None:
                self.timeline[k]['end_time'] = v
                logger.info(
                    f"Set end time for background audio {self.timeline[k]['name']} to {v}")
        
    def loop_audio(self, audio, duration, trim=True):
        """
        Loop audio if it is shorter than the duration.
        """
        if duration:
            if len(audio) < duration:
                num_loops = duration // len(audio)
                remainder = duration % len(audio)
                audio = audio * num_loops + audio[:remainder]
            
            if trim:
                audio = audio[:duration]
            
        return audio
    
    def merge_segment(self, audio, start_time, target_audio):
        """
        Merge a segment into the target audio.
        """

        # Pad silence to the start of the audio
        pad_silence = AudioSegment.silent(duration=start_time)
        padded_audio = pad_silence + audio
        return  padded_audio.overlay(target_audio)

    def render(self, filename, format):
        """
        Render the timeline to a single audio file.

        Args:
        filename (str): The name of the file to save the rendered audio to.
        format (str): The format to save the rendered audio in.
        """
        try:
            foreground_audio = AudioSegment.silent(duration=0)
            background_audio = AudioSegment.silent(duration=0)

            self.set_end_times()

            # now accumulate audio
            for entry in self.timeline:
                audio = entry['audio']
                #extend audio to meet end time, and trim, if necessary
                audio = self.loop_audio(audio, 
                                        duration=entry['end_time'] - entry['start_time'])
                logger.info(f"Audio duration: {len(audio)} after looping")
                
                if entry['label'] == SegmentLabel.FOREGROUND:
                    foreground_audio=self.merge_segment(audio, 
                                   target_audio=foreground_audio,
                                   start_time=entry['start_time'])
                else:
                    background_audio=self.merge_segment(audio, 
                                   target_audio=background_audio,
                                   start_time=entry['start_time'])

                

            logger.info(f"Foreground audio duration: {len(foreground_audio)} ")
            logger.info(f"Background audio duration: {len(background_audio)} ")
            if len(background_audio) > 0:
                background_audio = self._process_background_audio(background_audio, foreground_audio)
                if len(foreground_audio) > len(background_audio):
                    rendered_audio = foreground_audio.overlay(
                        background_audio)
                else:
                    rendered_audio = background_audio.overlay(foreground_audio)
            else:
                rendered_audio = foreground_audio

            with open(filename, 'wb') as file:
                rendered_audio.export(file, format=format)

            logger.info(
                f"Rendered timeline to file {filename} with duration {len(rendered_audio)}")
        except Exception as e:
            print(f"An error occurred while rendering: {str(e)}")

    def visualize_timeline(self, output_file='audio_timeline.html'):
        """
        Visualize the timeline using Plotly to generate a Gantt-style plot.
        """
        import plotly.graph_objects as go
        from plotly.offline import plot
        import plotly.express as px
        import pandas as pd
        from datetime import datetime

        data = []

        for i, entry in enumerate(self.timeline):
            duration = len(entry['audio'])

            # Calculate the end time if not provided
            if entry['end_time'] is None:
                end_time = entry['start_time'] + duration
            else:
                end_time = entry['end_time']

            start_datetime = datetime.fromtimestamp(entry['start_time'] / 1000)
            end_datetime = datetime.fromtimestamp(end_time / 1000)

            data.append({
                # Task': label.value,
                'Task': i,
                'Start': start_datetime,
                'Finish': end_datetime,
                'Name': entry['name'],
                'Type': entry['type'],
                'Duration': duration,
            })

        df = pd.DataFrame(data)

        fig = px.timeline(df, x_start="Start", x_end="Finish",
                          y="Task", color="Type", hover_data=["Name"])
        # fig.update_yaxes(autorange="reversed")  # Reverse the y-axis order

        # Create an HTML file from the figure
        plot(fig, filename=output_file, auto_open=False)

    def execute(self):
        """Render the timeline."""
        output_folder = self.global_results['output_folder']
        file_path = os.path.join(
            output_folder, f"{self.plugin_instance_name}.wav")
        logger.info(
            f"Rendering timeline for {self.plugin_instance_name} to file {file_path}")
        self.render(file_path, "wav")

        html_file_path = os.path.join(
            output_folder, f"{self.plugin_instance_name}_timeline.html")
        logger.info(
            f"Visualizing timeline for {self.plugin_instance_name} to file {html_file_path}")
        self.visualize_timeline(html_file_path)

        return {'file_path': file_path,
                'timeline_html': html_file_path}
