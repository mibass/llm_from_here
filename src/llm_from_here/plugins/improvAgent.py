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
from llm_from_here.openrouter_web_search import run_web_search
from llm_from_here.plugins.freesoundfetch import FreeSoundFetch
from llm_from_here.schemas.improv_outputs import ImprovTurn, SceneSetup

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "openrouter:deepseek/deepseek-v4-flash"

# Web-search prompt used when ``news_inspiration: true`` with no custom prompt.
# The director mines ONE familiar, well-known story from the week as optional
# inspiration. It is open to any topic; the model picks based on the (already
# retrieved) search results rather than being steered toward a niche/odd story.
_DEFAULT_NEWS_INSPIRATION_PROMPT = (
    "Among the search results, pick ONE familiar, notable, well-known news story from "
    "the past week, open to any topic. Keep it light and wholesome: avoid tragedy, death, "
    "violence, disasters, war, and grim crime. Choose based on the actual results \u2014 do "
    "not invent one. Return a factual 2-3 sentence summary plus the setting and the "
    "characters involved."
)

_MAX_NEWS_INSPIRATION_CHARS = 900

# Hard upper bound on SFX cues honored per turn. The turn prompt asks for at
# most one (a second only when integral); this guarantees the bound even when
# the model disobeys, so a turn can never flood the timeline with foley.
_MAX_SFX_CUES_PER_TURN = 2

_ANY_BRACKET_RE = re.compile(r"\[([^\]]+)\]")
# Only explicit sound cues become SFX; arbitrary stage directions like
# ``[Alice leans closer]`` are not treated as Freesound queries.
_SFX_CUE_RE = re.compile(r"\[(?:SFX|SOUND)\s*:\s*([^\]]+)\]", re.IGNORECASE)
# A sung/hummed beat is requested as ``[SUNG: <what is sung>]`` in stage_direction
# (never dialog). The expressive Gemini TTS performs it as a hum/song when we pass
# it a clear directive, so we route it deliberately rather than letting prose leak.
_SUNG_CUE_RE = re.compile(r"\[(?:SUNG|SING|HUM)\s*:\s*([^\]]+)\]", re.IGNORECASE)
# A directive sentence that instructs the voice to perform rather than speak; used
# to keep accidental performance instructions out of spoken dialog (belt + suspenders
# on top of the prompt rule). Two shapes: a modal imperative ("you have to hum...") or
# a bare imperative ("hum Twinkle Twinkle"/"you hum."). Descriptive phrasing like
# "you hum it so well" is NOT matched and stays as dialogue.
_PERFORM_DIRECTIVE_RE = re.compile(
    r"^\s*(?:"
    r"(?:you\s+(?:must|have to|need to|should|gotta|could)\s+)?"
    r"(?:hum|humming|sing|singing|whistle|whistling|laugh|laughing|sigh|sighing|"
    r"chant|chanting|moan|moaning|growl|growling|mutter|muttering)\b"
    r"|"
    r"you\s+(?:hum|humming|sing|singing|whistle|whistling)\s*(?:[.!?:,]|$)"
    r")",
    re.IGNORECASE,
)

# Rotating "this beat, play this move" menus injected per turn to break the
# recurrent groove where the escalator only scales up and the straight man
# only prices things out. Indexed by global turn count.
_ESCALATOR_MOVES: list[str] = [
    "raise the stakes in scale or scope",
    "reinterpret your partner's objection into evidence for your cause",
    "surface a brand-new absurd domain tied to your obsession",
    "invert the frame: make your partner's objection your new goal",
    "reveal a hidden motive or backstory that justifies the obsession",
    "deflate yourself for one beat, then recommit harder",
]
_STRAIGHT_MAN_MOVES: list[str] = [
    "escalate the practical consequences of the obsession",
    "escalate procedure, policy, or authority that blocks it",
    "state the personal stake it costs you (time, people, sanity)",
    "reveal your own hidden motive for being the skeptic",
    "take your partner seriously for a beat and be momentarily charmed",
    "pay one genuine human beat before re-grounding the Game",
]


