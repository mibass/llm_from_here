"""Resolve OpenRouter credentials, models, and client defaults for chat + TTS."""

from __future__ import annotations

import os
from typing import Any, Literal

import openai

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

StructuredOutputMode = Literal["native", "tool"]


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_openrouter_free_mode() -> bool:
    return _truthy("LLMFH_OPENROUTER_FREE_MODE")


def is_lyria_enabled() -> bool:
    """OpenRouter Lyria background music. Off by default; set LLMFH_LYRIA_ENABLED=1 to enable."""
    return _truthy("LLMFH_LYRIA_ENABLED")


def require_openrouter_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "Missing OPENROUTER_API_KEY. Set it in the environment or .env in the repo root."
        )
    return key


def get_openrouter_chat_model() -> str:
    """Chat model slug.

    In **free mode**, chat always uses ``openrouter/free`` so a paid ``OPENROUTER_MODEL``
    from ``.env`` does not override (dotenv would otherwise undo shell ``unset``).
    Set ``LLMFH_OPENROUTER_FREE_CHAT_MODEL`` to pick another free-tier slug explicitly.
    """
    if is_openrouter_free_mode():
        return (
            os.getenv("LLMFH_OPENROUTER_FREE_CHAT_MODEL", "").strip() or "openrouter/free"
        )
    explicit = os.getenv("OPENROUTER_MODEL", "").strip()
    if explicit:
        return explicit
    # OpenRouter IDs change; ``deepseek/deepseek-chat`` is the stable chat slug (currently V3-class).
    return (
        os.getenv("OPENROUTER_MODEL_DEFAULT", "deepseek/deepseek-chat").strip()
        or "deepseek/deepseek-chat"
    )


def get_openrouter_tts_model() -> str:
    return (
        os.getenv("OPENROUTER_TTS_MODEL", "").strip()
        or "openai/gpt-4o-mini-tts-2025-12-15"
    )


def get_openrouter_tts_voice() -> str:
    return os.getenv("OPENROUTER_TTS_VOICE", "alloy").strip() or "alloy"


def get_openrouter_music_model() -> str:
    return (
        os.getenv("OPENROUTER_MUSIC_MODEL", "").strip()
        or "google/lyria-3-pro-preview"
    )


def get_structured_output_mode() -> StructuredOutputMode:
    """
    LLMFH_STRUCTURED_OUTPUT_MODE=native|tool.
    In free mode, default to tool when unset (native is unreliable on openrouter/free).
    DeepSeek via OpenRouter does not support pydantic-ai native structured output; default to tool.
    """
    raw = os.getenv("LLMFH_STRUCTURED_OUTPUT_MODE", "").strip().lower()
    if raw in ("native", "tool"):
        return raw  # type: ignore[return-value]
    if is_openrouter_free_mode():
        return "tool"
    if "deepseek" in get_openrouter_chat_model().lower():
        return "tool"
    return "native"


def structured_output_fallback_enabled() -> bool:
    """Optional native→tool retry on known API errors."""
    return _truthy("LLMFH_STRUCTURED_OUTPUT_FALLBACK")


def build_openrouter_client() -> openai.OpenAI:
    """OpenAI SDK client pointed at OpenRouter (chat + audio.speech)."""
    key = require_openrouter_api_key()
    headers: dict[str, str] = {}
    referer = os.getenv("OPENROUTER_HTTP_REFERER", "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    title = os.getenv("OPENROUTER_APP_NAME", "").strip()
    if title:
        headers["X-Title"] = title
    return openai.OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=key,
        default_headers=headers or None,  # type: ignore[arg-type]
    )


def log_free_mode_startup(logger: Any, resolved_chat_model: str) -> None:
    if is_openrouter_free_mode():
        logger.info(
            "LLMFH_OPENROUTER_FREE_MODE=on: chat_model=%s (paid OPENROUTER_MODEL from .env is ignored; "
            "override with LLMFH_OPENROUTER_FREE_CHAT_MODEL if needed)",
            resolved_chat_model,
        )
