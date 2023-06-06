import pytest
import dotenv
from llm_from_here.plugins.ytfetch import YtFetch
from llm_from_here.plugins.gpt import ChatApp
from conftest import *
import logging
import sys

dotenv.load_dotenv()
logging.basicConfig(stream=sys.stdout)

@pytest.fixture
def yt_fetch():
    yt_fetch = YtFetch(prefix="test_")
    yield yt_fetch
    yt_fetch.video_ids_returned.complete_session()

@pytest.fixture
def chat_app():
    # Create an instance of ChatApp with the necessary configuration
    return ChatApp(system_message="")

def test_search_video_with_duration(yt_fetch, chat_app, enforce_json_prompt_template, enforce_json_schema):
    query = 'Bill Burr'
    min_duration = 300
    max_duration = 660
    duration_search_filter = "medium"
    additional_query_text = '("stand up"|"live from here")'
    llm_filter_prompt = enforce_json_prompt_template.format("{{title}}", "{{description}}", "{{channel_title}}")
    llm_filter_js = enforce_json_schema
    
    # Call the function being tested
    result = yt_fetch.search_video_with_duration(query = f"{query} {additional_query_text}", 
                                                 min_duration = min_duration, 
                                                 max_duration = max_duration,
                                                duration_search_filter = duration_search_filter,
                                                llm_filter_prompt = llm_filter_prompt,
                                                llm_filter_js = llm_filter_js,
                                                chat_app = chat_app)

    # Assertions
    print(f"FINAL RETURNED Result: {result}")
    if result:
        assert 'video_id' in result
        assert 'title' in result
        assert 'channel_title' in result
        assert 'video_url' in result
        assert result['video_id'] != ''
        assert result['title'] != ''
        assert result['channel_title'] != ''
        assert result['video_url'].startswith('https://www.youtube.com/watch?v=')




    # def search_video_with_duration(self, query, min_duration, max_duration, 
    #                                duration_search_filter = None, 
    #                                description_filters=None, 
    #                                orderby="relevance",
    #                                llm_filter_prompt=None,
    #                                llm_filter_js=None,
    #                                chat_app=None):