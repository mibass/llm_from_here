import openai
import os
import logging
from retry import retry
import jsonschema
import json
import re
import yaml
from collections import Counter

# Setup basic logging
logger = logging.getLogger(__name__)

import dotenv
dotenv.load_dotenv()

def extract_json_response(response):
    """
    Attempts to extract objects, and lists of objects from a response string.
    """
    # Regular expression pattern to find JSON objects and arrays within the string
    json_regex = r'(\[\s*\{.*\}\s*\]|\{\s*".*":\s*".*",\s*".*":\s*".*"\s*\})'
    json_match = re.search(json_regex, response, re.DOTALL)

    if json_match:
        json_data = json_match.group()
        return json_data

    return response


class ChatApp:
    MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")

    def __init__(self, system_message=""):
        """
        Initialize the chat app.
        Args:
            system_message (str): The system message to start the conversation.
        """
        # Setting the API key to use the OpenAI API
        self.messages = [
            {"role": "system", "content": system_message},
        ]
        self.system_message = system_message
        self.responses = []
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def __getstate__(self):
        state = self.__dict__.copy()
        # Remove the unpickleable entries.
        state.pop('client', None)
        return state

    def __setstate__(self, state):
        # Restore instance attributes.
        self.__dict__.update(state)
        # Recreate the client or set it to None, depending on your needs.
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def chat(self, message, strip_quotes=False, tries=5, delay=2, backoff=2):
        @retry(
            (
                openai.RateLimitError,
                openai.AuthenticationError,
                openai.APIError,
            ),
            tries=tries,
            delay=delay,
            backoff=backoff,
        )
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
                response = self.client.chat.completions.create(
                    model=self.MODEL_NAME, messages=messages
                )
            except Exception as e:
                logger.error(f"Error interacting with OpenAI API: {e}")
                raise e

            self.messages.append(
                {
                    "role": "assistant",
                    "content": response.choices[0].message.content,
                }
            )
            self.responses.append(response)

            response_text = response.choices[0].message.content
            return response_text.strip('"') if strip_quotes else response_text

        return chat(self, message, strip_quotes=strip_quotes)

    def delete_last_message(self):
        """
        Deletes the last message from the conversation, except for the initial system message.
        """
        if len(self.messages) > 1:
            self.messages.pop()
            self.responses.pop()

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
            with open(file_path, "w") as f:
                for message in self.messages:
                    f.write(f'{message["role"]}: {message["content"]}\n')
        except Exception as e:
            logging.error(f"Error saving conversation: {e}")
            raise

    def enforce_json_response(
        self, message, json_schema, log_prompt=False, tries=5, delay=2, backoff=2
    ):
        @retry(
            (jsonschema.exceptions.ValidationError),
            tries=tries,
            delay=delay,
            backoff=backoff,
        )
        def enforce_json_response_inner(self, message, json_schema):
            """
            Sends a message to the OpenAI API, injects the JSON schema into the message,
            enforces the response to obey the JSON schema, and retries if it fails.
            Args:
                message (str): The message to send.
                json_schema (dict): The JSON schema to enforce on the response.
            Returns:
                The assistant's response.
            """
            schema_message = json.dumps(json_schema)
            injected_message = f"{message}\n{schema_message}"

            if log_prompt:
                logger.info(f"Prompting chat app with: {injected_message}")

            response = self.chat(injected_message)
            extracted_response = extract_json_response(response)

            if log_prompt:
                logger.info(f"Chat app response: {response}")
                if response != extracted_response:
                    logger.warning(f"Extracted response: {extracted_response}")

            try:
                jsonschema.validate(
                    instance=json.loads(extracted_response), schema=json_schema
                )
            except jsonschema.exceptions.ValidationError as e:
                self.delete_last_message()
                logger.warning(
                    f"Response does not obey the provided JSON schema. Retrying..."
                )
                raise e

            return json.loads(extracted_response)

        return enforce_json_response_inner(self, message, json_schema)

    def enforce_list_response(
        self,
        message,
        num_entries=100,
        list_format="output the list formatted as a yaml list wrapped in 3 single quotes and make it have {} entries",
        log_prompt=False,
        tries=5,
        delay=2,
        backoff=2,
    ):
        @retry((Exception), tries=tries, delay=delay, backoff=backoff)
        def enforce_list_response_inner(self, message, num_entries, list_format):
            """
            Sends a message to the OpenAI API, adds the list_format string to the prompt,
            parses the output to find the list, and retries if it fails.
            Args:
                message (str): The message to send.
                num_entries (int): The number of entries to request in the list.
                list_format (str): The string to add to the message to ask for a list.
            Returns:
                The assistant's response as a list.
            """
            list_format = list_format.format(num_entries)
            injected_message = f"{message}\n{list_format}"

            if log_prompt:
                logger.info(f"Prompting chat app with: {injected_message}")

            response = self.chat(injected_message)
            if log_prompt:
                logger.info(f"Chat app response: {response}")
            try:
                # Extract the response between triple single quotes, or backticks
                match = re.search(r"'''(.*?)'''", response, re.DOTALL) or re.search(r"```(.*?)```", response, re.DOTALL)
                if match:
                    extracted_response = match.group(1).strip()

                    # Try parsing as YAML
                    try:
                        response_as_list = yaml.safe_load(extracted_response)
                    except yaml.YAMLError:
                        # If that fails, try parsing as a bullet list
                        response_as_list = [
                            line.strip()[1:].strip()
                            for line in extracted_response.split("\n")
                            if line.strip().startswith("-")
                        ]

                    if isinstance(response_as_list, list):
                        return response_as_list
                    else:
                        raise ValueError(
                            "Extracted response could not be parsed as a list."
                        )
                else:
                    raise ValueError(
                        "No response was found between triple single quotes."
                    )
            except Exception as e:
                if log_prompt:
                    logger.info(f"Chat app response: {response}")
                    logger.warning(f"Failed to parse response as a list. Retrying...")

                self.delete_last_message()
                raise e

        return enforce_list_response_inner(self, message, num_entries, list_format)

    def enforce_list_response_consensus(
        self,
        message,
        num_entries=100,
        num_consensus=2,
        list_format="output only the list formatted as a yaml list wrapped in 3 single quotes (''') and make it have {} entries; do not number the list, only output it in YAML format",
        log_prompt=False,
        tries=5,
        delay=2,
        backoff=2,
        reset_conversation=True,
    ):
        """
        Repeatedly calls enforce_list_response, stores the results,
        and adds results to a consensus list until they reach num_consensus results
        that have been seen at least twice. Then, sorts the consensus responses by their counts
        in descending order and returns the top num_entries responses.
        Args:
            message (str): The message to send.
            num_entries (int): The number of entries to request in the list.
            num_consensus (int): The number of unique responses to reach a consensus.
            list_format (str): The string to add to the message to ask for a list.
        Returns:
            The consensus list of responses.
        """
        all_responses = []

        while True:
            if reset_conversation:
                self.reset_conversation()

            response = self.enforce_list_response(
                message, num_entries, list_format, log_prompt, tries, delay, backoff
            )
            all_responses.extend(response)

            response_counts = Counter(all_responses)
            consensus_responses = [
                item for item, count in response_counts.items() if count >= num_consensus
            ]

            if len(consensus_responses) >= num_entries:
                break

        if reset_conversation:
            self.reset_conversation()

        # Sort responses by count in descending order and take the top num_entries responses
        sorted_responses = sorted(
            consensus_responses, key=lambda x: -response_counts[x]
        )
        return sorted_responses[:num_entries]


if __name__ == "__main__":
    import sys

    # get command line args
    message = sys.argv[1]

    chat_app = ChatApp()

    # Call the chat method
    response = chat_app.chat(message)

    print(response)
