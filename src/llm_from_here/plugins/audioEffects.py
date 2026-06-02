"""Audio effects for narrator segments (pedalboard-backed reverb)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from pedalboard import Convolution, LowpassFilter, Pedalboard, Reverb
from pydub import AudioSegment

from llm_from_here.common import get_resources_path

logger = logging.getLogger(__name__)

DEFAULT_IMPULSE_RESPONSE = "auditorium_ir.wav"
_DEFAULT_WET_DB = -10.0
_DEFAULT_HIGH_CUT_HZ = 8000.0
_TAIL_PAD_SEC = 1.8


def default_narrator_reverb_config() -> dict[str, Any]:
    """YAML-friendly defaults for subtle auditorium speech reverb."""
    return {
        "enabled": True,
        "mode": "reverb",
        "room_size": 0.48,
        "damping": 0.35,
        "wet_level": 0.38,
        "dry_level": 0.88,
        "width": 1.0,
        "impulse_response": DEFAULT_IMPULSE_RESPONSE,
        "wet_db": _DEFAULT_WET_DB,
        "high_cut_hz": _DEFAULT_HIGH_CUT_HZ,
    }


def resolve_impulse_response_path(config: dict[str, Any]) -> Path:
    """Resolve IR path relative to package resources unless absolute."""
    ir_name = config.get("impulse_response", DEFAULT_IMPULSE_RESPONSE)
    ir_path = Path(str(ir_name))
    if ir_path.is_absolute():
        return ir_path
    return Path(get_resources_path()) / ir_path.name


def ensure_default_impulse_response(path: Path | str | None = None) -> Path:
    """Create a synthetic small-hall IR if the bundled file is missing."""
    target = (
        Path(path)
        if path is not None
        else Path(get_resources_path()) / DEFAULT_IMPULSE_RESPONSE
    )
    if target.is_file():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    rt60_sec = 1.6
    length = int(sample_rate * rt60_sec)
    rng = np.random.default_rng(42)
    t = np.arange(length, dtype=np.float64) / sample_rate
    decay = np.exp(-6.9 * t / rt60_sec)
    ir = rng.standard_normal(length).astype(np.float64) * decay
    # Early reflections (sparse auditorium-ish taps)
    for delay_ms, gain in ((23, 0.35), (41, 0.22), (67, 0.14), (97, 0.09)):
        idx = int(sample_rate * delay_ms / 1000.0)
        if idx < length:
            ir[idx] += gain
    # No direct impulse — dry speech is mixed separately so the tail stays audible.
    ir[0] = 0.0
    peak = np.max(np.abs(ir))
    if peak > 0:
        ir = ir / peak

    from scipy.io import wavfile

    wavfile.write(str(target), sample_rate, ir.astype(np.float32))
    logger.info("Wrote synthetic auditorium impulse response to %s", target)
    return target


def _segment_to_float32_array(segment: AudioSegment) -> tuple[np.ndarray, int]:
    """Return float32 samples shaped (channels, samples) and frame rate."""
    if segment.channels == 1:
        samples = np.array(segment.get_array_of_samples(), dtype=np.float32)
        samples /= float(1 << (8 * segment.sample_width - 1))
        return samples[np.newaxis, :], segment.frame_rate

    stereo = segment.set_channels(2)
    interleaved = np.array(stereo.get_array_of_samples(), dtype=np.float32)
    scale = float(1 << (8 * stereo.sample_width - 1))
    interleaved /= scale
    frames = interleaved.reshape((-1, 2)).T
    return frames, stereo.frame_rate


def _float32_array_to_segment(
    array: np.ndarray,
    frame_rate: int,
    channels: int,
    sample_width: int,
) -> AudioSegment:
    """Convert pedalboard output back to pydub AudioSegment."""
    array = np.asarray(array, dtype=np.float32)
    if array.ndim == 1:
        array = array[np.newaxis, :]

    if channels == 1:
        mono = array[0] if array.shape[0] > 1 else array.mean(axis=0)
        mono = np.clip(mono, -1.0, 1.0)
        pcm = (mono * float(1 << (8 * sample_width - 1))).astype(np.int16)
        return AudioSegment(
            pcm.tobytes(),
            frame_rate=frame_rate,
            sample_width=sample_width,
            channels=1,
        )

    if array.shape[0] == 1:
        array = np.vstack([array[0], array[0]])
    elif array.shape[0] > 2:
        array = array[:2]

    array = np.clip(array, -1.0, 1.0)
    interleaved = array.T.reshape(-1)
    pcm = (interleaved * float(1 << (8 * sample_width - 1))).astype(np.int16)
    return AudioSegment(
        pcm.tobytes(),
        frame_rate=frame_rate,
        sample_width=sample_width,
        channels=2,
    )


def _wet_gain_linear(wet_db: float) -> float:
    return float(10 ** (wet_db / 20.0))


def _apply_convolution_reverb(
    dry: np.ndarray,
    sample_rate: int,
    config: dict[str, Any],
) -> np.ndarray:
    ir_path = resolve_impulse_response_path(config)
    if not ir_path.is_file():
        ir_path = ensure_default_impulse_response(ir_path)

    wet_db = float(config.get("wet_db", _DEFAULT_WET_DB))
    wet_gain = _wet_gain_linear(wet_db)
    convolution_gain = float(config.get("convolution_gain", 1.0))
    tail_pad_sec = float(config.get("tail_pad_sec", _TAIL_PAD_SEC))
    tail_pad = int(sample_rate * tail_pad_sec)

    if dry.ndim == 1:
        dry = dry[np.newaxis, :]
    dry_len = dry.shape[-1]
    dry_padded = np.pad(dry, ((0, 0), (0, tail_pad)))

    board: list[Any] = [Convolution(str(ir_path), convolution_gain)]
    high_cut = config.get("high_cut_hz")
    if high_cut is not None:
        board.append(LowpassFilter(cutoff_frequency_hz=float(high_cut)))

    wet = np.asarray(Pedalboard(board)(dry_padded, sample_rate), dtype=np.float32)
    if wet.ndim == 1:
        wet = wet[np.newaxis, :]

    out_len = min(wet.shape[-1], dry_len + tail_pad)
    dry_part = dry_padded[..., :out_len]
    wet_part = wet[..., :out_len]
    mixed = dry_part + wet_part * wet_gain
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak
    return mixed.astype(np.float32)


def _apply_algorithmic_reverb(
    dry: np.ndarray,
    sample_rate: int,
    config: dict[str, Any],
) -> np.ndarray:
    room_size = float(config.get("room_size", 0.48))
    damping = float(config.get("damping", 0.35))
    width = float(config.get("width", 1.0))
    wet_level = float(config.get("wet_level", 0.38))
    dry_level = float(config.get("dry_level", 0.88))

    board: list[Any] = [
        Reverb(
            room_size=room_size,
            damping=damping,
            wet_level=wet_level,
            dry_level=dry_level,
            width=width,
        )
    ]
    high_cut = config.get("high_cut_hz")
    if high_cut is not None:
        board.append(LowpassFilter(cutoff_frequency_hz=float(high_cut)))

    mixed = np.asarray(Pedalboard(board)(dry, sample_rate), dtype=np.float32)
    if mixed.ndim == 1:
        mixed = mixed[np.newaxis, :]

    # Optional global trim if YAML still sets wet_db (attenuate entire processed signal).
    wet_db = config.get("wet_db")
    if wet_db is not None:
        trim = _wet_gain_linear(float(wet_db)) / _wet_gain_linear(_DEFAULT_WET_DB)
        trim = float(np.clip(trim, 0.25, 1.5))
        if abs(trim - 1.0) > 0.01:
            mixed = mixed * trim

    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak
    return mixed.astype(np.float32)


def apply_narrator_reverb(
    segment: AudioSegment,
    config: dict[str, Any] | None,
) -> AudioSegment:
    """Apply auditorium-style reverb to a narrator TTS segment."""
    if not config:
        return segment
    if config.get("enabled") is False:
        return segment

    original_channels = segment.channels
    original_width = segment.sample_width
    original_rate = segment.frame_rate

    # gTTS is often 24 kHz mono; pedalboard sounds clearer at 44.1 kHz.
    work = segment
    if work.frame_rate < 44100:
        work = work.set_frame_rate(44100)

    dry_array, sample_rate = _segment_to_float32_array(work)
    mode = str(config.get("mode", "convolution")).lower()
    try:
        if mode == "reverb":
            processed = _apply_algorithmic_reverb(dry_array, sample_rate, config)
        else:
            processed = _apply_convolution_reverb(dry_array, sample_rate, config)
    except Exception:
        logger.warning(
            "Narrator reverb failed (mode=%s); returning dry audio",
            mode,
            exc_info=True,
        )
        return segment

    out = _float32_array_to_segment(
        processed,
        sample_rate,
        original_channels,
        original_width,
    )
    if out.frame_rate != original_rate:
        out = out.set_frame_rate(original_rate)
    logger.info(
        "Applied narrator reverb (mode=%s, wet_db=%s, channels=%s, ms=%s)",
        mode,
        config.get("wet_db", _DEFAULT_WET_DB),
        original_channels,
        len(out),
    )
    return out
