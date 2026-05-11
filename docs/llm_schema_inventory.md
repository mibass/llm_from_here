# LLM structured output schema inventory

YAML JSON Schema blocks were replaced by Pydantic models in `src/llm_from_here/schemas/llm_outputs.py`.

| Legacy YAML / location | Pydantic model | Call site |
| --- | --- | --- |
| `json_script_prompt` (configs v2/v3, `config.yaml`) | `IntroScriptLines` (`{ "lines": IntroLine[] }`) | `intro.py`, `introFromGuestlist.py` via `LlmSession.run_structured` |
| `json_guest_prompt` (configs v2, `config.yaml`) | `GuestListJson` (`{ "guests": GuestEntry[] }`) | `intro.py` |
| `llm_filter_js` (configs v2/v3 `llm_filter_*`, `includes/llm_filter_vars.yml`) | `LlmFilterResponse` | `ytfetch.py` `llm_filter_title` |
| `prompt_js` in `promptToSegment` prompts | **Removed** — use `output_model: "module:Class"` per prompt row | `promptToSegment.py` |
| Guest agent tool payloads (`guest_agent.py`) | `VideoResult` (search rows), `GuestSegment` (final pick) | `src/llm_from_here/models/guest_models.py` · `agents/guest_agent.py` · `segmentsToTimeline.agent_search` |
