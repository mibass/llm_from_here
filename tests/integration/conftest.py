import logging
import os
import sys

import numpy as np
import pytest
from pydub import AudioSegment

pytestmark = pytest.mark.integration

# Configure logging to output to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def _truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


@pytest.fixture(scope="session", autouse=True)
def _integration_openrouter_use_free_models():
    """
    After test modules run dotenv.load_dotenv(), prefer OpenRouter free-tier chat.

    Sets LLMFH_OPENROUTER_FREE_MODE so unresolved chat model becomes openrouter/free,
    structured output defaults to tool mode, and slow TTS uses gTTS.

    Opt out with LLMFH_INTEGRATION_USE_FREE_OPENROUTER=0 to keep .env OPENROUTER_* as-is.
    """
    if not _truthy("LLMFH_INTEGRATION_USE_FREE_OPENROUTER", "1"):
        yield
        return
    os.environ["LLMFH_OPENROUTER_FREE_MODE"] = "1"
    os.environ.pop("OPENROUTER_MODEL", None)
    yield


@pytest.fixture
def enforce_json_prompt_template():
    """Prompt for video appropriateness (structured output schema is enforced by pydantic-ai)."""
    return (
        "Can you tell me if this video title represents a video that would be appropriate for a "
        "variety show that is meant to be uplifting and simulate nostalgic feelings? I want to "
        "avoid controversial, misogynistic, and political content. You should be more lenient "
        "with channels from well known sources like NPR, PBS, and the BBC as well as late night "
        "talk shows.\n\n"
        "Make your best guess attempt and respond only with yes or no.\n\n"
        "The title is \"{}\" and the channel title is \"{}\" and the description is:\n{}"
    )


@pytest.fixture
def enforce_json_schema():
    """Legacy fixture name — schema is now ``LlmFilterResponse`` in code."""
    return {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "enum": ["yes", "no"],
            }
        },
        "required": ["answer"],
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
