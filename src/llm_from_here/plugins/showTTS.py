import numpy as np
import re

from scipy.io.wavfile import write as write_wav
from gtts import gTTS
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
from pydub.silence import detect_nonsilent

import os
import tempfile
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


def _segment_from_openrouter_speech_file(path: str) -> AudioSegment:
    """Decode binary returned by ``audio.speech.create`` (OpenRouter / OpenAI-compatible)."""
    size = os.path.getsize(path)
    if size < 64:
        raise ValueError(f"Speech payload too small ({size} bytes)")
    with open(path, "rb") as f:
        head = f.read(1024)
    stripped = head.lstrip()
    if stripped.startswith((b"{", b"[")):
        snippet = stripped[:1200].decode("utf-8", errors="replace")
        raise ValueError(
            "OpenRouter speech endpoint returned JSON/text instead of audio: " + snippet
        )
    if head.startswith(b"RIFF"):
        return AudioSegment.from_file(path, format="wav")
    if head.startswith(b"ID3") or (
        len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0
    ):
        return AudioSegment.from_file(path, format="mp3")
    if head.startswith(b"OggS"):
        return AudioSegment.from_file(path, format="ogg")
    try:
        return AudioSegment.from_file(path)
    except CouldntDecodeError as err:
        raise ValueError(
            "Could not decode OpenRouter speech payload "
            f"(size={size} bytes, hex_prefix={head[:32].hex()})"
        ) from err


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

    def speak(self, text, output_file, fast=False, voice=None, model=None):
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
            self._speak_openrouter_tts(text, output_file, voice=voice, model=model)

    def _speak_gtts(self, text, output_file):
        # fast version that uses google TTS
        tts = gTTS(text=text, lang="en")
        fd, temp_mp3_file = tempfile.mkstemp(suffix=".mp3", prefix="llmfh_gtts_")
        os.close(fd)
        try:
            tts.save(temp_mp3_file)
            audio = AudioSegment.from_file(temp_mp3_file, format="mp3")
            audio.export(output_file, format="wav")
        finally:
            try:
                os.remove(temp_mp3_file)
            except OSError:
                pass
        logger.info(f"Successfully generated audio file: {output_file}")
        self.audio_file = output_file

    def _get_openrouter_client(self) -> openai.OpenAI:
        if self._openrouter_client is None:
            self._openrouter_client = build_openrouter_client()
        return self._openrouter_client

    def _speak_openrouter_tts(self, text, output_file, voice=None, model=None):
        client = self._get_openrouter_client()

        use_model = model or self.tts_model_name
        use_voice = voice or self.tts_voice

        # OpenRouter validates response_format strictly (typically mp3|pcm only).
        response = client.audio.speech.create(
            model=use_model,
            voice=use_voice,
            input=text,
            response_format="mp3",
        )

        fd, tmp_audio = tempfile.mkstemp(suffix=".mp3", prefix="llmfh_openrouter_tts_")
        os.close(fd)
        try:
            response.stream_to_file(tmp_audio)
            audio = _segment_from_openrouter_speech_file(tmp_audio)
            audio.export(output_file, format="wav")
        finally:
            try:
                os.remove(tmp_audio)
            except OSError:
                pass

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
