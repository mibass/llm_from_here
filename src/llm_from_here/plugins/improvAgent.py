"""Agentic improv scene generator: scene setup, per-slot performer models, SFX cues.

The committed runtime path does not judge turns with an LLM. Each performer model
returns a structured turn (spoken dialog + optional stage direction + concrete SFX
cues), and the scene is trusted as generated. Scene-quality judging lives in
dev-only tooling (see ``evals/eval_improv_agent.py``), not here.
"""

from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from typing import Any

import yaml

from llm_from_here.llm_session import LlmSession
from llm_from_here.plugins.freesoundfetch import FreeSoundFetch
from llm_from_here.schemas.improv_outputs import ImprovTurn, SceneSetup

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "openrouter:openai/gpt-4o-mini"

_ANY_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
# Only explicit sound cues become SFX; arbitrary stage directions like
# ``[Alice leans closer]`` are not treated as Freesound queries.
_SFX_CUE_RE = re.compile(r"\[(?:SFX|SOUND)\s*:\s*([^\]]+)\]", re.IGNORECASE)


def _strip_bracket_cues(text: str) -> str:
    """Remove any bracketed content (stage directions / cues) from spoken text."""
    return _ANY_BRACKET_RE.sub("", text).replace("  ", " ").strip()


def _extract_bracket_cues(text: str) -> list[str]:
    """Extract only explicit ``[SFX: ...]`` / ``[SOUND: ...]`` cues (compat fallback)."""
    out: list[str] = []
    for raw in _SFX_CUE_RE.findall(text or ""):
        s = raw.strip()
        if s:
            out.append(s)
    return out


def _normalize_sfx_query(cue: str) -> str:
    """Trim a cue into a short, concrete Freesound-style search query."""
    s = re.sub(r"\s+", " ", (cue or "").strip())
    s = s.strip(" .!?,;:\"'")
    return s[:120]


def _clean_dialog(dialog: str, name: str) -> str:
    """Strip bracket cues, surrounding quotes, and leaked ``Name:`` speaker prefixes."""
    cleaned = _strip_bracket_cues(dialog or "")
    prefix_re = re.compile(rf"^\s*{re.escape(name)}\s*:\s*", re.IGNORECASE)
    prev: str | None = None
    while prev != cleaned:
        prev = cleaned
        cleaned = prefix_re.sub("", cleaned)
    cleaned = cleaned.strip().strip('"').strip()
    return cleaned or (dialog or "").strip()


_DEFAULT_SFX_MAP: dict[str, Any] = {
    "sound effect": {
        "segment_type": "music_generator_freesound",
        "arguments": {
            "duration_min_sec": 1,
            "duration_max_sec": 60,
        },
    },
    "background": {
        "segment_type": "music_generator_freesound",
        "background_music": True,
        "arguments": {
            "duration_min_sec": 30,
            "duration_max_sec": 200,
        },
    },
    "default": {"segment_type": "slow_TTS", "arguments": {}},
}


