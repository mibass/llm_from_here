import llm_from_here.plugins.showTTS as showTTS
import json
import os
import re
import shutil
import tempfile

from llm_from_here.gemini_tts import (
    LONGFORM_TTS_CHUNK_PAUSE_MS,
    build_longform_tts_prompt,
    prepare_narrator_tts_text,
    split_longform_transcript,
)
from llm_from_here.llm_env import is_lyria_enabled, is_openrouter_free_mode
from llm_from_here.openrouter_music import (
    generate_instrumental,
    normalize_story_music_prompt,
    youtube_fallback_query,
)
from pydub import AudioSegment

from llm_from_here.plugins.applause import generate_applause
import llm_from_here.plugins.freesoundfetch as freesoundfetch
from llm_from_here.plugins.foleyAgent import FoleyAgent
import llm_from_here.plugins.ytfetch as ytfetch
import llm_from_here.plugins.audioTimeline as audioTimeline

import logging
from typing import Any

from llm_from_here.agents.guest_agent import (
    GuestAgentDeps,
    get_guest_agent,
    strip_guest_queue_prefix,
    video_metadata_features_guest,
)
from llm_from_here.models.guest_models import GuestSegment
from llm_from_here.run_logging import log_pydantic_agent_trace

logger = logging.getLogger(__name__)


