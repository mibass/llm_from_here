import unittest
from unittest.mock import patch, MagicMock
import sys
sys.path.append('../src/plugins')
from gpt import ChatApp  # Your class to test

SYSTEM_MESSAGE="You are a big shot new york live show producer, writer, and performer. You are current the show runner for the Live From Here show and are calling all the shots. You are very emotional and nostalgic and like to listen to music, podcasts, npr, and long-form improv comedy."
class TestChatApp(unittest.TestCase):

    @patch('openai.ChatCompletion.create')
    def test_chat(self, mock_create):
        # Set up the mock
        mock_create.return_value = {
            "choices": [
                {"message": {"content": "Test response"}}
            ]
        }

        # Initialize ChatApp
        chat_app = ChatApp(system_message=SYSTEM_MESSAGE)

        # Test the chat method
        response = chat_app.chat("Test message")

        # Check the API was called with the right arguments
        mock_create.assert_called_once_with(
            model=ChatApp.MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": "Test message"}
            ]
        )

        # Check the response was as expected
        self.assertEqual(response, "Test response")

    @patch('openai.ChatCompletion.create')
    def test_chat_appends_responses(self, mock_create):
        # Set up the mock
        mock_create.return_value = {
            "choices": [
                {"message": {"content": "Test response"}}
            ]
        }

        # Initialize ChatApp
        chat_app = ChatApp(system_message=SYSTEM_MESSAGE)

        # Call the chat method
        chat_app.chat("Test message")

        # Check the responses list was appended
        self.assertEqual(chat_app.responses[0]["choices"][0]["message"]["content"], "Test response")

    @patch('openai.ChatCompletion.create')
    def test_chat_appends_messages(self, mock_create):
        # Set up the mock
        mock_create.return_value = {
            "choices": [
                {"message": {"content": "Test response"}}
            ]
        }

        # Initialize ChatApp
        chat_app = ChatApp(system_message=SYSTEM_MESSAGE)

        # Call the chat method
        chat_app.chat("Test message")

        # Check the messages list was appended
        self.assertEqual(chat_app.messages[-1]["role"], "assistant")
        self.assertEqual(chat_app.messages[-1]["content"], "Test response")


if __name__ == '__main__':
    unittest.main()
