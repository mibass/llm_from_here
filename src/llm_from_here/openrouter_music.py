"""OpenRouter Lyria music generation (intro/story background cues)."""

from __future__ import annotations

import base64
import logging
import os
import re
import tempfile
import time
from typing import Any

from llm_from_here.llm_env import build_openrouter_client, get_openrouter_music_model
from llm_from_here.plugins.showTTS import _segment_from_openrouter_speech_file

logger = logging.getLogger(__name__)

_MUSIC_PREFIX_RE = re.compile(r"^\[MUSIC\s*", re.IGNORECASE)
_BACKGROUND_PREFIX_RE = re.compile(r"^\[background:\s*", re.IGNORECASE)
_BACKGROUND_MUSIC_PREFIX_RE = re.compile(r"^\[BACKGROUND MUSIC:\s*", re.IGNORECASE)

MUSIC_CUE_MAX_LEN = 500
YOUTUBE_FALLBACK_QUERY_MAX_LEN = 80
LYRIA_EMPTY_STREAM_MSG = "OpenRouter Lyria stream returned no audio data"
LYRIA_CONTENT_FILTER_MSG = "OpenRouter Lyria stream returned codebook tokens (content filter suspected)"
_LYRIA_CODEBOOK_RE = re.compile(r"\[\[[A-Z]\d+\]\]")
_LYRIA_DEFAULT_RETRY_DELAYS_SEC = (2.0, 8.0, 20.0)
_LYRIA_SIMPLIFIED_FALLBACK_PROMPT = (
    "Create a 180-second instrumental track at 90 BPM. "
    "Live acoustic folk instrumental. Acoustic guitar, light mandolin, upright bass. "
    "Instrumental only, no vocals."
)


class LyriaEmptyStreamError(ValueError):
    """HTTP 200 stream finished without any ``delta.audio.data`` chunks."""


class LyriaContentFilterError(LyriaEmptyStreamError):
    """Empty stream with Lyria codebook tokens suggesting input filtering."""


def _lyria_max_attempts() -> int:
    raw = os.getenv("LLMFH_LYRIA_MAX_ATTEMPTS", "3").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(1, n)


def _lyria_retry_delay_sec() -> float:
    """Legacy single delay env var; prefer ``LLMFH_LYRIA_RETRY_DELAYS_SEC``."""
    raw = os.getenv("LLMFH_LYRIA_RETRY_DELAY_SEC", "2").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 2.0


def _lyria_retry_delays_sec() -> tuple[float, ...]:
    """
    Exponential backoff delays between Lyria retries.

    Default: 2s, 8s, 20s. Override with ``LLMFH_LYRIA_RETRY_DELAYS_SEC=2,8,20``.
    """
    raw = os.getenv("LLMFH_LYRIA_RETRY_DELAYS_SEC", "").strip()
    if raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        delays: list[float] = []
        for part in parts:
            try:
                delays.append(max(0.0, float(part)))
            except ValueError:
                continue
        if delays:
            return tuple(delays)
    return _LYRIA_DEFAULT_RETRY_DELAYS_SEC


def _lyria_retry_delay_for_attempt(attempt: int) -> float:
    """Delay before retry attempt ``attempt`` (1-based, after first failure)."""
    delays = _lyria_retry_delays_sec()
    return delays[min(max(attempt - 1, 0), len(delays) - 1)]


def _looks_like_codebook_tokens(texts: list[str]) -> bool:
    return any(_LYRIA_CODEBOOK_RE.search(text) for text in texts)


def simplified_music_prompt(_original: str) -> str:
    """Safe generic fallback when Lyria rejects a specific music cue."""
    return _LYRIA_SIMPLIFIED_FALLBACK_PROMPT


