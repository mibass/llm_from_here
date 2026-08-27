# Improv module

Generates a full improv scene as a playable podcast episode: an LLM director sets up
the scene, per-character LLMs trade structured beats, and an LLM **foley judge**
replaces dialog cues with real sound effects fetched from Freesound. Everything
renders down to plain WAV + WebVTT-style timeline HTML via the standard
`segmentsToTimeline` / `audioTimeline` pipeline.

## Pipeline

`improvAgent.py` -> `improv_script` -> `segmentsToTimeline` (SFX fetch + TTS) -> `audioTimeline` (render)

1. **Setup** — `SceneSetup` from `schemas/improv_outputs.py`. The director emits
   characters (with niche obsessions + escalation vectors), a grounded setting, an
   inciting scenario, a background ambience search query, and an `sfx_palette`.
 2. **Turns** — each character is a separate `LlmSession` with its own model/system
    message. Turns are `ImprovTurn {dialog, stage_direction, sfx_cues}`; a `TurnJudgement`
    per beat scores `coherence`, `yes_and`, `character_consistency` and can end the scene.
    A sung/hummed beat is signalled with `[SUNG: <what is sung>]` in `stage_direction`;
    it becomes a controlled performance directive for the expressive Gemini TTS (which
    otherwise may accidentally hum from performance prose leaking into `dialog`).
3. **Segments** — turns flatten to `ImprovSegment`s; SFX cues map to a `segment_type_map`
   (default `_DEFAULT_SFX_MAP`: `sound effect` -> `music_generator_freesound`,
   `background` -> `music_generator_foley_ambience`).
4. **Foley** — `FoleyAgent.resolve()` picks a real clip for each cue via an LLM judge
   over Freesound candidates (see *Foley/SFX* below).
5. **Audio** — TTS per segment, SFX overlaid, ambience bed looped, everything stitched
   into `audio_render.wav` + `audio_render_timeline.html`.

## Quick start

```bash
uv run python -m llm_from_here.showRunner configs/improv_agent.yaml --clear-cache --output-dir /tmp/improv_out
```

A lighter smoke config (< 1 min) is `configs/improv_agent_smoke.yaml`.

Diagnostics:

```bash
uv run python scripts/inspect_improv_scene.py                           # pretty-print improv_debug.json
uv run python evals/eval_improv_agent.py path/to/improv_debug.json      # LLM-as-judge quality eval
```

## Config reference (`configs/improv_agent.yaml`)

| Key | Meaning | Default |
| --- | --- | --- |
| `setup_model` | Model for the director setup call (`openrouter:<slug>`) | `openrouter:deepseek/deepseek-v4-flash` |
| `setup_system_message` | UCB-style direction for the director | built-in |
| `target_turn_count` | Max beats before forced resolution | `20` |
| `character_slots[].model` | Per-performer model | same as setup |
| `character_slots[].tts_voice` | TTS voice for the performer | `Puck` / `Fenrir` |
| `character_slots[].system_message` | Per-performer persona (escalator / straight man) | built-in |
| `scene_establishment` | Prepend base-reality orienting rule to every performer prompt | `true` |
| `scene_establishment_instruction` | Custom rule replacing the default (default = *first two lines must orient a listener: where, what, who*) | default rule |
| `foley_max_duration_sec` | Hard cap on any fetched SFX clip (fade-truncated downstream) | unset (no cap) |
| `news_inspiration` | Feed the director one familiar, notable news story from the week as optional inspiration (`true` for the default prompt, or a dict with `search_prompt` / `search` / `model`). Open to any topic; the model picks based on the search results. Best-effort; a failed search is logged and setup continues without it. | unset (off) |

Per-character scenes can be tuned by `setup_system_message` (niche obsessions, the
anti-cost-friction rule, multi-axis escalation). Structured-output schemas are tracked
in `docs/llm_schema_inventory.md`.

## Foley / SFX

`foleyAgent.py` defines a pluggable provider interface:

- `SoundProvider` protocol — `search(...)` + `download(...)`.
- `FreesoundProvider` — the shipped provider. Does **query trimming**: if a long
  natural-language cue (e.g. *"distant library hum ventilation rumble occasional page
  turn"*) returns no hits, it retries by dropping trailing tokens until results appear
  or a single token remains.
- `FoleyAgent.resolve(intent, duration_min_sec, duration_max_sec, model_slug, download_dir, sustained)`:
  searches, runs an LLM **foley judge** over candidates (`SfxJudgement {chosen_index,
  reasoning}`), downloads the pick, and returns a result dict (`status`, `file`,
  `selected`, `attempts`, `reason`).

Reliability behavior:

- Result dicts are cached per `intent` in an app cache; bump `_CACHE_VERSION` when the
  judge behavior changes so stale picks get re-judged. Impact clips are capped with an
  ict `_MAX_IMPACT_CLIP_SEC` constant.
- `SegmentsToTimeline.music_generator_freesound` truncates any fetched clip to
  `foley_max_duration_sec` (with a short fade) so long downloads never break pacing.
- `music_generator_foley_ambience` builds the sustained background bed; on a total
  Freesound miss it synthesizes a soft room-tone bed (`ambience_fallback`) so the
  background is never silently dropped (`ambience_fallback=False` skips the segment).
- Every SFX/ambience resolution is written to `foley_audit.json` (`cue_type`, `status`,
  `reason`, `selected`, `attempts`).

## Artifacts (per run folder)

- `improv_debug.json` — full structured scene, segments, turn audit (incl. per-turn
  judge scores).
- `foley_audit.json` — per-cue SFX resolution audit trail.
- `agent_trace.log` — pydantic-ai traces for traced agents.
- `improv_audio_*.wav` — per-segment TTS/SFX renders; `audio_render.wav` + timeline HTML is the final show.

## Notes on reliability

Improv depends on OpenRouter structured-output streaming. Under provider load you may
occasionally see `UnexpectedModelBehavior: Exceeded maximum output retries (5)` on a
turn — the plugin retries (`retries: 3`), and re-running with `--clear-cache` typically
recovers. Long SFX downloads can silently pause the pipeline for minutes; that is normal
and resolves on its own.