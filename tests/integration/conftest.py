import pytest
import logging
import sys
from pydub import AudioSegment
import numpy as np

# Configure logging to output to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

@pytest.fixture
def enforce_json_prompt_template():
    return """
        Can you tell me if this video title represents a video that would be appropriate for a 
        variety show that is meant to be uplifting and simulate nostalgic feelings? I want to 
        avoid controversial, misogynistic, and political content. You should be more lenient
        with channels from well known sources like NPR, PBS, and the BBC as well as late night
        talk shows.
        
        Make your best guess attempt and respond only with yes or no.

        The title is "{}" and the channel title is "{}
        and the description is:
        ````
        {}
        ```

        Respond only with the following schema:
    """

@pytest.fixture
def enforce_json_schema():
    return {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "enum": ["yes", "no"]
            }
        },
        "required": ["answer"]
    }
    
    

def generate_noisy_audio(duration, sample_rate=44100, channels=2, bit_depth=16):
    num_samples = int(duration * sample_rate / 1000)
    random_samples = np.random.randint(
        -2 ** (bit_depth - 1), 2 ** (bit_depth - 1), size=(num_samples, channels)
    )
    audio = AudioSegment(
        random_samples.tobytes(),
        frame_rate=sample_rate,
        sample_width=bit_depth // 8,
        channels=channels,
    )
    audio = audio.set_frame_rate(sample_rate)
    return audio[:duration]