def _rotating_moves(turn_index: int) -> tuple[str, str]:
    """Return (escalator move, straight-man move) for the given global turn index."""
    n = len(_ESCALATOR_MOVES)
    return _ESCALATOR_MOVES[turn_index % n], _STRAIGHT_MAN_MOVES[turn_index % n]


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


def _extract_sung_cue(text: str) -> str | None:
    """Return the requested sung/hummed content from a ``[SUNG: ...]`` cue, or None."""
    m = _SUNG_CUE_RE.search(text or "")
    if not m:
        return None
    s = re.sub(r"\s+", " ", m.group(1)).strip()
    return s or None


def _strip_performance_directives(dialog: str) -> str:
    """Drop leading directive sentences that instruct a performance (hum/sing/...).

    Guards against a performer leaking an acting note into spoken dialog, which the
    expressive Gemini TTS would otherwise *perform* (e.g. it may hum a melody).
    """
    if not dialog:
        return dialog
    sentences = re.split(r"(?<=[.!?])\s+", dialog.strip())
    kept: list[str] = []
    started = False
    for sent in sentences:
        if not started and _PERFORM_DIRECTIVE_RE.match(sent):
            continue
        started = True
        kept.append(sent)
    out = " ".join(kept).strip()
    return out or dialog.strip()


def _clean_dialog(dialog: str, name: str) -> str:
    """Strip bracket cues, surrounding quotes, and leaked ``Name:`` speaker prefixes."""
    cleaned = _strip_bracket_cues(dialog or "")
    prefix_re = re.compile(rf"^\s*{re.escape(name)}\s*:\s*", re.IGNORECASE)
    prev: str | None = None
    while prev != cleaned:
        prev = cleaned
        cleaned = prefix_re.sub("", cleaned)
    cleaned = _strip_performance_directives(cleaned)
    cleaned = cleaned.strip().strip('"').strip()
    return cleaned or (dialog or "").strip()


_DEFAULT_SFX_MAP: dict[str, Any] = {
    "sound effect": {
        "segment_type": "music_generator_foley_agent",
        "arguments": {
            "duration_min_sec": 1,
            "duration_max_sec": 60,
            "foley_max_duration_sec": 12,
        },
    },
    "background": {
        "segment_type": "music_generator_foley_ambience",
        "background_music": True,
        "arguments": {
            "duration_min_sec": 30,
            "duration_max_sec": 200,
        },
    },
    "default": {"segment_type": "slow_TTS", "arguments": {}},
}


