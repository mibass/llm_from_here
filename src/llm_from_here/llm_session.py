"""OpenRouter-backed LLM session using pydantic-ai (replaces legacy ChatApp / plugins.gpt)."""

from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from typing import Any, cast

import httpx
import yaml
from pydantic import BaseModel
from pydantic_ai import Agent, AgentRetries
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.output import NativeOutput
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openrouter import OpenRouterProvider
from retry import retry
import openai

from llm_from_here.llm_env import (
    get_openrouter_chat_model,
    get_structured_output_mode,
    is_openrouter_free_mode,
    log_free_mode_startup,
    structured_output_fallback_enabled,
)
from llm_from_here.llm_env import StructuredOutputMode

logger = logging.getLogger(__name__)

import dotenv

dotenv.load_dotenv()

# A stalled OpenRouter SSE stream ("200 OK" headers, then the body never finishes)
# previously hung `run_sync` for tens of minutes. We inject a bounded-timeout httpx
# client into every OpenRouterModel so that hang raises a retriable error instead.
_OPENROUTER_HTTP_CLIENT: httpx.AsyncClient | None = None


def openrouter_read_timeout_s() -> float:
    """Read timeout in seconds for OpenRouter responses (default 120, env-tunable)."""
    raw = os.getenv("LLMFH_OPENROUTER_HTTP_TIMEOUT_S", "").strip()
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 120.0
    return timeout if timeout > 0 else 120.0


def _openrouter_provider() -> OpenRouterProvider:
    """OpenRouterProvider backed by a lazily-created bounded-timeout httpx client."""
    global _OPENROUTER_HTTP_CLIENT
    if _OPENROUTER_HTTP_CLIENT is None:
        _OPENROUTER_HTTP_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=openrouter_read_timeout_s(),
                write=30.0,
                pool=10.0,
            )
        )
    return OpenRouterProvider(http_client=_OPENROUTER_HTTP_CLIENT)


# Transient provider/network errors worth one bounded retry at the structured-call
# level. `UnexpectedModelBehavior` covers "Exceeded maximum output retries (5)":
# a fresh LLM attempt (as opposed to re-validating the same output) recovers it.
_TRANSIENT_LLM_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
    ModelHTTPError,
    ModelAPIError,
    UnexpectedModelBehavior,
)


def _is_transient_llm_error(exc: BaseException) -> bool:
    return isinstance(exc, _TRANSIENT_LLM_ERRORS)


