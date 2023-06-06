import pytest
import logging
import sys

# Configure logging to output to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

@pytest.fixture
def enforce_json_prompt_template():
    return """
        Can you tell me if this video title represents a video that would be appropriate for a 
        variety show that is meant to be uplifting and simulate nostalgic feelings? I want to 
        avoid controversial, misogynistic, and political content. You should be more lenient
        with channels from well known sources like NPR, PBS, and the BBC as well as late night
        talk shows such as Conan, Jimmy Fallon, Jimmy Kimmel, Letterman, Leno, or any old time late show.
        
        Make your best guess attempt and respond only with yes or no.

        The title is "{}" and the description is "{}"
        and the channel title is "{}".

        Respond only with the following schema:
    """

@pytest.fixture
def enforce_json_schema():
    return {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "pattern": r"^yes$|^no$"
            }
        },
        "required": ["answer"]
    }
    