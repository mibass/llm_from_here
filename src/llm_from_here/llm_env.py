"""Resolve OpenRouter credentials, models, and client defaults for chat + TTS."""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.request
from typing import Any, Literal

import openai

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

StructuredOutputMode = Literal["native", "tool"]

_logger = logging.getLogger(__name__)

# Populated by ShowRunner from YAML ``model_routing`` (see ``set_model_routing``).
_routing: dict[str, str] = {}


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
        or "google/gemini-3.1-flash-tts-preview"
    )


def get_openrouter_tts_voice() -> str:
    # Sadachbia: male, lively (Gemini prebuilt voice). Override via OPENROUTER_TTS_VOICE.
    return os.getenv("OPENROUTER_TTS_VOICE", "Sadachbia").strip() or "Sadachbia"


def get_openrouter_tts_response_format(model: str | None = None) -> str:
    """Gemini TTS on OpenRouter requires pcm; most other speech models use mp3."""
    slug = (model or get_openrouter_tts_model()).lower()
    if "gemini" in slug and "tts" in slug:
        return "pcm"
    return "pcm" if os.getenv("OPENROUTER_TTS_RESPONSE_FORMAT", "").strip().lower() == "pcm" else "mp3"


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


def set_model_routing(config: dict[str, Any] | None) -> None:
    """Merge YAML ``global_params.model_routing`` into process-wide defaults."""
    global _routing
    _routing = dict(config) if isinstance(config, dict) else {}


def _routing_or_env(key_yaml: str, key_env: str, default: str) -> str:
    v = (_routing.get(key_yaml) or "").strip()
    if v:
        return v
    return os.getenv(key_env, "").strip() or default


def get_filter_model() -> str:
    """Small yes/no / classification tasks (OpenRouter by default; override with ``ollama:...`` + ``OLLAMA_BASE_URL``)."""
    return _routing_or_env(
        "filter_model",
        "LLMFH_FILTER_MODEL",
        "openrouter:openai/gpt-4o-mini",
    )


def get_structured_model() -> str:
    """Tool-calling agents and structured multi-step reasoning (OpenRouter slug)."""
    return _routing_or_env(
        "structured_model",
        "LLMFH_STRUCTURED_MODEL",
        "openrouter:openai/gpt-4o-mini",
    )


def get_prose_model() -> str:
    """Long-form script / high-quality prose (OpenRouter slug)."""
    return _routing_or_env(
        "prose_model",
        "LLMFH_PROSE_MODEL",
        "openrouter:openai/gpt-4o",
    )


def get_web_search_engine() -> str:
    """OpenRouter web search engine: auto, native, exa, firecrawl, or parallel."""
    return os.getenv("LLMFH_WEB_SEARCH_ENGINE", "").strip() or "exa"


def get_web_search_max_results() -> int:
    raw = os.getenv("LLMFH_WEB_SEARCH_MAX_RESULTS", "").strip()
    if raw:
        return max(1, min(25, int(raw)))
    return 5


def get_web_search_max_total_results() -> int | None:
    raw = os.getenv("LLMFH_WEB_SEARCH_MAX_TOTAL_RESULTS", "").strip()
    if not raw:
        return 10
    return max(1, int(raw))


def check_ollama_available(host: str = "127.0.0.1", port: int = 11434) -> bool:
    """Lightweight ping of Ollama; logs warning and returns False on failure."""
    url = f"http://{host}:{port}/api/tags"
    try:
        urllib.request.urlopen(url, timeout=2)  # noqa: S310 — intentional localhost check
        return True
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        _logger.warning("Ollama not reachable at %s (%s)", url, e)
        return False


def warn_if_ollama_models_unavailable() -> None:
    """Call once after routing is set if filter or structured slug uses ollama."""
    for slug in (get_filter_model(), get_structured_model()):
        low = slug.lower()
        if low.startswith("ollama:") or low.startswith("ollama/"):
            check_ollama_available()
            break
