import os
import dotenv
import logging

# Assuming these modules are adapted to have a common interface
import llm_from_here.plugins.gpt as gpt
import llm_from_here.plugins.claude as claude

# Setup basic logging
logger = logging.getLogger(__name__)

dotenv.load_dotenv()

def get_llm_provider(system_message=""):
    provider = os.getenv('LLM_PROVIDER', 'gpt').lower()
    if provider == 'claude':
        logger.info("Using Claude as LLM provider")
        return claude.ClaudeChatApp(system_message=system_message)
    elif provider == 'gpt':
        logger.info("Using GPT as LLM provider")
        return gpt.ChatApp(system_message=system_message)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")