_BASE_REALITY_RULE = (
    "Establish the scene in the opening exchange. Your first two lines of DIALOG "
    "must let a listener orient: where you are, what you are doing, and who your "
    "partner is (and your relationship) \u2014 through action and concrete detail, "
    "not exposition. Ground the base reality before fully committing to the "
    "unusual game, and keep picking up details of the world in later beats."
)


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

        establish_scene = bool(params.get("scene_establishment", True))
        establish_rule = (params.get("scene_establishment_instruction") or "").strip() or _BASE_REALITY_RULE
        self.slot_sessions: list[LlmSession] = []
        for slot_cfg in self.character_slots_cfg:
            m = (slot_cfg.get("model") or "").strip() or _DEFAULT_MODEL
            sys_m = slot_cfg.get("system_message") or (
                "You are an improv performer. Listen, yes-and, speak only in character."
            )
            if establish_scene:
                sys_m = f"{sys_m}\n\n{establish_rule}"
            self.slot_sessions.append(LlmSession(sys_m, model_slug=m))

        self.target_turn_count = int(params.get("target_turn_count", 20))
        self.scene_injection = (params.get("scene_injection") or "").strip()

        self.news_inspiration: dict[str, Any] | None = None
        news = params.get("news_inspiration")
        if news is True:
            self.news_inspiration = {"search_prompt": _DEFAULT_NEWS_INSPIRATION_PROMPT}
        elif isinstance(news, dict):
            cfg = dict(news)
            cfg.setdefault("search_prompt", _DEFAULT_NEWS_INSPIRATION_PROMPT)
            self.news_inspiration = cfg

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

    def _fetch_news_inspiration(self) -> str:
        """Best-effort weekly story for the director, or '' when unavailable."""
        cfg = self.news_inspiration
        if not cfg:
            return ""
        search_cfg = cfg.get("search") or {}
        model = cfg.get("model") or search_cfg.get("model")
        try:
            result = run_web_search(
                str(cfg["search_prompt"]),
                model=model,
                engine=search_cfg.get("engine"),
                max_results=search_cfg.get("max_results"),
                max_total_results=search_cfg.get("max_total_results"),
                search_context_size=search_cfg.get("search_context_size", "medium"),
                allowed_domains=search_cfg.get("allowed_domains"),
                excluded_domains=search_cfg.get("excluded_domains"),
            )
        except Exception as e:  # noqa: BLE001 - inspiration is best-effort
            logger.warning("News inspiration search failed: %s", e)
            return ""
        story = (result.content or "").strip()
        if not story:
            return ""
        return story[:_MAX_NEWS_INSPIRATION_CHARS]

    def _run_setup(self) -> SceneSetup:
        n = len(self.character_slots_cfg)
        inj = ""
        if self.scene_injection:
            inj = (
                "\nOptional producer constraint (must honor if it does not violate safety):\n"
                f"{self.scene_injection}\n"
            )
        insp = ""
        if self.news_inspiration:
            story = self._fetch_news_inspiration()
            if story:
                insp = (
                    "\nOptional real-world inspiration from this week's news (draw from it "
                    "if it sparks a seed; nothing here is a requirement):\n"
                    f"{story}\n"
                )
        prompt = (
            f"{self.setup_system_message}\n\n"
            f"You must define exactly {n} characters with slots 1..{n} in order. "
            "Each needs a distinct playable name and a one-sentence want or obstacle.\n"
            "Design one playable Game: a single unusual thing (an obsession, a wrong belief, "
            "a recurring behavior) that both performers can identify, commit to, and heighten. "
            "Make it concrete and grounded in the setting, not abstract. Give the Game multiple "
            "escalation vectors so the performers can heighten in kind (elaborating logic, "
            "reinterpreting reality, inverting authority, compounding commitment), not only "
            "in scale. Make the conflict axis NON-financial: the straight man's friction must "
            "not be primarily cost or feasibility. Pick the opposing force freely from a wider "
            "menu, e.g. a personal rule, a duty or code, a physical or practical constraint, a "
            "social obligation or status worry, a world-view or taste clash, a deadline, a "
            "relationship tension, or a personal stake. These are examples only: vary the type "
            "scene-to-scene, and occasionally wander beyond them \u2014 do NOT default to a "
            "policy, regulation, or bureaucrat.\n"
            "Also provide: setting, scenario (inciting incident), background_sound "
            "(short Freesound-style ambient query), and sfx_palette (3–5 short searchable SFX labels).\n"
            f"{insp}{inj}\n"
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

    def _turn_prompt(
        self,
        scene: SceneSetup,
        ch_name: str,
        transcript_parts: list[str],
        turn_index: int,
        is_final_beat: bool,
    ) -> str:
        palette = ", ".join(scene.sfx_palette) if scene.sfx_palette else ""
        palette_hint = (
            f"Prefer sounds from this palette when apt: {palette}. " if palette else ""
        )
        esc_move, sm_move = _rotating_moves(turn_index)

        if is_final_beat:
            move_line = (
                "\nTHIS IS THE FINAL BEAT \u2014 button the scene. Deliver ONE decisive closing "
                "line that pays off the game and lands, not merely continues it:\n"
                "- Callback: invoke an earlier object, phrase, or number from the transcript "
                "and reveal its full meaning (the straight man's code fulfilled, the escalator's "
                "obsession completed, a setup the audience clocked).\n"
                "- OR fulfill the premise's logical extreme: the final, most committed version "
                "of the game \u2014 the absurdity resolved in a clean, hard pop.\n"
                "- One clean line, hard stop. Do NOT open anything new, do NOT trail off, and "
                "do NOT add a tag-on, a 'yep', an 'exactly', or a restatement.\n"
                "Put the button mostly in dialog; a stage_direction or one SFX cue is allowed but optional.\n"
            )
        else:
            button_hint = ""
            if turn_index >= self.target_turn_count - 2:
                button_hint = (
                    "\nThe scene is building to its button. Once a beat lands the big laugh, "
                    "do not open a new escalation \u2014 the next beat should pay the game off.\n"
                )
            move_line = (
                "\nThis beat, play exactly ONE move. If you are the ESCALATOR: "
                f"{esc_move}. If you are the STRAIGHT MAN: {sm_move}. "
                "Break ties toward surprise.\n"
                f"{button_hint}"
            )

        return (
            "Transcript so far:\n"
            + "\n".join(transcript_parts)
            + f"\n\nYour turn, {ch_name}. Deliver the next beat as ONE structured turn:\n"
            "- dialog: two to four sentences of spoken words only, so the beat has room "
            "to land like a real podcast exchange. Do NOT prefix your name. "
            "Do NOT include stage directions or bracketed cues in dialog. "
            "Never put performance verbs or acting notes in dialog (hum, sing, whistle, "
            "laugh, sigh, 'you have to...') \u2014 those go in stage_direction, and the "
            "voice will otherwise perform them. "
            "End on the punchline; no 'you know'/'right?'/'exactly' padding, no compliment "
            "chains, no trailing tag-ons that restate the joke. If the setup is already paid "
            "off, subvert the predictable. Be specific: name the object, the brand, the number.\n"
            "- stage_direction: optional short acting note (not spoken). If this beat needs a "
            "song or hum, write it here as [SUNG: <what is sung, e.g. 'Happy Birthday'>]; "
            "keep the spoken dialog clean.\n"
            "- sfx_cues: at most ONE concrete, audible sound-effect search query, and only "
            "add a second if a sound is genuinely integral to the beat. "
            f"{palette_hint}"
            "Use real sounds (e.g. 'coffee machine steam', 'doorbell chime', 'chair scrape'), "
            "not emotions or gestures. Leave empty if no sound is warranted.\n"
            f"{move_line}"
        )

    def _sfx_segments_for_turn(
        self, turn: ImprovTurn, turn_index: int
    ) -> list[dict[str, Any]]:
        """Build sound-effect segments from structured cues (+ explicit bracket fallback)."""
        cues: list[str] = list(turn.sfx_cues)
        cues += _extract_bracket_cues(turn.stage_direction)
        cues += _extract_bracket_cues(turn.dialog)

        truncated = False
        if len(cues) > _MAX_SFX_CUES_PER_TURN:
            dropped = cues[_MAX_SFX_CUES_PER_TURN:]
            cues = cues[:_MAX_SFX_CUES_PER_TURN]
            truncated = True
            logger.warning(
                "Turn %d requested %d SFX cues (cap %d); dropping %s",
                turn_index,
                len(cues) + len(dropped),
                _MAX_SFX_CUES_PER_TURN,
                dropped,
            )

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
                    "truncated": truncated and cue == cues[-1],
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
                is_final = (turns_done + 1) >= self.target_turn_count
                prompt = self._turn_prompt(
                    scene, ch.name, transcript_parts, turns_done, is_final
                )

                raw = sess.run_structured(prompt, ImprovTurn)
                turn = ImprovTurn.model_validate(raw)
                dialog = _clean_dialog(turn.dialog, ch.name)

                sung = _extract_sung_cue(turn.stage_direction) or _extract_sung_cue(turn.dialog)
                beat_kind = "sung" if sung else "dialog"
                # A requested song/hum becomes a controlled performance directive for the
                # expressive Gemini TTS (it reliably hums/sings a clear instruction). Keep
                # it out of the spoken-prose path so we control when/why it performs.
                if sung:
                    dialog = f'You hum "{sung}".'

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
                        "kind": beat_kind,
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
