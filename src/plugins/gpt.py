import openai
import os
import logging
from retry import retry

# Setup basic logging
logger = logging.getLogger(__name__)

class ChatApp:
    MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
    
    def __init__(self, system_message):
        """
        Initialize the chat app.
        Args:
            system_message (str): The system message to start the conversation.
        """
        # Setting the API key to use the OpenAI API
        openai.api_key = os.getenv("OPENAI_API_KEY")
        self.messages = [
            {"role": "system", "content": system_message},
        ]
        self.system_message = system_message
        self.responses = []

    @retry((openai.error.RateLimitError, openai.error.AuthenticationError, openai.error.APIError), tries=5, delay=2, backoff=2)
    def chat(self, message, strip_quotes=False):
        """
        Sends a message to the OpenAI API and returns the assistant's response.
        Args:
            message (str): The message to send.
            strip_quotes (bool): If true, strips quotes from the response.
        Returns:
            The assistant's response.
        """
        messages = self.messages + [{"role": "user", "content": message}]
        try:
            response = openai.ChatCompletion.create(
                model=self.MODEL_NAME, 
                messages=messages
            )
        except Exception as e:
            logger.error(f"Error interacting with OpenAI API: {e}")
            raise

        self.messages.append({"role": "assistant", "content": response["choices"][0]["message"]["content"]})
        self.responses.append(response)
        
        response_text = response["choices"][0]["message"]["content"]
        return response_text.strip('"') if strip_quotes else response_text

    def reset_conversation(self):
        """
        Resets the conversation to the initial system message.
        """
        self.messages = [
            {"role": "system", "content": self.system_message},
        ]
        self.responses = []

    def save_conversation(self, file_path):
        """
        Saves the conversation to a file.
        Args:
            file_path (str): The path to the file where the conversation should be saved.
        """
        try:
            with open(file_path, 'w') as f:
                for message in self.messages:
                    f.write(f'{message["role"]}: {message["content"]}\n')
        except Exception as e:
            logging.error(f"Error saving conversation: {e}")
            raise