import unittest
import jsonschema
from unittest.mock import patch, MagicMock
from llm_from_here.plugins.gpt import ChatApp
import json
import openai

class TestChatApp(unittest.TestCase):
    @patch('llm_from_here.plugins.gpt.openai.OpenAI')
    def setUp(self, mock_openai):
        # Create a mock response object with the necessary attributes
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test response"))]

        # Set up the mock OpenAI client
        self.mock_client = mock_openai.return_value
        self.mock_client.chat.completions.create.return_value = mock_response

        self.system_message = "Welcome"
        self.chat_app = ChatApp(self.system_message)


    def test_chat(self):
        # Test the chat method
        response = self.chat_app.chat("Test message")

        # Check the API was called with the right arguments
        self.mock_client.chat.completions.create.assert_called_once_with(
            model=ChatApp.MODEL_NAME,
            messages=[
                {"role": "system", "content": self.system_message},
                {"role": "user", "content": "Test message"}
            ]
        )

        # Check the response was as expected
        self.assertEqual(response, "Test response")
        
    def test_chat_appends_responses(self):

        # Call the chat method
        self.chat_app.chat("Test message")

        # Check the responses list was appended
        response = self.chat_app.responses[0]
        self.assertEqual(response.choices[0].message.content, "Test response")

    def test_chat_appends_messages(self):
        # Call the chat method
        self.chat_app.chat("Test message")

        # Check the messages list was appended
        self.assertEqual(self.chat_app.messages[-1]["role"], "assistant")
        self.assertEqual(self.chat_app.messages[-1]["content"], "Test response")


    def test_enforce_json_response_success(self):
        message = "Hello"
        json_schema = {"type": "object", "properties": {
            "response": {"type": "string"}}}
        response = '{"response": "World"}'
        expected_result = json.loads(response)

        # Mock the chat method to return a valid response
        with patch.object(ChatApp, 'chat', return_value=response):
            result = self.chat_app.enforce_json_response(
                message, json_schema, delay=0, backoff=0, tries=1)

        self.assertEqual(result, expected_result)

    def test_enforce_json_response_failure(self):
        message = "Hello"
        json_schema =   {"type": "object", "properties": {
                            "response": {"type": "string"}
                            },
                         "required": ["response"]
                        }
        response = '{}'

        # Mock the chat method to return an invalid response
        with patch.object(ChatApp, 'chat', return_value=response):
            with self.assertRaises(jsonschema.exceptions.ValidationError):
                self.chat_app.enforce_json_response(
                    message, json_schema, delay=0, backoff=0, tries=2)

    def test_enforce_json_response_retry(self):
        message = "Hello"
        json_schema =   {"type": "object", "properties": {
                            "response": {"type": "string"}
                            },
                         "required": ["response"]
                        }
        invalid_response = '{"invalid_key": "World"}'
        valid_response = '{"response": "World"}'
        
        # Mock the chat method to return an invalid response first and then a valid response
        with patch.object(ChatApp, 'chat', side_effect=[invalid_response, valid_response]):
            result = self.chat_app.enforce_json_response(
                message, json_schema, delay=0, backoff=0, tries=2)

        self.assertEqual(result, json.loads(valid_response))


if __name__ == '__main__':
    unittest.main()
