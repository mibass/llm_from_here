import anthropic
import os
import logging
from retry import retry
import jsonschema
import json
import re
import yaml
from collections import Counter

from .gpt import ChatApp

# Setup basic logging
logger = logging.getLogger(__name__)

import dotenv
dotenv.load_dotenv()

class ClaudeChatApp(ChatApp):
    MODEL_NAME = os.getenv("CLAUDE_MODEL_NAME", "claude-3-opus-20240229")

    def __init__(self, system_message=""):
        # super().__init__(system_message)
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.system_message = system_message
        self.responses = []
        self.messages = []
        logger.info(f"Using Claude model: {self.MODEL_NAME}")

    def chat(self, message, strip_quotes=False, tries=5, delay=2, backoff=2):
        @retry(
            (
                anthropic.RateLimitError,
                anthropic.AuthenticationError,
                anthropic.APIError,
            ),
            tries=tries,
            delay=delay,
            backoff=backoff,
        )
        def chat(self, message, strip_quotes=False):
            #if the last message was a user message, remove it
            if self.messages and self.messages[-1]["role"] == "user":
                self.messages.pop()
            self.messages = self.messages + [{"role": "user", "content": message}]
            try:
                response = self.client.messages.create(
                    model=self.MODEL_NAME, max_tokens=4096, messages=self.messages,
                    system=self.system_message
                )
            except Exception as e:
                logger.error(f"Error interacting with Anthropic API: {e}")
                raise e

            self.messages.append(
                {
                    "role": response.role,
                    "content": response.content,
                }
            )
            self.responses.append(response)

            response_text = response.content[0].text
            return response_text.strip('"') if strip_quotes else response_text

        return chat(self, message, strip_quotes=strip_quotes)

    def reset_conversation(self):
        """
        Resets the conversation to the initial system message.
        """
        self.messages = []
        self.responses = []