class SegmentsToTimeline:
    def __init__(self, params, global_results, plugin_instance_name):
        self.show_tts = None
        self.freesound_fetch = freesoundfetch.FreeSoundFetch(
            params, global_results, plugin_instance_name
        )
        self.yt_fetch = None
        self.chat_app_object = global_results.get(
            params.get("chat_app_object", "intro_chat_app"), None
        )
        self.global_results = global_results
        self.params = params
        self.plugin_instance_name = plugin_instance_name

        # check if a timeline already exists
        timeline_variable = params.get("timeline_variable", None)
        self.timeline = global_results.get(
            timeline_variable, audioTimeline.AudioTimeline()
        )
        if timeline_variable:
            logger.info(
                f"Using existing timeline in {timeline_variable}. Timeline length: {self.timeline.get_last_end_time()}"
            )
        else:
            logger.info(f"No timeline found. Creating new timeline.")

    def _segment_type_map(self) -> dict:
        """Use params.segment_type_map, or global_results[segment_type_map_variable] if set."""
        var_key = self.params.get("segment_type_map_variable")
        if var_key:
            m = self.global_results.get(var_key)
            if isinstance(m, dict) and m:
                logger.info("Using segment_type_map from global_results[%s]", var_key)
                return m
        return self.params.get("segment_type_map") or {}

    def applause_generator(self, text, output_file):
        # extract the duration from the text
        match = re.search(r"duration (\d+)", text)
        if match:
            duration = int(match.group(1)) * 1000
        else:
            duration = 3000
        logger.info(f"Generating applause of duration: {duration}")
        applause_segment = generate_applause(duration, 2000, 4000, 500)

        # Export to a new file
        with open(output_file, "wb") as f:
            applause_segment.export(f, format="wav")
            return True

    def silence_generator(self, text, output_file):
        match = re.search(r"duration\s*(\d+)", text, flags=re.IGNORECASE)
        duration_ms = int(match.group(1)) if match else 800
        logger.info("Generating silence of duration: %s ms", duration_ms)
        silence_segment = AudioSegment.silent(duration=duration_ms)
        with open(output_file, "wb") as f:
            silence_segment.export(f, format="wav")
            return True

    def music_generator_freesound(
        self,
        text,
        output_file,
        additional_query_text="",
        duration_min_sec=20,
        duration_max_sec=600,
    ):
        # extract the music type from the text
        match = re.search(r"\[MUSIC (.*?)\]", text)
        if match:
            music_type = match.group(1)
        else:
            # Strip a leading bracket label such as "[BACKGROUND: ...]" or "[SFX: ...]"
            # so the Freesound query is the inner text, not the decorated cue.
            label_match = re.fullmatch(r"\s*\[[A-Za-z ]+:?\s*(.*?)\]\s*", text)
            music_type = label_match.group(1) if label_match else text

        # extract the dir from output_file
        output_dir = os.path.dirname(output_file)
        self.freesound_fetch.out_dir = output_dir
        query = f"{music_type} {additional_query_text}".strip()
        logger.info(
            f"Retreiving freesound music with query: {query}, duration: {duration_min_sec} to {duration_max_sec}"
        )
        before = len(self.freesound_fetch.temp_files)
        # Try the duration-constrained search first, then fall back to an unconstrained
        # search so a slightly-too-specific duration filter doesn't drop the segment.
        attempts = [
            {"filter": f"duration:[{duration_min_sec} TO {duration_max_sec}]"},
            {},
        ]
        for attempt in attempts:
            try:
                self.freesound_fetch.search_and_download_top_samples(query, 1, attempt)
            except Exception as e:
                logger.warning(
                    "Freesound search/download failed for query %r; skipping segment: %s",
                    query,
                    e,
                )
                return None
            if len(self.freesound_fetch.temp_files) > before:
                shutil.move(self.freesound_fetch.temp_files[-1], output_file)
                return True
        logger.warning("No freesound results for query %r; skipping segment.", query)
        return None

    def _foley_cue_query(self, text: str, additional_query_text: str = "") -> str:
        """Extract a bare SFX search query, stripping any bracket label."""
        label_match = re.fullmatch(r"\s*\[[A-Za-z ]+:?\s*(.*?)\]\s*", text)
        cue = label_match.group(1) if label_match else text
        if additional_query_text:
            cue = f"{cue} {additional_query_text}".strip()
        return cue.strip()

    def _foley_agent(self, cache_dir: str | None = None) -> FoleyAgent:
        if getattr(self, "_foley_agent_obj", None) is None:
            self._foley_agent_obj = FoleyAgent(cache_dir=cache_dir)
        return self._foley_agent_obj

    def _record_foley_audit(self, cue: str, result: dict) -> None:
        out_folder = self.global_results.get("output_folder")
        if not out_folder:
            return
        path = os.path.join(out_folder, "foley_audit.json")
        try:
            rows: list = []
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        rows = loaded
            rows.append(
                {
                    "cue": cue,
                    "status": result.get("status"),
                    "reason": result.get("reason"),
                    "selected": result.get("selected"),
                    "attempts": result.get("audit", {}).get("attempts"),
                }
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, default=str)
        except OSError as e:
            logger.error("Could not write foley_audit.json: %s", e)

    def music_generator_foley_agent(
        self,
        text,
        output_file,
        duration_min_sec=1,
        duration_max_sec=60,
        additional_query_text="",
        model=None,
        cache_dir=None,
    ):
        """LLM-in-the-loop SFX fetch via FoleyAgent; silence pad preserves pacing on miss."""
        cue = self._foley_cue_query(text, additional_query_text)
        if not cue:
            logger.warning("Empty foley cue; writing silence pad.")
            self.silence_generator("duration 700", output_file)
            return True
        result = self._foley_agent(cache_dir).resolve(
            intent=cue,
            duration_min_sec=int(duration_min_sec),
            duration_max_sec=int(duration_max_sec),
            model_slug=model,
            download_dir=os.path.dirname(output_file) or None,
        )
        self._record_foley_audit(cue, result)
        status = result.get("status")
        file_path = result.get("file")
        if status in ("hit", "cached") and file_path and os.path.isfile(file_path):
            shutil.copyfile(file_path, output_file)
            logger.info(
                "Foley %s for %r -> %s", status, cue, result.get("selected") or {}
            )
            return True
        logger.warning(
            "Foley miss for %r (%s); writing silence pad.",
            cue,
            result.get("reason", status),
        )
        self.silence_generator("duration 700", output_file)
        return True

    def music_generator_openrouter(self, text, output_file, **kwargs):
        music_cue_profile = kwargs.pop("music_cue_profile", None)
        cue_text = (
            normalize_story_music_prompt(text)
            if music_cue_profile == "story"
            else text
        )

        fallback_segment_type = kwargs.pop("fallback_segment_type", "youtube_search")
        fallback_kwargs = dict(kwargs)
        if fallback_segment_type == "youtube_search":
            fallback_kwargs.setdefault(
                "additional_query_text",
                fallback_kwargs.get("additional_query_text", "instrumental live"),
            )
            search_text = youtube_fallback_query(cue_text)
            logger.info(
                "Lyria fallback youtube_search query from cue: %r", search_text
            )
            fallback_call = lambda: getattr(self, fallback_segment_type)(
                search_text, output_file, **fallback_kwargs
            )
        else:
            fallback_call = lambda: getattr(self, fallback_segment_type)(
                text, output_file, **fallback_kwargs
            )

        if is_openrouter_free_mode():
            logger.info(
                "LLMFH_OPENROUTER_FREE_MODE: skipping Lyria, using %s",
                fallback_segment_type,
            )
            return fallback_call()

        if not is_lyria_enabled():
            logger.info(
                "LLMFH_LYRIA_ENABLED is off: skipping Lyria, using %s",
                fallback_segment_type,
            )
            return fallback_call()

        try:
            return generate_instrumental(cue_text, output_file)
        except Exception:
            logger.warning(
                "OpenRouter Lyria music generation failed; falling back to %s",
                fallback_segment_type,
                exc_info=True,
            )
            return fallback_call()

    def tts(self, text, output_file, fast_tts=True, voice=None, tts_model=None):
        if self.show_tts is None:
            self.show_tts = showTTS.ShowTextToSpeech()
        text_filtered = prepare_narrator_tts_text(text)

        if text != text_filtered:
            logger.info(
                f"Filtered out text. Original: {text}. Filtered: {text_filtered}"
            )
        if len(text_filtered.strip()) == 0:
            logger.info(f"Text is empty after filtering. Skipping TTS.")
            return None
        else:
            speak_kw: dict[str, Any] = {"fast": fast_tts}
            if voice is not None:
                speak_kw["voice"] = voice
            if tts_model is not None:
                speak_kw["model"] = tts_model
            self.show_tts.speak(text_filtered, output_file, **speak_kw)

        return {}

    def fast_TTS(self, text, output_file, **kwargs):
        voice = kwargs.pop("voice", None)
        tts_model = kwargs.pop("tts_model", None)
        if kwargs:
            logger.warning("fast_TTS ignoring unknown kwargs: %s", list(kwargs.keys()))
        return self.tts(text, output_file, fast_tts=True, voice=voice, tts_model=tts_model)

    def slow_TTS(self, text, output_file, **kwargs):
        voice = kwargs.pop("voice", None)
        tts_model = kwargs.pop("tts_model", None)
        if kwargs:
            logger.warning("slow_TTS ignoring unknown kwargs: %s", list(kwargs.keys()))
        return self.tts(text, output_file, fast_tts=False, voice=voice, tts_model=tts_model)

    def gemini_longform_TTS(self, text, output_file, **kwargs):
        """Render one story block with Gemini's advanced long-form prompt structure."""
        if self.show_tts is None:
            self.show_tts = showTTS.ShowTextToSpeech()

        voice = kwargs.pop("voice", None)
        tts_model = kwargs.pop("tts_model", None)
        max_chunk_chars = int(kwargs.pop("max_chunk_chars", 750))
        chunk_pause_ms = int(kwargs.pop("chunk_pause_ms", LONGFORM_TTS_CHUNK_PAUSE_MS))
        section = kwargs.pop("section", None)
        prompt_kw: dict[str, str] = {}
        for key in ("audio_profile", "scene", "director_notes", "sample_context"):
            val = kwargs.pop(key, None)
            if val is not None:
                prompt_kw[key] = val
        if section is not None:
            prompt_kw["section"] = section
        if kwargs:
            logger.warning(
                "gemini_longform_TTS ignoring unknown kwargs: %s", list(kwargs.keys())
            )

        chunks = split_longform_transcript(text, max_chars=max_chunk_chars)
        if not chunks:
            logger.info("Skipping long-form TTS: empty transcript")
            return None

        speak_kw: dict[str, Any] = {}
        if voice is not None:
            speak_kw["voice"] = voice
        if tts_model is not None:
            speak_kw["model"] = tts_model

        if len(chunks) == 1:
            try:
                prompt = build_longform_tts_prompt(
                    chunks[0], chunk_index=0, chunk_total=1, **prompt_kw
                )
            except ValueError as err:
                logger.info("Skipping long-form TTS: %s", err)
                return None
            self.show_tts.speak_longform(prompt, output_file, **speak_kw)
            return {}

        combined = AudioSegment.empty()
        previous_tail: str | None = None
        for i, chunk in enumerate(chunks):
            try:
                prompt = build_longform_tts_prompt(
                    chunk,
                    chunk_index=i,
                    chunk_total=len(chunks),
                    previous_tail=previous_tail,
                    **prompt_kw,
                )
            except ValueError as err:
                logger.warning("Skipping long-form TTS chunk %s: %s", i + 1, err)
                continue

            fd, tmp_audio = tempfile.mkstemp(
                suffix=".wav", prefix=f"llmfh_longform_{i:02d}_"
            )
            os.close(fd)
            try:
                self.show_tts.speak_longform(prompt, tmp_audio, **speak_kw)
                segment = AudioSegment.from_wav(tmp_audio)
                combined += segment
                if i < len(chunks) - 1 and chunk_pause_ms > 0:
                    combined += AudioSegment.silent(duration=chunk_pause_ms)
            finally:
                try:
                    os.remove(tmp_audio)
                except OSError:
                    pass

            prepared_chunk = prepare_narrator_tts_text(chunk)
            previous_tail = prepared_chunk[-120:] if prepared_chunk else None

        if len(combined) == 0:
            logger.info("No long-form TTS audio generated after chunking")
            return None

        combined.export(output_file, format="wav")
        return {}
        
    def init_ytfetch(self, **kwargs):
        if self.yt_fetch is None:
            self.yt_fetch = ytfetch.YtFetch(**kwargs)

    def youtube_search(self, text, output_file, **kwargs):
        self.init_ytfetch(**kwargs)
        additional_query_text = kwargs.get("additional_query_text", "")

        query = f"{text} {additional_query_text}"
        logger.info(f"Retreiving youtube audio with query: {query}")
        kwargs["chat_app"] = self.chat_app_object

        res = self.yt_fetch.search_and_download_audio_with_duration(
            query, output_file, **kwargs
        )

        if res is None:
            logger.warning(f"No youtube audio result found for query: {query}")
            return None
        else:
            logger.info(
                f"Retreived youtube audio result with title: {res.get('title','')} {res.get('video_url','')}"
            )
            return res

    def youtube_playlist(self, text, output_file, **kwargs):
        playlist_id = kwargs.get("playlist_id")
        logger.info(f"Retreiving youtube playlist item with id: {playlist_id}")

        self.init_ytfetch(**kwargs)

        res = self.yt_fetch.download_random_video_from_playlist(
            playlist_id, output_file
        )
        logger.info(
            f"Retreived youtube audio result with title: {res.get('title','')} {res.get('video_url','')}"
        )
        return res

    def agent_search(self, guest_name, output_file, *, guest_category: str = "", **kwargs):
        """Guest clip discovery via pydantic-ai + YouTube Data API + yt-dlp download.

        Retries fresh agent runs when picks fail validation or collide with ``excluded_video_ids``.
        ``guest_clip_max_attempts`` (from kwargs, default 4) caps attempts per call.
        """
        attempt_kw = int(kwargs.pop("guest_clip_max_attempts", 4))
        max_attempts = max(1, attempt_kw)
        excluded: set[str] = set(kwargs.pop("excluded_video_ids", None) or [])

        self.init_ytfetch(**kwargs)
        duration_min_sec = int(kwargs.get("duration_min_sec", 300))
        duration_max_sec = int(kwargs.get("duration_max_sec", 660))

        match_name = strip_guest_queue_prefix(guest_name or "")
        agent = get_guest_agent()

        for attempt in range(1, max_attempts + 1):
            deps = GuestAgentDeps(
                yt_fetch=self.yt_fetch,
                duration_min_sec=duration_min_sec,
                duration_max_sec=duration_max_sec,
                guest_category=guest_category or "guest",
                guest_name=guest_name or "",
                guest_match_name=match_name,
            )
            user_msg = (
                f'Guest category: {deps.guest_category}. Guest name: "{match_name}". '
                "Find one appropriate YouTube clip for this guest segment."
            )
            if excluded:
                user_msg += (
                    " Do NOT choose any of these video IDs (already rejected or used): "
                    + ", ".join(sorted(excluded))
                    + "."
                )

            try:
                run_result = agent.run_sync(user_msg, deps=deps)
                raw_seg = run_result.output
                segment = (
                    raw_seg
                    if isinstance(raw_seg, GuestSegment)
                    else GuestSegment.model_validate(raw_seg)
                )
                log_pydantic_agent_trace(
                    "guest_agent.agent_search",
                    run_result,
                    context={
                        "guest_name": guest_name,
                        "guest_category": guest_category,
                        "attempt": attempt,
                        "run_id": self.global_results.get("run_id"),
                        "output_folder": self.global_results.get("output_folder"),
                    },
                    output_extra=segment,
                )
            except Exception as err:
                logger.exception(
                    "guest_agent.run_sync failed (attempt %s/%s): %s",
                    attempt,
                    max_attempts,
                    err,
                )
                continue

            video_url = f"https://www.youtube.com/watch?v={segment.video_id}"
            if segment.video_id in excluded:
                logger.info(
                    "guest_agent returned excluded video_id=%s; retrying (%s/%s)",
                    segment.video_id,
                    attempt,
                    max_attempts,
                )
                continue

            try:
                meta = self.yt_fetch.get_video_basic_info(segment.video_id)
                video_title = meta["title"]
                description = meta.get("description") or ""
            except Exception as err:
                logger.warning("Invalid agent video_id=%s: %s", segment.video_id, err)
                excluded.add(segment.video_id)
                continue

            if not video_metadata_features_guest(match_name, video_title, description):
                logger.warning(
                    "Skipping agent pick %s (%r): metadata does not match guest %r (attempt %s/%s)",
                    segment.video_id,
                    video_title,
                    guest_name,
                    attempt,
                    max_attempts,
                )
                excluded.add(segment.video_id)
                continue

            if not self.yt_fetch.youtube_video_has_extractable_audio(video_url):
                logger.warning(
                    "Skipping agent pick %s (%r): no extractable audio",
                    segment.video_id,
                    video_title,
                )
                excluded.add(segment.video_id)
                continue

            if not self.yt_fetch.video_ids_returned.add(segment.video_id):
                logger.info(
                    "Video %s already used in this episode; retrying guest_agent (%s/%s)",
                    segment.video_id,
                    attempt,
                    max_attempts,
                )
                excluded.add(segment.video_id)
                continue

            try:
                self.yt_fetch.download_audio(video_url, output_file)
            except Exception as err:
                logger.exception("download_audio failed for %s: %s", video_url, err)
                excluded.add(segment.video_id)
                continue

            duration_sec = len(AudioSegment.from_file(output_file)) / 1000.0
            logger.info(
                "Agent guest clip: guest=%r video=%s title=%r duration_sec=%.1f",
                guest_name,
                segment.video_id,
                video_title,
                duration_sec,
            )
            return {
                "title": video_title,
                "video_url": video_url,
                "duration_sec": duration_sec,
            }

        logger.warning(
            "agent_search exhausted %s attempts for guest=%r category=%r",
            max_attempts,
            guest_name,
            guest_category,
        )
        return None

    @staticmethod
    def _normalized_guest_key(name: str) -> str:
        return (name or "").strip().lower()

    def _dequeue_fallback_guest_row(self, category: str, used_normalized: set[str]) -> dict | None:
        """Pull another name from the same Supabase queue used by ``guest_selection``."""
        prefix = self.params.get("guest_fallback_queue_key_prefix", "guest_selection_")
        cat = (category or "").strip().lower()
        key = f"{prefix}{cat}"
        sq = self.global_results.get(key)
        if sq is None or not hasattr(sq, "dequeue"):
            logger.debug("No SupaQueue at %r for fallback dequeue", key)
            return None
        for _ in range(80):
            batch = sq.dequeue(1)
            if not batch:
                logger.info("Fallback dequeue exhausted for queue %r", key)
                return None
            name = batch[0]
            nk = self._normalized_guest_key(name)
            if nk in used_normalized:
                logger.info("Fallback dequeued duplicate guest %r; continuing", name)
                continue
            return {"guest_name": name, "guest_category": cat}
        return None

    def _resolve_segment_type(self, entry: dict, type_key: str, segment_type_map: dict) -> str | None:
        segment_type = entry[type_key].lower()
        if segment_type not in segment_type_map:
            if "default" not in segment_type_map:
                logger.warning(
                    "No function found for segment type: %s and no default set. Skipping segment.",
                    segment_type,
                )
                return None
            logger.debug(
                "No segment_type_map entry for %r; using default.",
                segment_type,
            )
            segment_type = "default"
        return segment_type

    def _attach_guest_clip_to_timeline(
        self,
        *,
        i: int,
        entry: dict,
        type_key: str,
        value_key: str,
        file_path: str,
        res: dict,
        segment_type: str,
        segment_type_map: dict,
        segment_transition_map: list | None,
        output_folder: str,
        background_music: bool,
        background_end_fade_ms: int | None = None,
    ) -> float:
        """Intro TTS + applause + clip on timeline. Returns clip duration in seconds."""
        title = res.get("title") if isinstance(res, dict) else None

        if segment_type_map[segment_type].get("intro_name", False) and title:
            intro_file_name = f"{self.plugin_instance_name}_{i:03d}_intro_name.wav"
            intro_file_path = os.path.join(output_folder, intro_file_name)
            prompt = segment_type_map[segment_type].get("intro_prompt", None)
            if prompt and self.chat_app_object:
                intro_prompt = prompt + entry[value_key] + ":::" + title
                logger.info(f"Prompting chat app with: {intro_prompt}")
                intro_text = self.chat_app_object.chat(intro_prompt, strip_quotes=True)
            else:
                intro_text = "Ladies and gentlemen... {intro_text}"

            fast_tts = segment_type_map[segment_type].get("fast_tts", True)
            self.tts(intro_text, intro_file_path, fast_tts=fast_tts)

            afp_kwargs = self.get_transition_map_entry(
                segment_transition_map, "intro_name"
            )
            self.timeline.add_after_previous(
                intro_file_path,
                label=audioTimeline.SegmentLabel.FOREGROUND,
                name=f"intro_name_{i}",
                type="intro_name",
                **afp_kwargs,
            )
            logger.info(f"Generated intro name for: {intro_text}")

        if segment_type_map[segment_type].get("intro_applause", False):
            applause_file_name = f"{self.plugin_instance_name}_{i:03d}_intro_applause.wav"
            applause_file_path = os.path.join(output_folder, applause_file_name)
            self.applause_generator("duration 3", applause_file_path)

            afp_kwargs = self.get_transition_map_entry(
                segment_transition_map, "intro_applause"
            )
            self.timeline.add_after_previous(
                applause_file_path,
                label=audioTimeline.SegmentLabel.FOREGROUND,
                name=f"intro_applause_{i}",
                type="intro_applause",
                **afp_kwargs,
            )
            logger.info("Generated applause")

        afp_kwargs = self.get_transition_map_entry(
            segment_transition_map, entry[type_key]
        )
        logger.info(
            "Adding %s to timeline as label %s and args %s",
            entry[type_key],
            audioTimeline.SegmentLabel.BACKGROUND
            if background_music
            else audioTimeline.SegmentLabel.FOREGROUND,
            afp_kwargs,
        )
        timeline_kwargs = dict(afp_kwargs)
        if background_music and background_end_fade_ms:
            timeline_kwargs["end_fade_ms"] = background_end_fade_ms
        self.timeline.add_after_previous(
            file_path,
            label=audioTimeline.SegmentLabel.BACKGROUND
            if background_music
            else audioTimeline.SegmentLabel.FOREGROUND,
            name=title if title else f"{entry[type_key]}_{i}",
            type=entry[type_key],
            **timeline_kwargs,
        )

        dur = float(res.get("duration_sec") or 0.0)
        if dur <= 0 and os.path.isfile(file_path):
            dur = len(AudioSegment.from_file(file_path)) / 1000.0
        return dur

    def _try_agent_guest_clip(
        self,
        *,
        entry: dict,
        segment_index: int,
        type_key: str,
        value_key: str,
        segment_type: str,
        segment_type_map: dict,
        segment_transition_map: list | None,
        output_folder: str,
        background_music: bool,
        max_attempts: int,
        background_end_fade_ms: int | None = None,
    ) -> float | None:
        """Run agent_search (+ timeline hooks). Returns clip duration sec or None."""
        filename_prefix = f"{self.plugin_instance_name}_{segment_index:03d}"
        filename = filename_prefix + ".wav"
        file_path = os.path.join(output_folder, filename)
        function_arguments = dict(segment_type_map[segment_type].get("arguments", {}))
        logger.info(
            "Generating audio for type: %s using agent_search with value: %s",
            entry[type_key],
            entry[value_key],
        )
        res = self.agent_search(
            entry[value_key],
            file_path,
            guest_category=entry[type_key],
            guest_clip_max_attempts=max_attempts,
            **function_arguments,
        )
        if res is None:
            logger.info("No audio generated for type: %s", entry[type_key])
            return None
        return self._attach_guest_clip_to_timeline(
            i=segment_index,
            entry=entry,
            type_key=type_key,
            value_key=value_key,
            file_path=file_path,
            res=res,
            segment_type=segment_type,
            segment_type_map=segment_type_map,
            segment_transition_map=segment_transition_map,
            output_folder=output_folder,
            background_music=background_music,
            background_end_fade_ms=background_end_fade_ms,
        )

    def _generate_guest_audio_target_duration(self):
        """Fill guest clips until ``target_guest_audio_sec`` using retries + queue fallbacks."""
        output_folder = self.global_results["output_folder"]
        type_key = self.params.get("segment_type_key", "speaker")
        value_key = self.params.get("segment_value_key", "dialog")
        segment_type_map = self.params.get("segment_type_map", {})
        segment_transition_map = self.params.get("segment_transition_map", [])
        target_sec = float(self.params["target_guest_audio_sec"])
        max_attempts = int(self.params.get("guest_clip_max_attempts", 4))
        max_fb_attempts = int(self.params.get("guest_fallback_max_attempts", 48))
        replace_on_fail = bool(self.params.get("guest_replace_on_primary_failure", True))

        primary = self.get_data(type_key, value_key)
        fb_categories = self.params.get("guest_fallback_categories")
        if not fb_categories:
            fb_categories = sorted({e[type_key].lower() for e in primary})
        fb_categories = [str(c).lower() for c in fb_categories]

        used_norm = {self._normalized_guest_key(e[value_key]) for e in primary}
        accum_sec = 0.0
        segment_idx = 0
        rr = 0
        fb_attempts = 0

        def segment_bg_flag(seg_t: str) -> bool:
            return bool(segment_type_map[seg_t].get("background_music", False))

        for entry in primary:
            seg_type = self._resolve_segment_type(entry, type_key, segment_type_map)
            if seg_type is None:
                segment_idx += 1
                continue
            bg = segment_bg_flag(seg_type)

            dur = self._try_agent_guest_clip(
                entry=entry,
                segment_index=segment_idx,
                type_key=type_key,
                value_key=value_key,
                segment_type=seg_type,
                segment_type_map=segment_type_map,
                segment_transition_map=segment_transition_map,
                output_folder=output_folder,
                background_music=bg,
                max_attempts=max_attempts,
            )
            if dur is None and replace_on_fail:
                fb_row = self._dequeue_fallback_guest_row(entry[type_key], used_norm)
                if fb_row:
                    used_norm.add(self._normalized_guest_key(fb_row[value_key]))
                    logger.info(
                        "Primary guest clip failed; trying fallback guest %r (%s)",
                        fb_row[value_key],
                        fb_row[type_key],
                    )
                    fb_seg = self._resolve_segment_type(fb_row, type_key, segment_type_map)
                    if fb_seg is not None:
                        dur = self._try_agent_guest_clip(
                            entry=fb_row,
                            segment_index=segment_idx,
                            type_key=type_key,
                            value_key=value_key,
                            segment_type=fb_seg,
                            segment_type_map=segment_type_map,
                            segment_transition_map=segment_transition_map,
                            output_folder=output_folder,
                            background_music=segment_bg_flag(fb_seg),
                            max_attempts=max_attempts,
                        )

            if dur is not None:
                accum_sec += dur
                logger.info(
                    "Guest audio accumulated %.1fs / target %.1fs after %s",
                    accum_sec,
                    target_sec,
                    entry[value_key],
                )
            segment_idx += 1

        while accum_sec < target_sec and fb_attempts < max_fb_attempts:
            if not fb_categories:
                break
            fb_attempts += 1
            cat = fb_categories[rr % len(fb_categories)]
            rr += 1
            fb_row = self._dequeue_fallback_guest_row(cat, used_norm)
            if not fb_row:
                continue
            used_norm.add(self._normalized_guest_key(fb_row[value_key]))
            seg_type = self._resolve_segment_type(fb_row, type_key, segment_type_map)
            if seg_type is None:
                continue
            dur = self._try_agent_guest_clip(
                entry=fb_row,
                segment_index=segment_idx,
                type_key=type_key,
                value_key=value_key,
                segment_type=seg_type,
                segment_type_map=segment_type_map,
                segment_transition_map=segment_transition_map,
                output_folder=output_folder,
                background_music=segment_bg_flag(seg_type),
                max_attempts=max_attempts,
            )
            if dur is not None:
                accum_sec += dur
                segment_idx += 1
                logger.info(
                    "Guest audio accumulated %.1fs / target %.1fs (fallback %s)",
                    accum_sec,
                    target_sec,
                    fb_row[value_key],
                )

        if accum_sec < target_sec:
            logger.warning(
                "target_guest_audio_sec not reached: %.1fs of %.1fs (fallback_attempts=%s)",
                accum_sec,
                target_sec,
                fb_attempts,
            )

    def get_transition_map_entry(self, segment_transition_map, to_type):
        if segment_transition_map is not None and len(segment_transition_map) > 0:
            to_type = to_type.lower()
            logger.info(
                f"Getting transition map entry for map {segment_transition_map} and type {to_type}"
            )
            from_type = self.timeline.get_last_type()
            if from_type:
                from_type = from_type.lower()
            if to_type:
                to_type = to_type.lower()
            logger.info(f"Last type was {from_type}")

            # segment_transition_map is a list of dicts, each dict is a transition map
            # find the from_type in the transition map, if it exists
            f = [
                d.get(from_type if from_type in d else "any")
                for d in segment_transition_map
                if from_type in d or "any" in d
            ]
            if len(f) > 0:
                logger.info(
                    f"Found from_type {from_type} in transition map, with entries {f}"
                )
                # find the to_type in the transition map, if it exists
                t = [
                    d.get(to_type if to_type in d else "any")
                    for d in f
                    if to_type in d or "any" in d
                ]
                if len(t) > 0:
                    logger.info(
                        f"Found to_type {to_type} in transition map, with entries {t}"
                    )
                    if len(t) > 1:
                        logger.warning(
                            f"Found multiple to_type entries in transition map. Using first."
                        )
                    return t[0]
        return {}

    def get_data(self, type_key, value_key):
        data = self.global_results.get(self.params.get("segments_object"))
        stm = self._segment_type_map()
        if not data:
            logger.info(f"No data found. Using segment_type_map instead.")
            # if no data, assume segment_type_map is the list
            data = []
            for k, _ in stm.items():
                data.append({type_key: k, value_key: ""})
            logger.info(f"Data is now: {data}")
        return data

    def generate_audio_segments(self):
        output_folder = self.global_results["output_folder"]
        type_key = self.params.get("segment_type_key", "speaker")
        value_key = self.params.get("segment_value_key", "dialog")
        single_background = self.params.get("single_background", False)
        segment_type_map = self._segment_type_map()
        segment_transition_map = self.params.get("segment_transition_map", {})

        use_agent = self.params.get("use_agent", False)
        if use_agent and self.params.get("target_guest_audio_sec") is not None:
            self._generate_guest_audio_target_duration()
            return

        max_attempts = int(self.params.get("guest_clip_max_attempts", 4))
        background_seen = False
        background_end_fade_ms = self.params.get("background_end_fade_ms")
        for i, entry in enumerate(self.get_data(type_key, value_key)):
            filename_prefix = f"{self.plugin_instance_name}_{i:03d}"
            filename = filename_prefix + ".wav"
            file_path = os.path.join(output_folder, filename)

            segment_type = self._resolve_segment_type(entry, type_key, segment_type_map)
            if segment_type is None:
                continue

            function_name = segment_type_map[segment_type].get("segment_type")
            function_arguments = segment_type_map[segment_type].get("arguments", {})

            # only allow one background music segment, if enabled
            background_music = segment_type_map[segment_type].get(
                "background_music", False
            )
            if background_music and single_background and background_seen:
                logger.info(
                    f"Skipping background music segment because single_background is enabled and background_seen is True."
                )
                continue

            logger.info(
                f"Generating audio for type: {entry[type_key]} "
                f"using {'agent_search' if use_agent else function_name} "
                f"with value: {entry[value_key]} and arguments {function_arguments}"
            )
            if use_agent:
                dur = self._try_agent_guest_clip(
                    entry=entry,
                    segment_index=i,
                    type_key=type_key,
                    value_key=value_key,
                    segment_type=segment_type,
                    segment_type_map=segment_type_map,
                    segment_transition_map=segment_transition_map,
                    output_folder=output_folder,
                    background_music=background_music,
                    max_attempts=max_attempts,
                    background_end_fade_ms=background_end_fade_ms,
                )
                if dur is None:
                    logger.info(f"No audio generated for type: {entry[type_key]}")
                continue

            res = getattr(self, function_name)(
                entry[value_key], file_path, **function_arguments
            )

            if res is None:
                logger.info(f"No audio generated for type: {entry[type_key]}")
                continue  # None indicates no audio was generated

            self._attach_guest_clip_to_timeline(
                i=i,
                entry=entry,
                type_key=type_key,
                value_key=value_key,
                file_path=file_path,
                res=res if isinstance(res, dict) else {},
                segment_type=segment_type,
                segment_type_map=segment_type_map,
                segment_transition_map=segment_transition_map,
                output_folder=output_folder,
                background_music=background_music,
                background_end_fade_ms=background_end_fade_ms,
            )

            if background_music:
                background_seen = True

    def execute(self):
        segments_key = self.params.get("segments_object")
        data = self.global_results.get(segments_key)
        if self.params.get("skip_if_no_segments") and not data:
            logger.info(
                "skip_if_no_segments: no segments at %r; leaving timeline unchanged",
                segments_key,
            )
            self.timeline.set_end_times()
            return {"timeline": self.timeline}
        self.generate_audio_segments()

        # set the end times for all background segments
        self.timeline.set_end_times()

        return {"timeline": self.timeline}

    def finalize(self):
        logger.info(f"Finalizing {self.__class__.__name__}")
        if self.yt_fetch is not None:
            self.yt_fetch.finalize()
