import llm_from_here.plugins.gpt as gpt
import pytest
import dotenv

from llm_from_here.schemas.llm_outputs import LlmFilterResponse

from conftest import *  # noqa: F401,F403

dotenv.load_dotenv()


@pytest.fixture
def chat_app():
    return gpt.ChatApp("")


@pytest.mark.parametrize(
    "title, description, channel_title, expected_answer",
    [
        (
            "George Takei Gets SLAMMED, Shows How Woke Hollywood Elites Really Think | They Want You To SUFFER",
            "#Ukraine #Hollywood #GeorgeTakei\nJoin my community on Locals! https://rkoutpost.locals.com/\nJoin Geeks + Gamers on Locals! https://geeksandgamers.locals.com/",
            "Ryan Kinel",
            "no",
        ),
    ],
)
def test_run_structured_llm_filter(
    chat_app,
    enforce_json_prompt_template,
    title,
    description,
    channel_title,
    expected_answer,
):
    prompt = enforce_json_prompt_template.format(title, channel_title, description)
    print(prompt)
    response = chat_app.run_structured(prompt, LlmFilterResponse, log_prompt=True)
    print(response)
    assert response["answer"].lower() == expected_answer.lower()
