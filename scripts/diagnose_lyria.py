#!/usr/bin/env python3
"""Probe OpenRouter Lyria streaming shapes (diagnostic only)."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from typing import Any

import dotenv
import requests

dotenv.load_dotenv()

PROMPT_180S = (
    "Create a 180-second instrumental track at 90 BPM. "
    "Live acoustic folk intro. Mandolin, acoustic guitar, upright bass, light percussion, "
    "warm and nostalgic. Instrumental only, no vocals."
)

PROMPT_30S = (
    "Create a 30-second instrumental track at 90 BPM. "
    "Live acoustic folk intro. Mandolin, acoustic guitar, upright bass, light percussion, "
    "warm and nostalgic. Instrumental only, no vocals."
)

VARIANTS: list[tuple[str, dict[str, Any]]] = [
    (
        "current_text_and_audio",
        {
            "stream": True,
            "extra_body": {
                "modalities": ["text", "audio"],
                "audio": {"format": "mp3"},
            },
        },
    ),
    (
        "audio_only_modality",
        {
            "stream": True,
            "extra_body": {
                "modalities": ["audio"],
                "audio": {"format": "mp3"},
            },
        },
    ),
    (
        "plain_stream_no_extra",
        {"stream": True},
    ),
    (
        "non_stream_text_audio",
        {
            "stream": False,
            "extra_body": {
                "modalities": ["text", "audio"],
                "audio": {"format": "mp3"},
            },
        },
    ),
]

LYRIA_PRO_SLUG = "google/lyria-3-pro-preview"
LYRIA_CLIP_SLUG = "google/lyria-3-clip-preview"


def prompt_for_duration(seconds: int) -> str:
    return (
        f"Create a {seconds}-second instrumental track at 90 BPM. "
        "Live acoustic folk intro. Mandolin, acoustic guitar, upright bass, light percussion, "
        "warm and nostalgic. Instrumental only, no vocals."
    )


def _chunk_dict(chunk: Any) -> dict[str, Any]:
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump(exclude_none=True)
    if isinstance(chunk, dict):
        return chunk
    return {"repr": repr(chunk)}


def _keys(obj: Any, prefix: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.append(path)
            out.extend(_keys(v, path))
    elif isinstance(obj, list) and obj:
        out.extend(_keys(obj[0], f"{prefix}[0]"))
    return out


def _find_audio_paths(obj: Any, prefix: str = "") -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if k in ("data", "audio", "b64", "bytes") and isinstance(v, str) and len(v) > 100:
                found.append((path, len(v)))
            found.extend(_find_audio_paths(v, path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):
            found.extend(_find_audio_paths(item, f"{prefix}[{i}]"))
    return found


def run_variant(
    client: Any,
    model: str,
    name: str,
    kwargs: dict[str, Any],
    *,
    prompt: str,
) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "variant": name,
        "model": model,
        "prompt": prompt,
        "kwargs": kwargs,
        "ok": False,
        "error": None,
        "elapsed_sec": 0.0,
        "chunk_count": 0,
        "summaries": [],
        "audio_paths": [],
        "content_preview": None,
        "mp3_bytes": 0,
    }
    try:
        if kwargs.get("stream"):
            stream = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **{k: v for k, v in kwargs.items() if k != "stream"},
                stream=True,
            )
            content_parts: list[str] = []
            audio_b64_parts: list[str] = []
            raw_chunks: list[dict[str, Any]] = []
            for chunk in stream:
                d = _chunk_dict(chunk)
                raw_chunks.append(d)
                result["chunk_count"] += 1
                if len(result["summaries"]) < 6:
                    choice = (d.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    result["summaries"].append(
                        {
                            "content": (delta.get("content") or "")[:120],
                            "audio_keys": sorted((delta.get("audio") or {}).keys())
                            if isinstance(delta.get("audio"), dict)
                            else None,
                            "finish_reason": choice.get("finish_reason"),
                        }
                    )
                for path, n in _find_audio_paths(d):
                    result["audio_paths"].append({"path": path, "len": n})
                choice = (d.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                audio = delta.get("audio")
                if isinstance(audio, dict) and audio.get("data"):
                    audio_b64_parts.append(audio["data"])
                if delta.get("content"):
                    content_parts.append(str(delta["content"]))
            joined = "".join(content_parts)
            result["content_preview"] = joined[:200]
            if audio_b64_parts:
                mp3 = base64.b64decode("".join(audio_b64_parts))
                result["mp3_bytes"] = len(mp3)
                result["ok"] = True
            elif joined.startswith("data:audio") or _looks_like_b64_audio(joined):
                mp3 = _decode_maybe_b64_audio(joined)
                result["mp3_bytes"] = len(mp3)
                result["ok"] = bool(mp3)
            result["all_keys_sample"] = _keys(raw_chunks[0]) if raw_chunks else []
            if raw_chunks:
                result["response_model"] = raw_chunks[0].get("model")
                result["response_provider"] = raw_chunks[0].get("provider")
        else:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **{k: v for k, v in kwargs.items() if k != "stream"},
            )
            d = _chunk_dict(resp)
            result["chunk_count"] = 1
            result["summaries"] = [{"top_keys": sorted(d.keys())}]
            result["audio_paths"] = [{"path": p, "len": n} for p, n in _find_audio_paths(d)]
            result["content_preview"] = str(
                ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            )[:200]
            msg = (d.get("choices") or [{}])[0].get("message") or {}
            audio = msg.get("audio")
            if isinstance(audio, dict) and audio.get("data"):
                mp3 = base64.b64decode(audio["data"])
                result["mp3_bytes"] = len(mp3)
                result["ok"] = True
            result["ok"] = result["ok"] or bool(result["audio_paths"])
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_sec"] = round(time.monotonic() - started, 2)
    return result


def _looks_like_b64_audio(s: str) -> bool:
    s = s.strip()
    return len(s) > 500 and all(c.isalnum() or c in "+/=\n" for c in s[:200])


def _decode_maybe_b64_audio(s: str) -> bytes:
    s = s.strip()
    if s.startswith("data:"):
        s = s.split(",", 1)[-1]
    return base64.b64decode(s)


def verify_openrouter_models(api_key: str, configured_model: str) -> dict[str, Any]:
    """Fetch Lyria Pro/Clip metadata from OpenRouter and compare to configured slug."""
    headers = {"Authorization": f"Bearer {api_key}"}
    out: dict[str, Any] = {
        "configured_model": configured_model,
        "configured_is_pro": configured_model == LYRIA_PRO_SLUG,
        "configured_is_clip": configured_model == LYRIA_CLIP_SLUG,
        "configured_is_lyria": "lyria" in configured_model.lower(),
        "models": {},
    }
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        all_models = resp.json().get("data") or []
        by_id = {m.get("id"): m for m in all_models if isinstance(m, dict)}
    except Exception as exc:
        out["models_error"] = str(exc)
        by_id = {}

    for slug in (LYRIA_PRO_SLUG, LYRIA_CLIP_SLUG, configured_model):
        if slug in out["models"]:
            continue
        entry = by_id.get(slug)
        if entry:
            out["models"][slug] = {
                k: entry.get(k)
                for k in ("id", "name", "description", "pricing", "top_provider", "architecture")
            }
        else:
            out["models"][slug] = {"error": "not found in /models list"}

    pro = out["models"].get(LYRIA_PRO_SLUG) or {}
    clip = out["models"].get(LYRIA_CLIP_SLUG) or {}
    out["summary"] = {
        "pro_id": pro.get("id") if isinstance(pro, dict) else None,
        "pro_name": pro.get("name") if isinstance(pro, dict) else None,
        "clip_id": clip.get("id") if isinstance(clip, dict) else None,
        "clip_name": clip.get("name") if isinstance(clip, dict) else None,
        "routing_ok": configured_model == LYRIA_PRO_SLUG,
        "warning": None,
    }
    if configured_model == LYRIA_CLIP_SLUG:
        out["summary"]["warning"] = (
            "OPENROUTER_MUSIC_MODEL is Lyria Clip (30s max, no duration controls). "
            "Use google/lyria-3-pro-preview for 180-second cues."
        )
    elif configured_model != LYRIA_PRO_SLUG:
        out["summary"]["warning"] = (
            f"Configured model {configured_model!r} is not the expected Pro slug "
            f"{LYRIA_PRO_SLUG!r}."
        )
    return out


def run_duration_ab(client: Any, model: str) -> list[dict[str, Any]]:
    """Compare 30s vs 180s prompts using the production audio-only modality."""
    kwargs = {
        "stream": True,
        "extra_body": {
            "modalities": ["audio"],
            "audio": {"format": "mp3"},
        },
    }
    results: list[dict[str, Any]] = []
    for seconds in (30, 180):
        prompt = prompt_for_duration(seconds)
        name = f"duration_{seconds}s_audio_only"
        print(f"\n=== {name} ===", flush=True)
        r = run_variant(client, model, name, kwargs, prompt=prompt)
        results.append(r)
        print(json.dumps(r, indent=2))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose OpenRouter Lyria response shapes")
    parser.add_argument("--model", default=os.getenv("OPENROUTER_MUSIC_MODEL", LYRIA_PRO_SLUG))
    parser.add_argument("--variant", action="append", help="Run only named variant(s)")
    parser.add_argument(
        "--duration-ab",
        action="store_true",
        help="Run 30s vs 180s A/B test with audio-only modality (production path)",
    )
    parser.add_argument(
        "--verify-model",
        action="store_true",
        help="Fetch OpenRouter metadata for Lyria Pro vs Clip and compare to configured model",
    )
    parser.add_argument("--json-out", help="Write full results JSON here")
    args = parser.parse_args()

    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        return 1

    from llm_from_here.llm_env import build_openrouter_client, get_openrouter_music_model

    configured = get_openrouter_music_model()
    model = args.model or configured
    results: list[dict[str, Any]] = []

    if args.verify_model:
        print("\n=== verify_model ===", flush=True)
        verification = verify_openrouter_models(os.environ["OPENROUTER_API_KEY"], configured)
        results.append({"verify_model": verification})
        print(json.dumps(verification, indent=2))
        if verification["summary"].get("warning"):
            print(f"\nWARNING: {verification['summary']['warning']}", file=sys.stderr)

    client = build_openrouter_client()

    if args.duration_ab:
        results.extend(run_duration_ab(client, model))
    elif args.variant or not args.verify_model:
        variants = VARIANTS
        if args.variant:
            names = set(args.variant)
            variants = [v for v in VARIANTS if v[0] in names]
        for name, kwargs in variants:
            print(f"\n=== {name} ===", flush=True)
            r = run_variant(client, model, name, kwargs, prompt=PROMPT_180S)
            results.append(r)
            print(json.dumps(r, indent=2))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"\nWrote {args.json_out}")

    ok_results = [r for r in results if r.get("ok")]
    return 0 if ok_results else 2


if __name__ == "__main__":
    raise SystemExit(main())
