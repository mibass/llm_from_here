# Episode release reporting templates

Use these templates after any **local** episode release run. Copy the relevant sections into chat or a run note.

---

## Release Run Summary

```markdown
# Episode Release Report

**Date:** YYYY-MM-DD HH:MM UTC
**Mode:** dev | prod | free
**Branch:** <git branch --show-current>
**Commit:** <git rev-parse --short HEAD>
**Working tree:** clean | dirty
**Command:** <exact ShowRunner invocation with env vars>
**Config:** configs/configv3.yaml
**Final status:** success | failure
**Output folder:** outputs/show_runN/
**Run ID (from logs):** <uuid from show_runner.log>

## Executive summary
<One paragraph: did the episode generate, publish, and meet quality bar?>

## Key outcomes
- Tests: pass | fail | skipped
- Show generated: yes | no
- Podbean published: yes | no | skipped (dev/free)
- Notable issues: <brief list or "none">
```

---

## Process Evaluation

Score each area **OK**, **WARN**, or **FAIL** with a one-line note.

```markdown
## Process evaluation

| Stage | Status | Notes |
|-------|--------|-------|
| Preflight / secrets | | |
| Unit tests (pytest) | | |
| Guest selection | | |
| YouTube search & filter | | |
| yt-dlp download | | |
| Intro/story music (Lyria / YouTube fallback) | | |
| TTS / narration render | | |
| Timeline assembly / ffmpeg | | |
| Podbean upload & publish | | |
| Supabase side effects | | |

**Overall verdict:** ship | retry | investigate
```

---

## Log Analysis Checklist

Work through in order. Log paths: `outputs/**/show_runner.log`, `outputs/**/agent_trace.log`.

```markdown
## Log analysis checklist

### show_runner.log
- [ ] Run completed (`phase=finalize` or clean exit; no unhandled Exception)
- [ ] `output_folder` path noted
- [ ] Each plugin reached `phase=execute` without ERROR (or expected `phase=skip`)
- [ ] Guest list populated (`introFromGuestlist` / `Found guests:`)
- [ ] YouTube segments resolved (no `No youtube audio result` without fallback success)
- [ ] Music path clear: Lyria attempt vs YouTube fallback logged
- [ ] TTS segments completed without timeout errors
- [ ] Podbean: publish logged (prod) or `only_in_prod` skip explained (dev/free)
- [ ] No repeated plugin failures across retries

### agent_trace.log
- [ ] Guest agent `pydantic_ai_run` entries present with non-empty `output`
- [ ] Filter LLM `kept: true` ratio reasonable (not all rejected)
- [ ] Rejected videos (`kept: false`) have sensible titles (not systematic false negatives)
- [ ] Token `usage` within expected range (no zero-usage failures)

### Artifacts
- [ ] Final audio file exists in run output folder
- [ ] Log paths confirmed under `outputs/show_runN/`
```

---

## Issue Recognition

Match log patterns to likely causes and suggested fixes.

### YouTube search & download

| Symptom | Likely cause | Suggested action |
|---------|--------------|------------------|
| `No youtube audio result` | Search returned nothing or download failed | Check `YT_API_KEY`; review guest/search query in log |
| yt-dlp extractor / JS errors | Missing Deno or stale cookies | Install Deno locally; set `YT_DLP_COOKIE_FILE` in `.env`; tune `YT_DLP_PLAYER_CLIENT` |
| DRM / format errors | Video blocked or wrong format | Try `YT_DLP_FORMAT`, `YT_DLP_VANILLA_FIRST`; grep `youtube_drm` in tests for patterns |
| Repeated irrelevant results | Weak search query or filter too permissive | Review `agent_trace.log` filter decisions; run `evals/eval_guest_agent.py` |
| All videos `kept: false` | Filter LLM too strict or wrong guest context | Inspect `filter_llm` entries; check `guest_name` / `title` pairs |
| Slow / timeout downloads | Network or `YT_DLP_SOCKET_TIMEOUT` too low | Increase timeout in `.env`; set `YT_DLP_VERBOSE=1` |

