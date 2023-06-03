
import unittest
from unittest.mock import patch, MagicMock, call
from pydub import AudioSegment
import sys, os
sys.path.append('../src/plugins')
from audioTimeline import AudioTimeline, SegmentLabel
import tempfile
import numpy as np


def generate_noisy_audio(duration, sample_rate=44100, channels=2, bit_depth=16):
    num_samples = int(duration * sample_rate / 1000)
    random_samples = np.random.randint(-2**(bit_depth - 1), 2**(bit_depth - 1), size=(num_samples, channels))
    audio = AudioSegment(random_samples.tobytes(), frame_rate=sample_rate, sample_width=bit_depth // 8, channels=channels)
    audio = audio.set_frame_rate(sample_rate)
    return audio[:duration]


# import logging
# logging.basicConfig(level=logging.DEBUG)

class AudioTimelineTest(unittest.TestCase):
    def setUp(self):
        self.timeline = AudioTimeline()

    def test_add_to_timeline(self):
        duration = 1000  # Duration in milliseconds
        audio = generate_noisy_audio(duration)

        self.timeline.add_to_timeline(audio, start_time=0)
        self.assertEqual(len(self.timeline.timeline), 1)
        self.assertEqual(self.timeline.timeline[0]['start_time'], 0)
        self.assertEqual(self.timeline.timeline[0]['label'], SegmentLabel.FOREGROUND)

    def test_add_after_previous(self):
        audio1 = generate_noisy_audio(1000)
        audio2 = generate_noisy_audio(2000)

        self.timeline.add_to_timeline(audio1, start_time=0)
        self.timeline.add_after_previous(audio2)

        self.assertEqual(len(self.timeline.timeline), 2)
        self.assertEqual(self.timeline.timeline[1]['start_time'], 1000)
        self.assertEqual(self.timeline.timeline[1]['label'], SegmentLabel.FOREGROUND)



    def test_add_background(self):
        audio = AudioSegment.silent(duration=1000)
        self.timeline.add_background(audio, start_time=0)
        self.assertEqual(len(self.timeline.timeline), 1)
        self.assertEqual(self.timeline.timeline[0]['start_time'], 0)
        self.assertEqual(self.timeline.timeline[0]['label'], SegmentLabel.BACKGROUND)

    def test_set_end_times(self):
        duration1 = 1000  # Duration of the first audio segment in milliseconds
        duration2 = 2000  # Duration of the second audio segment in milliseconds
        audio1 = generate_noisy_audio(duration1)
        audio2 = generate_noisy_audio(duration2)

        self.timeline.add_to_timeline(audio1, start_time=0)
        self.timeline.add_to_timeline(audio2, start_time=duration1)

        self.timeline.set_end_times()

        self.assertEqual(len(self.timeline.timeline), 2)
        self.assertEqual(self.timeline.timeline[0]['end_time'], duration1)
        self.assertEqual(self.timeline.timeline[1]['end_time'], duration1 + duration2)


    def test_loop_audio(self):
        audio = AudioSegment.silent(duration=1000)
        duration = 5000

        looped_audio = self.timeline.loop_audio(audio, duration)

        self.assertEqual(len(looped_audio), duration)
        self.assertEqual(looped_audio[:len(audio)], looped_audio[-len(audio):])


    def test_render(self):
        audio1 = AudioSegment.silent(duration=1000)
        audio2 = AudioSegment.silent(duration=2000)

        self.timeline.add_to_timeline(audio1, start_time=0)
        self.timeline.add_after_previous(audio2)

        with tempfile.TemporaryDirectory() as temp_dir:
            filename = f"{temp_dir}/test_audio.wav"
            format = 'wav'
            self.timeline.render(filename, format)
            
            # Assert that the file was rendered successfully
            self.assertTrue(os.path.exists(filename))

    def test_visualize_timeline(self):
        audio = AudioSegment.silent(duration=1000)
        self.timeline.add_to_timeline(audio, start_time=0)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = f"{temp_dir}/test_timeline.html"
            self.timeline.visualize_timeline(output_file)
            
            # Assert that the HTML file was generated successfully
            self.assertTrue(os.path.exists(output_file))
            
    def test_execute(self):
        # Create a temporary directory for the output files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Set the output folder in the global results
            self.timeline.global_results = {'output_folder': temp_dir}

            # Create some test audio segments
            audio1 = AudioSegment.silent(duration=1000)
            audio2 = AudioSegment.silent(duration=2000)

            # Add the audio segments to the timeline
            self.timeline.add_to_timeline(audio1, start_time=0)
            self.timeline.add_after_previous(audio2)

            # Execute the timeline rendering
            result = self.timeline.execute()

            # Assert that the rendered file exists in the output folder
            self.assertTrue(os.path.isfile(result['file_path']))

            # Assert that the timeline HTML visualization exists in the output folder
            self.assertTrue(os.path.isfile(result['timeline_html']))

    def tearDown(self):
        # Clean up any resources used by the test case
        pass
    
    
if __name__ == "__main__":
    unittest.main()
