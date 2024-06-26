import pytest
from unittest.mock import Mock
from llm_from_here.supaQueue import SupaQueue
import llm_from_here.plugins.gpt as gpt
from llm_from_here.plugins.guestSelection import GuestSelection 

class TestGuestSelection:
    @pytest.fixture
    def mock_chat_app(self):
        return Mock(spec=gpt.ChatApp)

    @pytest.fixture
    def mock_supa_queue(self):
        return Mock(spec=SupaQueue)

    @pytest.fixture
    def guest_selection(self, mock_chat_app, mock_supa_queue):
        params = {"guest_categories": [{"name": "test", "prompt": "Hello"}]}
        global_results = []
        plugin_instance_name = 'test_instance'
        return GuestSelection(params, global_results, plugin_instance_name, chat_app=mock_chat_app)

    def test_add_to_queue(self, guest_selection, mock_supa_queue, mock_chat_app):
        n = 1
        prompt = 'Hello'
        mock_chat_app.enforce_list_response.return_value = ['guest1']*n
        guest_selection.add_to_queue(mock_supa_queue, n, prompt)
        mock_chat_app.enforce_list_response.assert_called_with(prompt, n, log_prompt=True)
        mock_supa_queue.enqueue.assert_called_with(['guest1']*n)

    def test_get_params(self, guest_selection):
        guest_category = {"name": "test_name", "prompt": "test_prompt"}
        result = guest_selection.get_params(guest_category)
        assert result == ("test_name", "test_prompt", 1, 1, 100, 1, 1)