class ImprovAgent:
    """Multi-model improv pipeline: structured performer turns and Freesound SFX cues."""

    def __init__(self, params: dict[str, Any], global_results: dict[str, Any], plugin_instance_name: str):
        self.params = params
        self.global_results = global_results
        self.plugin_instance_name = plugin_instance_name
        self.output_folder = global_results.get("output_folder", ".")
        self.freesound_fetch = FreeSoundFetch(
            params, global_results, plugin_instance_name, out_dir=self.output_folder
        )

        self.character_slots_cfg: list[dict[str, Any]] = params.get("character_slots") or []
        if not self.character_slots_cfg:
            raise ValueError("improvAgent requires params.character_slots (non-empty list).")

        self.setup_system_message = params.get("setup_system_message") or (
            "You are a long-form improv director. Establish a complete scene setup."
        )

        # Scene setup uses a single OpenRouter session. Prefer an explicit
        # setup_model; otherwise reuse the first character slot's model. No judge.
        setup_model = (params.get("setup_model") or "").strip()
        if not setup_model:
            setup_model = (self.character_slots_cfg[0].get("model") or "").strip()
        setup_model = setup_model or _DEFAULT_MODEL
        self.setup_session = LlmSession(self.setup_system_message, model_slug=setup_model)

        self.slot_sessions: list[LlmSession] = []
        for slot_cfg in self.character_slots_cfg:
            m = (slot_cfg.get("model") or "").strip() or _DEFAULT_MODEL
            sys_m = slot_cfg.get("system_message") or (
                "You are an improv performer. Listen, yes-and, speak only in character."
            )
            self.slot_sessions.append(LlmSession(sys_m, model_slug=m))

        self.target_turn_count = int(params.get("target_turn_count", 20))
        self.scene_injection = (params.get("scene_injection") or "").strip()

        self.audit_log: list[dict[str, Any]] = []
        self.scene: SceneSetup | None = None

    def _build_segment_type_map(self, scene: SceneSetup) -> dict[str, Any]:
        base = deepcopy(self.params.get("segment_type_map_base") or _DEFAULT_SFX_MAP)
        for i, ch in enumerate(scene.characters):
            slot_cfg = self.character_slots_cfg[i] if i < len(self.character_slots_cfg) else {}
            voice = (slot_cfg.get("tts_voice") or "").strip() or None
            tts_model = (slot_cfg.get("tts_model") or "").strip() or None
            arguments: dict[str, Any] = {}
            if voice:
                arguments["voice"] = voice
            if tts_model:
                arguments["tts_model"] = tts_model
            key = f"character {ch.slot}"
            # slow_TTS routes to the Google/Gemini TTS path so per-character voices apply
            # (fast_TTS uses gTTS and ignores the voice parameter).
            base[key] = {
                "segment_type": "slow_TTS",
                "arguments": arguments,
            }
        return base

    def _run_setup(self) -> SceneSetup:
        n = len(self.character_slots_cfg)
        inj = ""
        if self.scene_injection:
            inj = (
                "\nOptional producer constraint (must honor if it does not violate safety):\n"
                f"{self.scene_injection}\n"
            )
        prompt = (
            f"{self.setup_system_message}\n\n"
            f"You must define exactly {n} characters with slots 1..{n} in order. "
            "Each needs a distinct playable name and a one-sentence want or obstacle.\n"
            "Also provide: setting, scenario (inciting incident), background_sound "
            "(short Freesound-style ambient query), and sfx_palette (3–5 short searchable SFX labels).\n"
            f"{inj}\n"
            "Respond using the required structured output schema only."
        )
        data = self.setup_session.run_structured(prompt, SceneSetup, log_prompt=True)
        scene = SceneSetup.model_validate(data)
        if len(scene.characters) != n:
            raise ValueError(
                f"SceneSetup returned {len(scene.characters)} characters; expected {n}."
            )
        scene = scene.model_copy(
            update={
                "characters": sorted(scene.characters, key=lambda c: c.slot),
            }
        )
        for j, ch in enumerate(scene.characters, start=1):
            if ch.slot != j:
                raise ValueError(f"Character slot mismatch: expected {j}, got {ch.slot}")
        logger.info("Scene setup: %s", scene.model_dump())
        return scene

    def _prime_slots(self, scene: SceneSetup) -> None:
        bible = yaml.safe_dump(scene.model_dump(), sort_keys=False)
        for i, sess in enumerate(self.slot_sessions):
            ch = scene.characters[i]
            sess.chat(
                "The director locked in this scene. Read it; you will speak in-character when cued.\n\n"
                f"{bible}\n"
                f"You are **{ch.name}** (slot {ch.slot}): {ch.description}\n"
                "Acknowledge in one short in-character line (this primes your voice)."
            )

    def _turn_prompt(self, scene: SceneSetup, ch_name: str, transcript_parts: list[str]) -> str:
        palette = ", ".join(scene.sfx_palette) if scene.sfx_palette else ""
        palette_hint = (
            f"Prefer sounds from this palette when apt: {palette}. " if palette else ""
        )
        return (
            "Transcript so far:\n"
            + "\n".join(transcript_parts)
            + f"\n\nYour turn, {ch_name}. Deliver the next beat as ONE structured turn:\n"
            "- dialog: one or two sentences of spoken words only. Do NOT prefix your name. "
            "Do NOT include stage directions or bracketed cues in dialog.\n"
            "- stage_direction: optional short acting note (not spoken).\n"
            "- sfx_cues: zero to two concrete, audible sound-effect search queries. "
            f"{palette_hint}"
            "Use real sounds (e.g. 'coffee machine steam', 'doorbell chime', 'chair scrape'), "
            "not emotions or gestures. Leave empty if no sound is warranted.\n"
        )

    def _sfx_segments_for_turn(
        self, turn: ImprovTurn, turn_index: int
    ) -> list[dict[str, Any]]:
        """Build sound-effect segments from structured cues (+ explicit bracket fallback)."""
        cues: list[str] = list(turn.sfx_cues)
        cues += _extract_bracket_cues(turn.stage_direction)
        cues += _extract_bracket_cues(turn.dialog)

        segments: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cue in cues:
            query = _normalize_sfx_query(cue)
            if not query or query.lower() in seen:
                continue
            seen.add(query.lower())
            segments.append(
                {
                    "speaker": "sound effect",
                    "dialog": query,
                    "character_name": None,
                    "sfx_search_query": query,
                    "sfx_freesound_id": None,
                }
            )
            self.audit_log.append(
                {
                    "phase": "sfx",
                    "turn_index": turn_index,
                    "cue": cue,
                    "query": query,
                }
            )
        return segments

    def _generation_loop(self, scene: SceneSetup) -> tuple[list[dict[str, Any]], str]:
        segments: list[dict[str, Any]] = []
        transcript_parts: list[str] = []

        segments.append(
            {
                "speaker": "background",
                "dialog": f"[BACKGROUND: {scene.background_sound}]",
                "character_name": None,
            }
        )
        transcript_parts.append(f"[ambient] {scene.background_sound}")

        turns_done = 0
        while turns_done < self.target_turn_count:
            for i, sess in enumerate(self.slot_sessions):
                if turns_done >= self.target_turn_count:
                    break
                ch = scene.characters[i]
                speaker_key = f"character {ch.slot}"
                prompt = self._turn_prompt(scene, ch.name, transcript_parts)

                raw = sess.run_structured(prompt, ImprovTurn)
                turn = ImprovTurn.model_validate(raw)
                dialog = _clean_dialog(turn.dialog, ch.name)

                segments.append(
                    {
                        "speaker": speaker_key,
                        "dialog": dialog,
                        "character_name": ch.name,
                    }
                )
                transcript_parts.append(f"{ch.name}: {dialog}")

                segments.extend(self._sfx_segments_for_turn(turn, turns_done))

                self.audit_log.append(
                    {
                        "phase": "turn",
                        "turn_index": turns_done,
                        "slot": ch.slot,
                        "character": ch.name,
                        "dialog": dialog,
                        "stage_direction": turn.stage_direction,
                        "sfx_cues": list(turn.sfx_cues),
                    }
                )
                turns_done += 1

        script = "\n".join(transcript_parts)
        return segments, script

    def _write_debug_dump(self, scene: SceneSetup, segments: list[dict[str, Any]], script: str) -> str | None:
        path = os.path.join(self.output_folder, "improv_debug.json")
        try:
            payload = {
                "scene_setup": scene.model_dump(),
                "transcript": script,
                "segments": segments,
                "audit_log": self.audit_log,
                "params_snapshot": {
                    "target_turn_count": self.target_turn_count,
                    "num_characters": len(scene.characters),
                },
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
            logger.info("Wrote improv debug dump to %s", path)
            return path
        except OSError as e:
            logger.error("Could not write improv_debug.json: %s", e)
            return None

    def execute(self) -> dict[str, Any]:
        self.scene = self._run_setup()
        assert self.scene is not None
        self._prime_slots(self.scene)
        segments, script = self._generation_loop(self.scene)
        seg_map = self._build_segment_type_map(self.scene)
        debug_path = self._write_debug_dump(self.scene, segments, script)

        out: dict[str, Any] = {
            "segments": segments,
            "script": script,
            "segment_type_map": seg_map,
            "scene_setup": self.scene.model_dump(),
            "transcript": script,
            "turn_audit_log": self.audit_log,
            "chat_app": self.setup_session,
        }
        if debug_path:
            out["improv_debug_path"] = debug_path
        return out