class LlmSession:
    """Multi-turn chat + structured outputs via OpenRouter and pydantic-ai."""

    def __init__(self, system_message: str = "", model_slug: str | None = None):
        self.system_message = system_message
        self.model_slug = model_slug
        self.chat_model_slug = (
            model_slug.split(":", 1)[1].strip()
            if model_slug and model_slug.startswith("openrouter:")
            else (model_slug if model_slug else get_openrouter_chat_model())
        )
        resolved = self._resolve_agent_backend(model_slug)
        uses_openrouter = model_slug is None or (
            isinstance(model_slug, str) and model_slug.startswith("openrouter:")
        )
        if uses_openrouter:
            log_free_mode_startup(logger, self.chat_model_slug)
        self._history_serial: list[dict[str, Any]] = []
        self.responses: list[Any] = []
        self._agent = Agent(
            resolved,
            system_prompt=(system_message,) if system_message else (),
            output_type=str,
            retries=AgentRetries(tools=3, output=5),
        )

    @staticmethod
    def _resolve_agent_backend(model_slug: str | None) -> Any:
        """OpenRouter via ``OpenRouterModel``; native providers via plain model string."""
        if model_slug is None:
            slug = get_openrouter_chat_model()
            if is_openrouter_free_mode():
                return OpenRouterModel(
                    slug,
                    provider=_openrouter_provider(),
                    profile=OpenAIModelProfile(openai_supports_tool_choice_required=False),
                )
            return OpenRouterModel(slug, provider=_openrouter_provider())
        if model_slug.startswith("openrouter:"):
            inner = model_slug.split(":", 1)[1].strip() or get_openrouter_chat_model()
            if is_openrouter_free_mode():
                return OpenRouterModel(
                    inner,
                    provider=_openrouter_provider(),
                    profile=OpenAIModelProfile(openai_supports_tool_choice_required=False),
                )
            return OpenRouterModel(inner, provider=_openrouter_provider())
        return model_slug

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state.pop("_agent", None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        slug = getattr(self, "model_slug", None)
        if slug is None:
            self.chat_model_slug = get_openrouter_chat_model()
        elif slug.startswith("openrouter:"):
            self.chat_model_slug = slug.split(":", 1)[1].strip() or get_openrouter_chat_model()
        else:
            self.chat_model_slug = slug
        resolved = self._resolve_agent_backend(slug)
        self._agent = Agent(
            resolved,
            system_prompt=(self.system_message,) if self.system_message else (),
            output_type=str,
            retries=AgentRetries(tools=3, output=5),
        )

    def _message_history(self) -> list[Any] | None:
        if not self._history_serial:
            return None
        return ModelMessagesTypeAdapter.validate_python(self._history_serial)

    def _append_new_messages(self, result: Any) -> None:
        new = result.new_messages()
        dumped = ModelMessagesTypeAdapter.dump_python(new, mode="json")
        if isinstance(dumped, list):
            self._history_serial.extend(cast(list[dict[str, Any]], dumped))
        else:
            self._history_serial.append(cast(dict[str, Any], dumped))

    def delete_last_message(self) -> None:
        """Remove the last assistant turn (and its user request) from stored history."""
        if self._history_serial and self._history_serial[-1].get("kind") == "response":
            self._history_serial.pop()
        if self._history_serial and self._history_serial[-1].get("kind") == "request":
            self._history_serial.pop()
        if self.responses:
            self.responses.pop()

    def reset_conversation(self) -> None:
        self._history_serial = []
        self.responses = []

    def save_conversation(self, file_path: str) -> None:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                for msg in self._history_serial:
                    f.write(f"{msg.get('kind', '?')}: {msg!r}\n")
        except OSError as e:
            logger.error("Error saving conversation: %s", e)
            raise

    def chat(self, message: str, strip_quotes: bool = False, tries: int = 5, delay: int = 2, backoff: int = 2):
        @retry(
            (openai.RateLimitError, openai.AuthenticationError, openai.APIError, openai.APIConnectionError),
            tries=tries,
            delay=delay,
            backoff=backoff,
        )
        def _inner() -> str:
            result = self._agent.run_sync(
                message,
                output_type=str,
                message_history=self._message_history(),
            )
            self._append_new_messages(result)
            text = result.output
            if text is None or not str(text).strip():
                raise ValueError("Empty model response content")
            text = str(text)
            self.responses.append({"output": text})
            return text.strip('"') if strip_quotes else text

        return _inner()

    def _output_spec(self, model_type: type[BaseModel], mode: StructuredOutputMode):
        if mode == "native":
            return NativeOutput(model_type)
        return model_type

    def _dump_structured(self, out: Any) -> Any:
        if isinstance(out, BaseModel):
            return out.model_dump()
        return out

    def _should_retry_structured_mode(self, exc: Exception, *, explicit_mode: bool) -> bool:
        if explicit_mode:
            return False
        if structured_output_fallback_enabled() or is_openrouter_free_mode():
            return True
        msg = str(exc).lower()
        return "tool choice must be auto" in msg

    def _run_structured_mode(
        self,
        prompt: str,
        output_type: type[BaseModel],
        mode: StructuredOutputMode,
        *,
        explicit_mode: bool,
    ) -> Any:
        def _run(mode_try: StructuredOutputMode) -> Any:
            spec = self._output_spec(output_type, mode_try)
            result = self._agent.run_sync(
                prompt,
                output_type=spec,
                message_history=self._message_history(),
            )
            self._append_new_messages(result)
            return self._dump_structured(result.output)

        try:
            return _run(mode)
        except Exception as e:
            if self._should_retry_structured_mode(e, explicit_mode=explicit_mode):
                alt: StructuredOutputMode = "tool" if mode == "native" else "native"
                logger.warning(
                    "Structured %s output failed (%s); retrying with %s mode",
                    mode,
                    e,
                    alt,
                )
                if self._history_serial:
                    self.delete_last_message()
                return _run(alt)
            raise

    def run_structured(
        self,
        prompt: str,
        output_type: type[BaseModel],
        *,
        log_prompt: bool = False,
        structured_mode: StructuredOutputMode | None = None,
    ) -> Any:
        mode = structured_mode or get_structured_output_mode(self.model_slug)
        if log_prompt:
            logger.info("run_structured mode=%s prompt=%s", mode, prompt)

        transient_attempts = 2
        for attempt in range(transient_attempts):
            try:
                return self._run_structured_mode(
                    prompt,
                    output_type,
                    mode,
                    explicit_mode=structured_mode is not None,
                )
            except Exception as e:
                if attempt < transient_attempts - 1 and _is_transient_llm_error(e):
                    delay = 1.0 + attempt * 1.5
                    logger.warning(
                        "Transient LLM error on structured call (%s); "
                        "retrying %d/%d in %.1fs",
                        e,
                        attempt + 2,
                        transient_attempts,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise

    def enforce_list_response(
        self,
        message: str,
        num_entries: int = 100,
        list_format: str = "output the list formatted as a yaml list wrapped in 3 single quotes and make it have {} entries",
        log_prompt: bool = False,
        tries: int = 5,
        delay: int = 2,
        backoff: int = 2,
    ):
        @retry((Exception,), tries=tries, delay=delay, backoff=backoff)
        def _inner() -> list[Any]:
            list_format_f = list_format.format(num_entries)
            injected = f"{message}\n{list_format_f}"
            if log_prompt:
                logger.info("enforce_list_response prompt: %s", injected)
            response = self.chat(injected)
            if log_prompt:
                logger.info("enforce_list_response response: %s", response)
            try:
                match = re.search(r"'''(.*?)'''", response, re.DOTALL) or re.search(
                    r"```(.*?)```", response, re.DOTALL
                )
                if not match:
                    raise ValueError("No response was found between triple single quotes.")
                extracted = match.group(1).strip()
                # Markdown fences often include a language tag line (``yaml``) that breaks YAML parsing.
                low = extracted.lower()
                if low.startswith("yaml"):
                    extracted = extracted[4:].lstrip("\n").strip()
                elif low.startswith("yml"):
                    extracted = extracted[3:].lstrip("\n").strip()
                try:
                    as_list = yaml.safe_load(extracted)
                except yaml.YAMLError:
                    as_list = [
                        line.strip()[1:].strip()
                        for line in extracted.split("\n")
                        if line.strip().startswith("-")
                    ]
                if not isinstance(as_list, list):
                    raise ValueError("Extracted response could not be parsed as a list.")
                return as_list
            except Exception:
                self.delete_last_message()
                raise

        return _inner()

    def enforce_list_response_consensus(
        self,
        message: str,
        num_entries: int = 100,
        num_consensus: int = 2,
        list_format: str = (
            "output only the list formatted as a yaml list wrapped in 3 single quotes (''') "
            "and make it have {} entries; do not number the list, only output it in YAML format"
        ),
        log_prompt: bool = False,
        tries: int = 5,
        delay: int = 2,
        backoff: int = 2,
        reset_conversation: bool = True,
    ) -> list[Any]:
        all_responses: list[Any] = []
        while True:
            if reset_conversation:
                self.reset_conversation()
            response = self.enforce_list_response(
                message, num_entries, list_format, log_prompt, tries, delay, backoff
            )
            all_responses.extend(response)
            counts = Counter(all_responses)
            consensus = [item for item, c in counts.items() if c >= num_consensus]
            if len(consensus) >= num_entries:
                break
        if reset_conversation:
            self.reset_conversation()
        sorted_responses = sorted(consensus, key=lambda x: -counts[x])
        return sorted_responses[:num_entries]