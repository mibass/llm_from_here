import llm_from_here.plugins.gpt as gpt
import pytest
import dotenv
import json
from conftest import *

dotenv.load_dotenv()

@pytest.fixture
def chat_app():
    return gpt.ChatApp("")

@pytest.mark.parametrize("title, description, channel_title, expected_answer", [
    #no tests
    ("George Takei Gets SLAMMED, Shows How Woke Hollywood Elites Really Think | They Want You To SUFFER",
        "#Ukraine #Hollywood #GeorgeTakei\nJoin my community on Locals! https://rkoutpost.locals.com/\nJoin Geeks + Gamers on Locals! https://geeksandgamers.locals.com/",
        "Ryan Kinel",
        "no"),
#    (" Joe Rogan Experience #1413 - Bill Maher ",
#         "Bill Maher is a comedian, political commentator, and television host. The new season of his show \"Real Time with Bill Maher\" premieres January 17 on HBO.",
#         "PowerfulJRE",
#         "no"),
#    ("The Joe Rogan Experience #1554 - Kanye West",
#         "Kanye West is a rapper, record producer, fashion designer, and current independent candidate for office in the 2020 United States Presidential Election.",
#         "PowerfulJRE",
#         "no"),
#     ("The Joe Rogan Experience #1555 - Alex Jones & Tim Dillon",
#         "Alex Jones is a radio show host, filmmaker, writer, and conspiracy theorist. Tim Dillon is a comedian, tour guide, and host. His podcast \"The Tim Dillon Show\" is available on YouTube & Apple Podcasts.",   
#         "PowerfulJRE",
#         "no"),
#     ("EXPOSING Matty Healy (Taylor Swift's OFFENSIVE and TOXIC Boyfriend)","","", "no"),
#     ("The Disturbing Tom Hanks Conspiracy", "","", "no"),
#     ("Tom Cruise's Heated Interview With Matt Lauer | Archives | TODAY", "", "", "no"),
#     #yes tests
#     ("Tom Cruise Watches One Movie Each Day", 
#         "Jimmy geeks out with Tom Cruise over laser discs when he stops by to promote his action flick, Edge of Tomorrow. ", 
#         "The Tonight Show Starring Jimmy Fallon",
#         "yes")
    
])
def test_enforce_json_response(chat_app, enforce_json_prompt_template, enforce_json_schema,
                               title, description, channel_title, 
                               expected_answer):

    json_prompt = enforce_json_prompt_template.format(title, description, channel_title)
    prompt = json_prompt + json.dumps(enforce_json_schema)
    print(prompt)
    response = chat_app.enforce_json_response(prompt, enforce_json_schema)
    print(response)
    assert response == {"answer": expected_answer}
