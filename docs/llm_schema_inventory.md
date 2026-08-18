# LLM structured output schema inventory

YAML JSON Schema blocks were replaced by Pydantic models in `src/llm_from_here/schemas/llm_outputs.py`.

| Legacy YAML / location | Pydantic model | Call site |
| --- | --- | --- |
| `json_script_prompt` (configs v2/v3, `config.yaml`) | `IntroScriptLines` (`{ "lines": IntroLine[] }`) | `intro.py`, `introFromGuestlist.py` via `LlmSession.run_structured` |
| `json_guest_prompt` (configs v2, `config.yaml`) | `GuestListJson` (`{ "guests": GuestEntry[] }`) | `intro.py` |
| `llm_filter_js` (configs v2/v3 `llm_filter_*`, `includes/llm_filter_vars.yml`) | `LlmFilterResponse` | `ytfetch.py` `llm_filter_title` |
| `prompt_js` in `promptToSegment` prompts | **Removed** — use `output_model: "module:Class"` per prompt row | `promptToSegment.py` |
| ImprovAgent setup / turn / SFX selection | `SceneSetup`, `TurnJudgement`, `SfxJudgement` in `schemas/improv_outputs.py` | `improvAgent.py`, `foleyAgent.py` via `LlmSession.run_structured` (see [docs/improv.md](improv.md)) |
| Story plugin (`configs/configv3.yaml` `story` promptToSegment) | `StoryScript` | `promptToSegment.py` via `run_structured` + `story_to_segments` |
| Outro plugin (`configs/configv3.yaml` `outro` promptToSegment) | `OutroScript` | `promptToSegment.py` via `run_structured` + `outro_to_segments` |
| Guest agent tool payloads (`guest_agent.py`) | `VideoResult` (search rows), `GuestSegment` (final pick) | `src/llm_from_here/models/guest_models.py` · `agents/guest_agent.py` · `segmentsToTimeline.agent_search` |