def normalize_music_prompt(text: str) -> str:
    """Strip music cue wrappers and ensure instrumental-only guard."""
    prompt = text.strip()
    prompt = _MUSIC_PREFIX_RE.sub("", prompt)
    prompt = _BACKGROUND_PREFIX_RE.sub("", prompt)
    prompt = _BACKGROUND_MUSIC_PREFIX_RE.sub("", prompt)
    prompt = prompt.rstrip("]").strip()
    if "no vocal" not in prompt.lower():
        prompt += " Instrumental only, no vocals."
    return prompt


def youtube_fallback_query(text: str, max_len: int = YOUTUBE_FALLBACK_QUERY_MAX_LEN) -> str:
    """Short search query for YouTube fallback from a long music cue."""
    prompt = normalize_music_prompt(text)
    first_sentence = re.split(r"[.!?]\s", prompt, maxsplit=1)[0].strip()
    query = first_sentence or prompt
    if len(query) > max_len:
        query = query[:max_len].rsplit(" ", 1)[0].strip() or query[:max_len]
    return query


def _audio_data_from_stream_chunk(chunk: Any) -> str | None:
    choice = (chunk.choices or [None])[0]
    if choice is None:
        return None
    delta = choice.delta
    if delta is None:
        return None
    audio = getattr(delta, "audio", None)
    if audio is None:
        return None
    if isinstance(audio, dict):
        data = audio.get("data")
    else:
        data = getattr(audio, "data", None)
    return data if data else None


def _summarize_stream_chunk(chunk: Any) -> str:
    """Short label for Lyria stream diagnostics when no audio arrives."""
    choice = (chunk.choices or [None])[0]
    if choice is None:
        return "no_choices"
    parts: list[str] = []
    fr = getattr(choice, "finish_reason", None)
    if fr:
        parts.append(f"finish_reason={fr!r}")
    delta = getattr(choice, "delta", None)
    if delta is None:
        parts.append("delta=None")
        return ",".join(parts) or "empty_choice"
    content = getattr(delta, "content", None)
    if content:
        text = str(content).replace("\n", " ")[:80]
        parts.append(f"text={text!r}")
    audio = getattr(delta, "audio", None)
    if audio is None:
        parts.append("audio=None")
    elif isinstance(audio, dict):
        if audio.get("data"):
            parts.append("audio=data")
        else:
            parts.append(f"audio_keys={sorted(audio.keys())}")
    else:
        has_data = bool(getattr(audio, "data", None))
        parts.append("audio=data" if has_data else "audio=empty")
    return ",".join(parts) or "empty_delta"


def _collect_streamed_mp3(client: Any, model: str, prompt: str) -> bytes:
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        # Lyria on OpenRouter emits structure tokens in delta.content when text is
        # requested; audio only reliably arrives as delta.audio.data with audio-only.
        extra_body={"modalities": ["audio"], "audio": {"format": "mp3"}},
    )
    audio_chunks: list[str] = []
    chunk_count = 0
    audio_data_chunks = 0
    text_chunks = 0
    text_contents: list[str] = []
    sample_summaries: list[str] = []
    for chunk in stream:
        chunk_count += 1
        data = _audio_data_from_stream_chunk(chunk)
        if data:
            audio_chunks.append(data)
            audio_data_chunks += 1
        delta = ((chunk.choices or [None])[0] or None)
        delta_obj = getattr(delta, "delta", None) if delta is not None else None
        content = getattr(delta_obj, "content", None) if delta_obj is not None else None
        if content:
            text_chunks += 1
            text_contents.append(str(content))
        if len(sample_summaries) < 8:
            sample_summaries.append(_summarize_stream_chunk(chunk))
    if not audio_chunks:
        prompt_preview = prompt[:300]
        logger.debug("Lyria empty stream full prompt: %r", prompt)
        if _looks_like_codebook_tokens(text_contents):
            logger.warning(
                "Lyria content filter suspected: model=%s chunks=%d audio_data_chunks=%d "
                "text_chunks=%d sample=%s prompt=%r",
                model,
                chunk_count,
                audio_data_chunks,
                text_chunks,
                sample_summaries,
                prompt_preview,
            )
            raise LyriaContentFilterError(LYRIA_CONTENT_FILTER_MSG)
        logger.warning(
            "Lyria stream ended with no audio: model=%s chunks=%d audio_data_chunks=%d "
            "text_chunks=%d sample=%s prompt=%r",
            model,
            chunk_count,
            audio_data_chunks,
            text_chunks,
            sample_summaries,
            prompt_preview,
        )
        raise LyriaEmptyStreamError(LYRIA_EMPTY_STREAM_MSG)
    return base64.b64decode("".join(audio_chunks))