### Audio generation

| Symptom | Likely cause | Suggested action |
|---------|--------------|------------------|
| Lyria skipped immediately | `LLMFH_LYRIA_ENABLED` off or free mode | Expected in free mode; enable with `LLMFH_LYRIA_ENABLED=1` for prod-quality beds |
| Lyria failed → YouTube fallback | OpenRouter music API error | Run `scripts/diagnose_lyria.py`; check `OPENROUTER_API_KEY` and model |
| gTTS instead of paid TTS | `LLMFH_OPENROUTER_FREE_MODE=1` | Expected in free mode; unset for prod-quality TTS |
| ffmpeg / render errors | Missing ffmpeg or bad segment paths | `preflight_env.py --require-ffmpeg`; verify ffmpeg installed |
| Silent or clipped audio | Segment duration mismatch | Grep timeline/segment duration lines in `show_runner.log` |

### Podbean & environment

| Symptom | Likely cause | Suggested action |
|---------|--------------|------------------|
| Podbean skipped | `LLMFH_ENV` not `prod` or `only_in_prod: True` | Re-run with `LLMFH_ENV=prod` only when user wants publish |
| OAuth / upload failed | Bad `PODBEAN_CLIENT_ID` / `SECRET` | Verify `.env` creds; never log credential values |
| Wrong episode count | Auto-prune at `max_episodes: 3` | See [PODBEAN.md](PODBEAN.md) for manual delete |
| Dev data in prod queues | Accidental prod run from wrong branch | Confirm branch/commit and `LLMFH_ENV` before prod dispatch |
| Wrong guests in Podbean description | `podcastManager` / `stitchAudio` cache hit | Re-run prod with `--clear-cache`; delete bad episode if published |
| Old MP3 filename uploaded | `stitchAudio` served cached stitch path | Same as above — prod defaults to `--clear-cache` per skill |

### Guest agent & LLM

| Symptom | Likely cause | Suggested action |
|---------|--------------|------------------|
| Empty `output` in `pydantic_ai_run` | Model failure or schema rejection | Check OpenRouter status; review `new_messages` in trace |
| Same guests every run | Cache or small guest pool | Run with `--clear-cache`; check `scripts/run_until_new_guests.py` logic |
| High token usage | Long agent loops | Review attempt counts in trace `context` |

---

## Recommendations Template

```markdown
## Recommendations

### Immediate actions
1. <e.g. Re-run dev mode after fixing YT_DLP cookies in .env>
2. <e.g. Delete mistaken Podbean episode — see PODBEAN.md>

### Config / env changes
- <e.g. Set LLMFH_LYRIA_ENABLED=1 for Lyria beds on next prod run>
- <e.g. Set SUPABASE_STORAGE_BUCKET if uploads fail>

### Quality improvements
- <e.g. Tune guest filter prompts if too many kept: false>
- <e.g. Run eval_guest_agent.py on recurring guest>

### Release hygiene
- <e.g. Commit branch changes before prod publish>
- <e.g. Prod publish used `--clear-cache` unless user opted into cache>
- <e.g. Prod publish confirmed; schedule next dev smoke test>

### Retry decision
**Retry now?** yes | no — <reason>
**Safe to publish prod?** yes | no — <reason>
```

---

## Compact post-mortem (failure runs)

```markdown
# Episode Release Post-Mortem

**Branch / commit:** <branch> @ <sha>
**Output folder:** outputs/show_runN/
**Failed at:** <plugin / phase from show_runner.log>
**Error excerpt:**
```
<paste 3–10 relevant log lines>
```

**Root cause:** <one sentence>
**Fix applied / proposed:** <one sentence>
**Prevent recurrence:** <config, test, or monitoring change>
```
