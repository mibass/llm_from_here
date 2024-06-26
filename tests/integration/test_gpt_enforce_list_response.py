# import llm_from_here.plugins.gpt as gpt
import llm_from_here.plugins.llm_factory as llm_factory
import pytest
import dotenv
import json
from conftest import *

dotenv.load_dotenv()

@pytest.fixture
def chat_app():
    # return gpt.ChatApp("")
    return llm_factory.get_llm_provider()

prompts = [
"""
Generate a list of band names that would be appropriate for a sometimes nostalgic, sometimes hip, sometimes avante garde variety show on NPR.
These should be real band names that are not controversial, misogynistic, or political.
They should not be made up.
Give priority to guests if they've been on Live From Here, Live On KEXP, Morning Becomes Electic, or Tiny desk concerts.
Make sure no more than 25% of the bands are from the same genre.
"""
]

@pytest.mark.parametrize("prompt", prompts)
def test_enforce_list_response(chat_app, prompt):
    print(prompt)
    n=5
    response = chat_app.enforce_list_response(
        prompt, num_entries=n, log_prompt=True, tries=5
    )
    print(response)
    print("list has length {}".format(len(response)))
    # ingore case in response
    # asset = response["answer"].lower() == expected_answer.lower()
    # assert response == {"answer": expected_answer}

@pytest.mark.parametrize("prompt", prompts)
def test_enforce_consensus_list_response(chat_app, prompt):
    print(prompt)
    n=50
    response = chat_app.enforce_list_response_consensus(
        prompt, num_entries=n, log_prompt=True, tries=5
    )
    print(response)
    print("list has length {}".format(len(response)))
    assert len(response) == n