def _collect_streamed_mp3_with_retry(
    client: Any,
    model: str,
    prompt: str,
    *,
    max_attempts: int | None = None,
    retry_delay_sec: float | None = None,
) -> bytes:
    attempts = max_attempts if max_attempts is not None else _lyria_max_attempts()
    last_error: LyriaEmptyStreamError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _collect_streamed_mp3(client, model, prompt)
        except LyriaContentFilterError as exc:
            last_error = exc
            break
        except LyriaEmptyStreamError as exc:
            last_error = exc
            if attempt >= attempts:
                break
            delay = (
                retry_delay_sec
                if retry_delay_sec is not None
                else _lyria_retry_delay_for_attempt(attempt)
            )
            logger.warning(
                "Lyria empty stream on attempt %d/%d; retrying in %.1fs",
                attempt,
                attempts,
                delay,
            )
            if delay > 0:
                time.sleep(delay)

    if isinstance(last_error, LyriaContentFilterError):
        fallback_prompt = simplified_music_prompt(prompt)
        logger.warning(
            "Lyria content filter suspected; retrying once with simplified prompt: %r",
            fallback_prompt[:300],
        )
        try:
            return _collect_streamed_mp3(client, model, fallback_prompt)
        except LyriaEmptyStreamError as exc:
            last_error = exc

    assert last_error is not None
    raise last_error


def generate_instrumental(
    cue_text: str,
    output_wav: str,
    *,
    model: str | None = None,
    client: Any | None = None,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    """Generate instrumental WAV from a music cue via OpenRouter Lyria."""
    prompt = normalize_music_prompt(cue_text)
    use_model = model or get_openrouter_music_model()
    if "lyria-3-clip" in use_model.lower():
        logger.warning(
            "OPENROUTER_MUSIC_MODEL=%s is Lyria Clip (30s max). "
            "Use google/lyria-3-pro-preview for 180-second cues.",
            use_model,
        )
    use_client = client or build_openrouter_client()
    attempts = max_attempts if max_attempts is not None else _lyria_max_attempts()

    started = time.monotonic()
    mp3_bytes = _collect_streamed_mp3_with_retry(
        use_client, use_model, prompt, max_attempts=attempts
    )

    fd, tmp_mp3 = tempfile.mkstemp(suffix=".mp3", prefix="llmfh_lyria_")
    os.close(fd)
    try:
        with open(tmp_mp3, "wb") as f:
            f.write(mp3_bytes)
        audio = _segment_from_openrouter_speech_file(tmp_mp3)
        audio.export(output_wav, format="wav")
    finally:
        try:
            os.remove(tmp_mp3)
        except OSError:
            pass

    elapsed = time.monotonic() - started
    logger.debug("Lyria generated full prompt: %r", prompt)
    logger.info(
        "Lyria generated %s (model=%s, mp3_bytes=%d, elapsed=%.1fs, attempts<=%d, prompt=%r)",
        output_wav,
        use_model,
        len(mp3_bytes),
        elapsed,
        attempts,
        prompt[:300],
    )
    return {
        "source": "openrouter_lyria",
        "model": use_model,
        "prompt": prompt,
        "mp3_bytes": len(mp3_bytes),
        "elapsed_sec": elapsed,
        "max_attempts": attempts,
    }
