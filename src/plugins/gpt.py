import openai
import os


class ChatApp:
    MODEL_NAME = "gpt-3.5-turbo"
    
    def __init__(self, system_message):
        # Setting the API key to use the OpenAI API
        openai.api_key = os.getenv("OPENAI_API_KEY")
        self.messages = [
            {"role": "system", "content": system_message},
        ]
        self.responses = []

    def chat(self, message, strip_quotes=False):
        messages = self.messages + [{"role": "user", "content": message}]
        response = openai.ChatCompletion.create(
            model=self.MODEL_NAME, 
            messages=messages
        )
        self.messages.append({"role": "assistant", "content": response["choices"][0]["message"]["content"]})
        self.responses.append(response)
        
        response_text = response["choices"][0]["message"]["content"]
        return response_text.strip('"') if strip_quotes else response_text

    def reset_conversation(self):
        self.messages = [
            {"role": "system", "content": """You are a big shot new york live show producer, writer, and performer. You are current the show runner for the Live From Here show and are calling all the shots. You are very emotional and nostalgic and like to listen to music, podcasts, npr, and long-form improv comedy."""},
        ]
        self.responses = []

    def save_conversation(self, file_path):
        with open(file_path, 'w') as f:
            for message in self.messages:
                f.write(f'{message["role"]}: {message["content"]}\n')