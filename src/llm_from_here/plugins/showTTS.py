import numpy as np
import re

from scipy.io.wavfile import write as write_wav
from gtts import gTTS
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

import os
import dotenv
import logging
import openai

from llm_from_here.llm_env import (
    build_openrouter_client,
    get_openrouter_tts_model,
    get_openrouter_tts_voice,
    is_openrouter_free_mode,
)

logger = logging.getLogger(__name__)

dotenv.load_dotenv()


def split_sentences(text):
    # Define the pattern for sentence splitting
    sentence_pattern = r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s"

    # Split the text into sentences using the pattern
    sentences = re.split(sentence_pattern, text)

    return sentences


def trim_silence_np_array(audio_array, sample_rate):
    # Convert the numpy array to an audio segment
    audio_segment = AudioSegment(
        audio_array.tobytes(),
        frame_rate=sample_rate,
        frame_width=audio_array.dtype.itemsize,
        channels=1,
    )

    # Convert the audio_segment to stereo if it is not
    if audio_segment.channels == 1:
        audio_segment = audio_segment.set_channels(2)

    start_trim = detect_nonsilent(
        audio_segment, min_silence_len=100, silence_thresh=-50
    )[0]
    end_trim = detect_nonsilent(
        audio_segment.reverse(), min_silence_len=100, silence_thresh=-50
    )[0]
    duration = len(audio_segment)
    trimmed_audio = audio_segment[start_trim[0] : duration - end_trim[0]]

    # Convert the trimmed audio back to a numpy array
    trimmed_audio_array = np.array(trimmed_audio.get_array_of_samples())

    return trimmed_audio_array


class ShowTextToSpeech:
    def __init__(self):
        self.pieces = None
        self.audio_file = None
        self.models_preloaded = False
        self.tts_model_name = get_openrouter_tts_model()
        self.tts_voice = get_openrouter_tts_voice()
        self._openrouter_client: openai.OpenAI | None = None

    def speak(self, text, output_file, fast=False):
        if fast or is_openrouter_free_mode():
            if is_openrouter_free_mode() and not fast:
                logger.info(
                    "LLMFH_OPENROUTER_FREE_MODE: using gTTS instead of paid OpenRouter TTS for: %s",
                    text[:80],
                )
            logger.info(f"Using fast TTS for text: {text}")
            self._speak_gtts(text, output_file)
        else:
            logger.info(f"Using slow TTS for text: {text}")
            self._speak_openrouter_tts(text, output_file)

    def _speak_gtts(self, text, output_file):
        # fast version that uses google TTS
        tts = gTTS(text=text, lang="en")
        temp_mp3_file = "temp.mp3"
        tts.save(temp_mp3_file)

        # Convert the MP3 file to WAV using pydub
        audio = AudioSegment.from_mp3(temp_mp3_file)
        audio.export(output_file, format="wav")

        # Remove the temporary MP3 file
        os.remove(temp_mp3_file)
        logger.info(f"Successfully generated audio file: {output_file}")
        self.audio_file = output_file

    def _get_openrouter_client(self) -> openai.OpenAI:
        if self._openrouter_client is None:
            self._openrouter_client = build_openrouter_client()
        return self._openrouter_client

    def _speak_openrouter_tts(self, text, output_file):
        client = self._get_openrouter_client()

        response = client.audio.speech.create(
            model=self.tts_model_name,
            voice=self.tts_voice,
            input=text,
        )

        # Save the audio to a file
        response.stream_to_file(output_file + ".mp3")

        # convert to wav
        audio = AudioSegment.from_mp3(output_file + ".mp3")
        audio.export(output_file, format="wav")
        os.remove(output_file + ".mp3")

        logger.info(f"Successfully generated audio file: {output_file}")
        self.audio_file = output_file


if __name__ == "__main__":
    import sys

    # get command line args
    text = sys.argv[1]
    speed = sys.argv[2]
    output_file = sys.argv[3]

    show_tts = ShowTextToSpeech()

    if speed == "fast":
        show_tts.speak(text, output_file, fast=True)
    elif speed == "slow":
        show_tts.speak(text, output_file, fast=False)
