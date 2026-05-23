"""Agentic improv scene generator: setup, per-slot models, SFX search+judge, turn judge."""

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
from llm_from_here.schemas.improv_outputs import (
    SceneSetup,
    SfxJudgement,
    TurnJudgement,
)

logger = logging.getLogger(__name__)

_BRACKET_CUE_RE = re.compile(r"\[([^\]]+)\]")


def _strip_bracket_cues(text: str) -> str:
    return _BRACKET_CUE_RE.sub("", text).replace("  ", " ").strip()


def _extract_bracket_cues(text: str) -> list[str]:
    raw = _BRACKET_CUE_RE.findall(text)
    out: list[str] = []
    for r in raw:
        s = r.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("background") or low.startswith("music"):
            continue
        out.append(s)
    return out


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
    "default": {"segment_type": "fast_TTS", "arguments": {}},
}


class ImprovAgent:
    """Multi-model improv pipeline with LLM judge and Freesound SFX selection."""

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

        judge_model = (params.get("judge_model") or "").strip() or "openai/gpt-4o-mini"
        judge_sys = params.get("judge_system_message") or (
            "You are an improv director and quality judge. "
            "Score turns and pick sound effects from candidates."
        )
        self.judge_session = LlmSession(judge_sys, model_slug=judge_model)

        self.slot_sessions: list[LlmSession] = []
        for slot_cfg in self.character_slots_cfg:
            m = (slot_cfg.get("model") or "").strip() or "openai/gpt-4o-mini"
            sys_m = slot_cfg.get("system_message") or (
                "You are an improv performer. Listen, yes-and, speak only in character."
            )
            self.slot_sessions.append(LlmSession(sys_m, model_slug=m))

        self.target_turn_count = int(params.get("target_turn_count", 20))
        self.max_regen_per_turn = int(params.get("max_regen_per_turn", 2))
        self.sfx_candidates = int(params.get("sfx_candidates", 5))
        self.judge_pass_threshold = int(params.get("judge_pass_threshold", 3))
        self.scene_injection = (params.get("scene_injection") or "").strip()
        self.setup_system_message = params.get("setup_system_message") or (
            "You are a long-form improv director. Establish a complete scene setup."
        )

        self.audit_log: list[dict[str, Any]] = []
        self.scene: SceneSetup | None = None

    def _build_segment_type_map(self, scene: SceneSetup) -> dict[str, Any]:
        base = deepcopy(self.params.get("segment_type_map_base") or _DEFAULT_SFX_MAP)
        for i, ch in enumerate(scene.characters):
            slot_cfg = self.character_slots_cfg[i] if i < len(self.character_slots_cfg) else {}
            voice = (slot_cfg.get("tts_voice") or "").strip() or None
            key = f"character {ch.slot}"
            base[key] = {
                "segment_type": "fast_TTS",
                "arguments": ({**({"voice": voice} if voice else {})}),
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
        data = self.judge_session.run_structured(prompt, SceneSetup, log_prompt=True)
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

    def _collect_freesound_candidates(self, query: str) -> list[Any]:
        if not query.strip():
            return []
        try:
            filt = "duration:[1 TO 120]"
            it = self.freesound_fetch.search_samples(query, {"filter": filt})
            sounds: list[Any] = []
            for s in it:
                sounds.append(s)
                if len(sounds) >= self.sfx_candidates:
                    break
            return sounds
        except Exception as e:
            logger.warning("Freesound search failed for %r: %s", query, e)
            return []

    def _judge_pick_sfx(self, cue: str, dialog_context: str, sounds: list[Any]) -> tuple[int | None, str]:
        if not sounds:
            return None, "no candidates"
        lines = []
        for idx, s in enumerate(sounds):
            desc = getattr(s, "description", "") or ""
            if not isinstance(desc, str):
                desc = str(desc)
            desc = desc[:240].replace("\n", " ")
            lines.append(f"{idx}: id={getattr(s, 'id', '?')} name={getattr(s, 'name', '?')!r} desc={desc!r}")
        prompt = (
            f"{self.params.get('judge_system_message') or ''}\n\n"
            "Pick the single best Freesound sample index for this staged cue.\n"
            f"Cue from script: {cue!r}\n"
            f"Surrounding dialogue context:\n{dialog_context}\n\n"
            "Candidates:\n"
            + "\n".join(lines)
            + "\n\nReturn structured SfxJudgement with chosen_index and brief reasoning."
        )
        raw = self.judge_session.run_structured(prompt, SfxJudgement, log_prompt=True)
        j = SfxJudgement.model_validate(raw)
        if j.chosen_index < 0 or j.chosen_index >= len(sounds):
            logger.warning("SfxJudgement index out of range; clamping. got=%s", j.chosen_index)
            return 0, j.reasoning
        return j.chosen_index, j.reasoning

    def _judge_turn(
        self,
        scene: SceneSetup,
        transcript: str,
        slot: int,
        character_name: str,
        line: str,
    ) -> TurnJudgement:
        prompt = (
            f"{self.params.get('judge_system_message') or ''}\n\n"
            "Score the latest improvised line for a two-hander scene.\n"
            f"Setting: {scene.setting}\nScenario: {scene.scenario}\n\n"
            f"Transcript so far:\n{transcript}\n\n"
            f"Latest line from {character_name} (slot {slot}):\n{line}\n\n"
            "Return TurnJudgement. Use pass_turn=true only if the line is playable, "
            "yes-ands the partner, and stays in character. "
            "end_scene=true only if the scene should naturally end now (rare)."
        )
        raw = self.judge_session.run_structured(prompt, TurnJudgement, log_prompt=True)
        return TurnJudgement.model_validate(raw)

    def _scores_meet_threshold(self, t: TurnJudgement) -> bool:
        if not t.pass_turn:
            return False
        th = self.judge_pass_threshold
        return t.coherence >= th and t.yes_and >= th and t.character_consistency >= th

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
        end_scene = False
        while turns_done < self.target_turn_count and not end_scene:
            for i, sess in enumerate(self.slot_sessions):
                if turns_done >= self.target_turn_count or end_scene:
                    break
                ch = scene.characters[i]
                speaker_key = f"character {ch.slot}"
                base_user = (
                    f"Transcript so far:\n"
                    + "\n".join(transcript_parts)
                    + f"\n\nYour turn, **{ch.name}**. "
                    "Deliver the next beat (one or two sentences). "
                    "Stay in character; yes-and your partner. "
                    "Optional bracketed sound cues like [door creak] are allowed.\n"
                )
                line = ""
                judgement = TurnJudgement(
                    coherence=1,
                    yes_and=1,
                    character_consistency=1,
                    pass_turn=False,
                    end_scene=False,
                    feedback="",
                )
                for attempt in range(self.max_regen_per_turn + 1):
                    extra = ""
                    if attempt > 0 and judgement.feedback:
                        extra = (
                            f"\nDirector note (fix and continue): {judgement.feedback}\n"
                        )
                    line = sess.chat(base_user + extra).strip()
                    judgement = self._judge_turn(
                        scene,
                        "\n".join(transcript_parts),
                        ch.slot,
                        ch.name,
                        line,
                    )
                    self.audit_log.append(
                        {
                            "phase": "turn",
                            "turn_index": turns_done,
                            "slot": ch.slot,
                            "character": ch.name,
                            "line": line,
                            "attempt": attempt,
                            "judgement": judgement.model_dump(),
                        }
                    )
                    if self._scores_meet_threshold(judgement):
                        break
                    if attempt < self.max_regen_per_turn:
                        for _ in range(2):
                            sess.delete_last_message()
                if not self._scores_meet_threshold(judgement):
                    logger.warning(
                        "Turn judge never passed for slot %s after %s attempts; keeping last line.",
                        ch.slot,
                        self.max_regen_per_turn + 1,
                    )

                clean = _strip_bracket_cues(line) or line
                segments.append(
                    {
                        "speaker": speaker_key,
                        "dialog": clean,
                        "character_name": ch.name,
                    }
                )
                transcript_parts.append(f"{ch.name}: {line}")

                cues = _extract_bracket_cues(line)
                ctx = "\n".join(transcript_parts[-4:])
                for cue in cues:
                    query = cue[:120]
                    sounds = self._collect_freesound_candidates(query)
                    idx, sfx_reason = self._judge_pick_sfx(cue, ctx, sounds)
                    fs_id = None
                    if idx is not None and sounds:
                        try:
                            fs_id = int(getattr(sounds[idx], "id", None))
                        except (TypeError, ValueError):
                            fs_id = None
                    segments.append(
                        {
                            "speaker": "sound effect",
                            "dialog": query,
                            "character_name": None,
                            "sfx_search_query": query,
                            "sfx_freesound_id": fs_id,
                        }
                    )
                    self.audit_log.append(
                        {
                            "phase": "sfx",
                            "cue": cue,
                            "query": query,
                            "chosen_index": idx,
                            "judge_reason": sfx_reason,
                            "freesound_id": fs_id,
                        }
                    )

                turns_done += 1
                if judgement.end_scene:
                    end_scene = True
                    break

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
                    "judge_pass_threshold": self.judge_pass_threshold,
                    "sfx_candidates": self.sfx_candidates,
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
            "chat_app": self.judge_session,
        }
        if debug_path:
            out["improv_debug_path"] = debug_path
        return out
