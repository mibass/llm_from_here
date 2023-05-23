from IPython.display import Audio, display
import numpy as np
import re

# from bark.generation import (
#     generate_text_semantic,
#     preload_models,
# )
# from bark.api import semantic_to_waveform
from bark import SAMPLE_RATE, generate_audio, preload_models
from scipy.io.wavfile import write as write_wav
from gtts import gTTS
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

import logging
logger = logging.getLogger(__name__)

MODEL_SETTINGS = {'text_use_small':True,
                'coarse_use_small':True,
                'fine_use_small':True,
                'text_use_gpu':False,
                'coarse_use_gpu':False,
                'fine_use_gpu':False,
                }


def split_sentences(text):
    # Define the pattern for sentence splitting
    sentence_pattern = r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s'

    # Split the text into sentences using the pattern
    sentences = re.split(sentence_pattern, text)

    return sentences

def trim_silence_np_array(audio_array, sample_rate):
    # Convert numpy array to audio segment
    audio_segment = AudioSegment(audio_array.tobytes(), 
                                 frame_rate=sample_rate, 
                                 sample_width=audio_array.dtype.itemsize, 
                                 channels=1)

    # Check if the audio_segment is stereo and convert it if not
    if audio_segment.channels == 1:
        audio_segment = audio_segment.set_channels(2)

    start_trim = detect_nonsilent(audio_segment, min_silence_len=100, silence_thresh=-50)[0]
    end_trim = detect_nonsilent(audio_segment.reverse(), min_silence_len=100, silence_thresh=-50)[0]
    duration = len(audio_segment)
    trimmed_audio = audio_segment[start_trim[0]:duration-end_trim[0]]

    # Convert the trimmed audio back to a numpy array
    trimmed_audio_array = np.array(trimmed_audio.get_array_of_samples())
    
    return trimmed_audio_array

class ShowTextToSpeech:
    def __init__(self):
        self.pieces = None
        self.audio_file = None
        self.models_preloaded = False


    def speak(self, text, output_file, fast=False):
        if fast:
            logger.info(f"Using fast TTS for text: {text}")
            self._speak_gtts(text, output_file)
        else:
            logger.info(f"Using slow TTS for text: {text}")
            if not self.models_preloaded:
                self.models_preloaded = True
                preload_models(**MODEL_SETTINGS)
                logger.info(f"Finished preloading models for slow TTS.")
            self._speak_bark(text, output_file)

    def _speak_gtts(self, text, output_file):
        #fast version that uses google TTS
        tts = gTTS(text=text, lang='en')
        temp_mp3_file = "temp.mp3"
        tts.save(temp_mp3_file)
        
        # Convert the MP3 file to WAV using pydub
        audio = AudioSegment.from_mp3(temp_mp3_file)
        audio.export(output_file, format="wav")

        # Remove the temporary MP3 file
        import os
        os.remove(temp_mp3_file)
        logger.info(f'Successfully generated audio file: {output_file}')
        self.audio_file = output_file
        
    def _speak_bark(self, text, output_file):
        #https://github.com/suno-ai/bark#-faq
        #demos: https://replicate.com/suno-ai/bark?prediction=aeqqwzybnbfm7ai2mf5aqkmm7u
        #slow version that uses Bark
        GEN_TEMP = 0.7
        SPEAKER = "v2/en_speaker_6"

        self.pieces = []
        sentences = split_sentences(text)
        for sentence in sentences:
            logger.info(f'Generating bark audio for sentence: {sentence}')
            # semantic_tokens = generate_text_semantic(
            #     sentence,
            #     history_prompt=SPEAKER,
            #     temp=GEN_TEMP,
            #     min_eos_p=0.05,  # this controls how likely the generation is to end
            # )

            # audio_array = semantic_to_waveform(semantic_tokens, history_prompt=SPEAKER,)
            audio_array = generate_audio(sentence, 
                                         history_prompt=SPEAKER, 
                                         text_temp=GEN_TEMP,
                                         silent=True)
            #convert to 16 bit and trim silence
            audio_array_16bit = np.int16(audio_array / np.max(np.abs(audio_array)) * 32767)
            trimmmed_audio_array = trim_silence_np_array(audio_array_16bit, SAMPLE_RATE)
            
            self.pieces += [trimmmed_audio_array]
        
        #concat peices and convert to 16 bit wav
        audio_array = np.concatenate(self.pieces)
        write_wav(output_file, SAMPLE_RATE, audio_array_16bit)

        logger.info(f'Successfully generated audio file: {output_file}')
        self.audio_file = output_file
        
    def print_sample(self):
        try:
            # Check if running in an interactive notebook environment
            #Audio(np.concatenate(self.pieces), rate=SAMPLE_RATE)
            display(Audio(self.audio_file))
        except NameError:
            print("Cannot print/play audio sample in this environment.")
    
    

if __name__ == "__main__":
    import sys
    #get command line args
    text = sys.argv[1]
    speed = sys.argv[2]
    output_file = sys.argv[3]
    
    show_tts = ShowTextToSpeech()
    
    if speed == "fast":
        show_tts.speak(text, output_file, fast=True)
    elif speed == "slow":
        show_tts.speak(text, output_file, fast=False)
